"""Orchestrates Stages 1-4: simulate(config, policy_name) -> dict of minute-resolution
DataFrames for every asset/meter, plus weather/production context and fault labels.
build_db.py aggregates these to 15-minute output and writes the SQLite tables.
"""
import numpy as np
import pandas as pd

from generator import calendar as cal
from generator import weather as wx
from generator import production as prod
from generator import compressor as cmp
from generator import chiller as chl
from generator import furnace as fur
from generator import paint_booth as pb
from generator import cnc as cnc_mod
from generator import solar as sol
from generator import main_meter as mm
from generator import noise as noise_mod
from generator import faults as flt


def _asset_cfg(config, asset_id):
    for a in config["assets"]:
        if a["asset_id"] == asset_id:
            return a
    raise KeyError(asset_id)


def _broadcast_air_demand(minute_df, air_demand_df, families):
    """Spread per-(date,shift) m3/min demand for the given families evenly across
    the minutes of that shift."""
    n = len(minute_df)
    out = np.zeros(n)
    lookup = {(r["date"], r["shift"]): r["air_demand_m3min"] for _, r in air_demand_df.iterrows()}
    dates = minute_df["date"].to_numpy()
    shifts = minute_df["shift"].to_numpy()
    keys = list(zip(dates, shifts))
    out = np.array([lookup.get(k, 0.0) for k in keys])
    return out


def simulate(config, policy_name):
    policy = config["policy"][policy_name]
    rng = np.random.default_rng(config["seed"])

    minute_df = cal.build_minute_frame(config)
    minute_df = wx.build_weather(minute_df, config, rng)
    daily_prod = prod.build_daily_production(minute_df, config, rng)

    hadapsar_families = ["gearbox", "compressor_package"]
    nashik_families = ["refrigeration_package"]
    air_demand_all = prod.production_air_demand_m3min(daily_prod, config)
    had_prod_df = daily_prod[daily_prod["family"].isin(hadapsar_families)]
    had_air_demand = prod.production_air_demand_m3min(had_prod_df, config)
    nas_prod_df = daily_prod[daily_prod["family"].isin(nashik_families)]
    nas_air_demand = prod.production_air_demand_m3min(nas_prod_df, config)

    fault_masks = flt.build_fault_masks(minute_df, config)
    n = len(minute_df)

    results = {}

    # --- Paint booth (feeds Hadapsar header demand) ---
    paint_cfg = _asset_cfg(config, "PAINT-BOOTH-01")
    fan_overrun_key = ("PAINT-BOOTH-01", "paint_fan_overrun")
    fan_overrun_mask = fault_masks.get(fan_overrun_key, {}).get("mask")
    paint_df = pb.simulate_paint_booth(minute_df, paint_cfg, rng, fan_overrun_window_mask=fan_overrun_mask)
    results["PAINT-BOOTH-01"] = paint_df

    # --- Hadapsar compressed-air header: CMP-CENT-01 (lead), CMP-SCR-01 (lag) ---
    cent_cfg = _asset_cfg(config, "CMP-CENT-01")
    scr_cfg = _asset_cfg(config, "CMP-SCR-01")
    base_demand = config["compressor"]["base_air_demand_m3min"]
    had_prod_demand = _broadcast_air_demand(minute_df, had_air_demand, hadapsar_families)
    header_demand = base_demand + had_prod_demand + paint_df["air_draw_m3min"].to_numpy()

    lower0 = policy["compressor_pressure_lower_bar"]
    upper0 = policy["compressor_pressure_upper_bar"]
    drift_key = ("CMP-CENT-01", "setpoint_drift")
    drift_mask = fault_masks.get(drift_key, {}).get("mask")
    drift_mag = fault_masks.get(drift_key, {}).get("magnitude", 0.0)
    lower_arr, upper_arr = cmp._setpoint_series(n, lower0, upper0, drift_mask, drift_mag or 0.0)

    start_date = minute_df["ts"].iloc[0]
    growth_per_day = config["compressor"]["leak_growth_fraction_per_day"]
    start_frac = config["compressor"]["leak_start_fraction_of_rated_flow"]
    had_system_leak = cmp.system_leak_flow_m3min(minute_df["ts"], start_date, cent_cfg["rated_m3_per_min"], growth_per_day, start_frac)

    leak_key_scr = ("CMP-SCR-01", "leak_growth")
    scr_leak_mask = fault_masks.get(leak_key_scr, {}).get("mask")
    scr_leak_mag = fault_masks.get(leak_key_scr, {}).get("magnitude", 1.0)
    scr_fault_leak = cmp.fault_leak_extra_flow_m3min(n, scr_cfg["rated_m3_per_min"], scr_leak_mask, scr_leak_mag or 1.0)

    # feed both leak components into the demand the header's pressure loop must satisfy,
    # so a growing leak forces more lead/lag cycling (most visible at night when
    # production demand is near zero)
    header_demand_with_leak = header_demand + had_system_leak + scr_fault_leak

    pressure, loaded, cycles = cmp.simulate_header(minute_df, [cent_cfg, scr_cfg], header_demand_with_leak, lower_arr, upper_arr)

    penalty_rate = config["compressor"]["overpressure_power_penalty_per_bar"]
    results["CMP-CENT-01"] = cmp.compute_asset_output(cent_cfg, pressure, loaded["CMP-CENT-01"], cycles["CMP-CENT-01"], had_system_leak, penalty_rate, auto_stop=True)
    results["CMP-CENT-01"]["sequencing_state"] = "lead"
    results["CMP-SCR-01"] = cmp.compute_asset_output(scr_cfg, pressure, loaded["CMP-SCR-01"], cycles["CMP-SCR-01"], scr_fault_leak, penalty_rate, off_standby_kw=1.0)
    results["CMP-SCR-01"]["sequencing_state"] = "lag"

    # --- Nashik header: CMP-REC-01 alone ---
    rec_cfg = _asset_cfg(config, "CMP-REC-01")
    nas_base_demand = config["compressor"]["base_air_demand_m3min"] * 0.4
    nas_prod_demand = _broadcast_air_demand(minute_df, nas_air_demand, nashik_families)
    nas_system_leak = cmp.system_leak_flow_m3min(minute_df["ts"], start_date, rec_cfg["rated_m3_per_min"], growth_per_day, start_frac)
    nas_demand = nas_base_demand + nas_prod_demand + nas_system_leak
    nas_lower = np.full(n, lower0)
    nas_upper = np.full(n, upper0)
    nas_pressure, nas_loaded, nas_cycles = cmp.simulate_header(minute_df, [rec_cfg], nas_demand, nas_lower, nas_upper)
    results["CMP-REC-01"] = cmp.compute_asset_output(rec_cfg, nas_pressure, nas_loaded["CMP-REC-01"], nas_cycles["CMP-REC-01"], nas_system_leak, penalty_rate, auto_stop=True)
    results["CMP-REC-01"]["sequencing_state"] = "lead"

    # --- Test rig (independent schedule, policy-controlled start time) ---
    rig_cfg = _asset_cfg(config, "TEST-RIG-CNG-01")
    rig_start = policy["test_rig_start_time"]
    results["TEST-RIG-CNG-01"] = cmp.build_test_rig(minute_df, rig_cfg, rig_start, run_minutes=90, rng=rng)
    results["TEST-RIG-CNG-01"]["sequencing_state"] = "standalone"

    # --- Chillers ---
    vam_cfg = _asset_cfg(config, "CHILLER-VAM-01")
    scr_chiller_cfg = _asset_cfg(config, "CHILLER-SCR-01")
    total_rated_tr = vam_cfg["rated_tr"] + scr_chiller_cfg["rated_tr"]
    total_tr_demand = chl.cooling_demand_tr(minute_df, total_rated_tr, minute_df["wet_bulb_c"].to_numpy())

    if policy["chiller_sequencing"] == "VAM_lead":
        lead_tr, lag_tr = chl.allocate_sequenced(total_tr_demand, vam_cfg["rated_tr"], scr_chiller_cfg["rated_tr"])
        vam_tr, scr_tr = lead_tr, lag_tr
    else:
        lead_tr, lag_tr = chl.allocate_sequenced(total_tr_demand, scr_chiller_cfg["rated_tr"], vam_cfg["rated_tr"])
        scr_tr, vam_tr = lead_tr, lag_tr

    fouling_key = ("CHILLER-SCR-01", "condenser_fouling")
    fouling_mask = fault_masks.get(fouling_key, {}).get("mask")
    fouling_mag = fault_masks.get(fouling_key, {}).get("magnitude", 1.0)
    leak_key = ("CHILLER-SCR-01", "refrigerant_leak")
    reflk_mask = fault_masks.get(leak_key, {}).get("mask")
    reflk_mag = fault_masks.get(leak_key, {}).get("magnitude", 0.0)

    results["CHILLER-SCR-01"] = chl.simulate_screw_chiller(
        minute_df, scr_chiller_cfg, scr_tr, minute_df["wet_bulb_c"].to_numpy(), rng,
        fouling_window_mask=fouling_mask, fouling_magnitude=fouling_mag or 1.0,
        refrigerant_leak_window_mask=reflk_mask, refrigerant_leak_magnitude=reflk_mag or 0.0,
    )
    results["CHILLER-VAM-01"] = chl.simulate_vam_chiller(minute_df, vam_cfg, vam_tr, rng, fuel_type=vam_cfg["fuel_type"])

    # --- Furnace ---
    furnace_cfg = _asset_cfg(config, "FURNACE-HT-01")
    door_key = ("FURNACE-HT-01", "furnace_door_open")
    door_mask = fault_masks.get(door_key, {}).get("mask")
    door_mag = fault_masks.get(door_key, {}).get("magnitude", 0.0)
    results["FURNACE-HT-01"] = fur.simulate_furnace(
        minute_df, furnace_cfg, policy["furnace_start_time"], rng,
        door_open_window_mask=door_mask, door_open_magnitude=door_mag or 0.0,
    )

    # --- CNC ---
    cnc_cfg = _asset_cfg(config, "CNC-GEAR-01")
    idle_key = ("CNC-GEAR-01", "cnc_idle_drift")
    idle_mask = fault_masks.get(idle_key, {}).get("mask")
    results["CNC-GEAR-01"] = cnc_mod.simulate_cnc(
        minute_df, cnc_cfg, daily_prod, rng,
        idle_shutdown_policy=policy["cnc_idle_shutdown"], idle_drift_window_mask=idle_mask,
    )

    # --- Total non-solar plant kW (for solar self-consumption + main meter) ---
    non_solar_kw = np.zeros(n)
    for aid, df in results.items():
        if "kW" in df.columns:
            non_solar_kw += df["kW"].to_numpy()
        elif "kW_electrical" in df.columns:
            non_solar_kw += df["kW_electrical"].to_numpy()

    # --- Solar ---
    solar_cfg = _asset_cfg(config, "SOLAR-SASWAD-01")
    results["SOLAR-SASWAD-01"] = sol.simulate_solar(
        minute_df, solar_cfg, minute_df["irradiance_kw_m2"].to_numpy(), minute_df["ambient_temp_c"].to_numpy(),
        non_solar_kw, rng,
    )

    # --- Main meter ---
    solar_self_consumed = results["SOLAR-SASWAD-01"]["kW_self_consumed"].to_numpy()
    results["MAIN-METER"] = mm.simulate_main_meter(non_solar_kw, solar_self_consumed, config, rng)

    fault_label_rows = flt.build_fault_label_rows(config)

    return {
        "minute_df": minute_df,
        "daily_production": daily_prod,
        "assets": results,
        "fault_labels": fault_label_rows,
        "policy_name": policy_name,
    }
