"""Stage 5: run the simulation for a scenario and write kpcl_energy[_optimized].db.

Usage: python build_db.py --scenario baseline|optimized
"""
import argparse
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import yaml

from generator import simulate as sim
from generator import faults as flt
from generator import fuel_events as fev
from generator import noise as noise_mod
from generator import emissions as em
from generator import main_meter as mm

SUM_COLS = {"units_produced"}
MINMAX_SUFFIXES = ("_c",)
MINMAX_SUBSTRINGS = ("pressure", "temp")


def aggregate_15min(ts, df):
    tmp = df.copy()
    for col in tmp.columns:
        if tmp[col].dtype == bool:
            tmp[col] = tmp[col].astype(int)
    tmp.index = pd.DatetimeIndex(ts.values, name="ts")

    numeric_cols = [c for c in tmp.columns if pd.api.types.is_numeric_dtype(tmp[c])]
    cat_cols = [c for c in tmp.columns if c not in numeric_cols]

    sum_cols_present = [c for c in numeric_cols if c in SUM_COLS]
    mean_cols = [c for c in numeric_cols if c not in sum_cols_present and c != "cycle_count"]

    agg = tmp[mean_cols].resample("15min").mean() if mean_cols else pd.DataFrame(index=tmp.resample("15min").size().index)

    for col in mean_cols:
        lc = col.lower()
        if lc.endswith(MINMAX_SUFFIXES) or any(s in lc for s in MINMAX_SUBSTRINGS):
            agg[f"{col}_min"] = tmp[col].resample("15min").min()
            agg[f"{col}_max"] = tmp[col].resample("15min").max()

    for col in sum_cols_present:
        agg[col] = tmp[col].resample("15min").sum()

    if "cycle_count" in tmp.columns:
        first = tmp["cycle_count"].resample("15min").first()
        last = tmp["cycle_count"].resample("15min").last()
        agg["cycle_count"] = (last - first).clip(lower=0)

    for col in cat_cols:
        agg[col] = tmp[col].resample("15min").agg(lambda s: s.mode().iloc[0] if len(s.mode()) else (s.iloc[0] if len(s) else None))

    agg = agg.reset_index()
    return agg


def to_sql_batched(conn, table_name, df, if_exists="append"):
    if len(df) == 0:
        return
    df.to_sql(table_name, conn, if_exists=if_exists, index=False, chunksize=5000)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dim_plant (
    plant_id TEXT PRIMARY KEY, name TEXT, city TEXT, division TEXT
);
CREATE TABLE IF NOT EXISTS dim_asset (
    asset_id TEXT PRIMARY KEY, type TEXT, plant_id TEXT,
    rated_kw REAL, rated_m3_per_min REAL, rated_tr REAL, rated_kwp REAL,
    extra_json TEXT
);
CREATE TABLE IF NOT EXISTS dim_tariff (
    period_name TEXT, start_hhmm TEXT, end_hhmm TEXT, rate_rs_per_kwh REAL,
    contract_demand_kva REAL, demand_charge_rs_per_kva REAL, source_note TEXT
);
CREATE TABLE IF NOT EXISTS dim_emission_factor (
    factor_name TEXT, value REAL, unit TEXT, source TEXT, version TEXT, year INTEGER
);
CREATE TABLE IF NOT EXISTS fact_meter (
    ts TEXT, asset_id TEXT, kW REAL, kWh REAL, state TEXT, dq_flag TEXT
);
CREATE TABLE IF NOT EXISTS fact_compressor (
    ts TEXT, asset_id TEXT, kW REAL, pressure_bar REAL, pressure_bar_min REAL, pressure_bar_max REAL,
    flow_m3min REAL, leak_flow_m3min REAL, specific_power_kwh_m3 REAL, load_fraction REAL,
    cycle_count INTEGER, sequencing_state TEXT
);
CREATE TABLE IF NOT EXISTS fact_chiller (
    ts TEXT, asset_id TEXT, TR REAL, kW REAL, kw_per_tr REAL, COP REAL,
    chw_supply_c REAL, chw_return_c REAL, condenser_approach_c REAL, refrigerant_charge_kg REAL,
    kW_electrical REAL, kWh_thermal REAL, thermal_cop REAL, fuel_kg REAL, fuel_type TEXT
);
CREATE TABLE IF NOT EXISTS fact_furnace (
    ts TEXT, batch_id INTEGER, batch_mass_kg REAL, setpoint_temp_c REAL, state TEXT,
    kW REAL, fuel_kg REAL
);
CREATE TABLE IF NOT EXISTS fact_paint_booth (
    ts TEXT, kW REAL, air_draw_m3min REAL, fan_running REAL, oven_on REAL
);
CREATE TABLE IF NOT EXISTS fact_solar (
    ts TEXT, kW_generated REAL, kW_self_consumed REAL, kW_exported REAL
);
CREATE TABLE IF NOT EXISTS fact_weather (
    ts TEXT, ambient_temp_c REAL, ambient_temp_c_min REAL, ambient_temp_c_max REAL,
    humidity_pct REAL, wet_bulb_c REAL, wet_bulb_c_min REAL, wet_bulb_c_max REAL,
    irradiance_kw_m2 REAL
);
CREATE TABLE IF NOT EXISTS fact_production (
    date TEXT, shift TEXT, family TEXT, plant_id TEXT, units REAL, is_surge INTEGER
);
CREATE TABLE IF NOT EXISTS fact_fuel_event (
    asset_id TEXT, ts TEXT, fuel_type TEXT, amount_kg REAL, note TEXT
);
CREATE TABLE IF NOT EXISTS fact_fault_label (
    asset_id TEXT, fault_type TEXT, start_ts TEXT, end_ts TEXT, magnitude REAL, label_class TEXT
);
CREATE TABLE IF NOT EXISTS fact_emissions (
    ts TEXT, scope1_tco2 REAL, scope2_tco2 REAL, solar_avoided_tco2 REAL
);
CREATE TABLE IF NOT EXISTS fact_main_meter (
    ts TEXT, kW REAL, kVA REAL, pf REAL, peak_flag INTEGER, cost_rs REAL
);
CREATE TABLE IF NOT EXISTS rollup_hourly_asset (
    ts_hour TEXT, asset_id TEXT, kWh REAL, max_kW REAL
);
CREATE TABLE IF NOT EXISTS rollup_daily_asset (
    date TEXT, asset_id TEXT, kWh REAL, max_kW REAL
);
CREATE TABLE IF NOT EXISTS rollup_daily_plant (
    date TEXT, plant_id TEXT, kWh REAL, scope1_tco2 REAL, scope2_tco2 REAL, cost_rs REAL
);
CREATE INDEX IF NOT EXISTS idx_fact_meter_asset_ts ON fact_meter(asset_id, ts);
CREATE INDEX IF NOT EXISTS idx_fact_compressor_asset_ts ON fact_compressor(asset_id, ts);
CREATE INDEX IF NOT EXISTS idx_fact_chiller_asset_ts ON fact_chiller(asset_id, ts);
CREATE INDEX IF NOT EXISTS idx_fact_main_meter_ts ON fact_main_meter(ts);
CREATE INDEX IF NOT EXISTS idx_fact_emissions_ts ON fact_emissions(ts);
CREATE INDEX IF NOT EXISTS idx_rollup_daily_asset ON rollup_daily_asset(asset_id, date);
"""

COMPRESSOR_IDS = {"CMP-CENT-01", "CMP-SCR-01", "CMP-REC-01", "TEST-RIG-CNG-01"}
CHILLER_IDS = {"CHILLER-SCR-01", "CHILLER-VAM-01"}


def build(config, scenario):
    out = sim.simulate(config, scenario)
    minute_df = out["minute_df"]
    ts = minute_df["ts"]
    assets_1m = out["assets"]
    daily_prod = out["daily_production"]
    fault_masks = flt.build_fault_masks(minute_df, config)

    assets_15m = {aid: aggregate_15min(ts, df) for aid, df in assets_1m.items()}
    # COP must satisfy TR*3.517/kW exactly at the stored resolution; averaging the
    # per-minute ratio directly breaks that identity (Jensen's inequality), so
    # recompute it from the aggregated TR/kW instead of carrying the mean-of-ratios.
    scr15 = assets_15m["CHILLER-SCR-01"]
    scr15["COP"] = np.where(scr15["kW"] > 1e-9, scr15["TR"] * 3.517 / scr15["kW"], np.nan)
    weather_15m = aggregate_15min(ts, minute_df[["ambient_temp_c", "humidity_pct", "wet_bulb_c", "irradiance_kw_m2"]])

    outage_arr = flt.outage_mask(minute_df, config)
    main_kw_1m = assets_1m["MAIN-METER"]["kW"].to_numpy()
    fuel_events = fev.build_fuel_events(minute_df, assets_1m, config, fault_masks, main_meter_kw=main_kw_1m, outage_mask_arr=outage_arr)

    cost_rs, peak_flag = mm.compute_cost_and_peak(assets_15m["MAIN-METER"].rename(columns={"ts": "ts"}), config)
    main_meter_15m = assets_15m["MAIN-METER"].copy()
    main_meter_15m["cost_rs"] = cost_rs
    main_meter_15m["peak_flag"] = peak_flag.astype(int)

    furnace_fuel_15 = assets_15m["FURNACE-HT-01"]["fuel_kg"] * 60.0 * 15.0 / 60.0  # kg/min mean * 15 -> per interval total handled below
    # per-interval totals (mean kg/min * 15 minutes)
    lpg_kg_15 = assets_15m["FURNACE-HT-01"]["fuel_kg"] * 15.0
    gas_kg_15 = assets_15m["CHILLER-VAM-01"]["fuel_kg"] * 15.0

    diesel_litre_15 = np.zeros(len(main_meter_15m))
    if outage_arr.any():
        outage_15 = aggregate_15min(ts, pd.DataFrame({"outage_frac": outage_arr.astype(float)}))["outage_frac"].to_numpy()
        sfc = config["dg_fuel_litre_per_kwh"]
        outage_kwh_15 = main_meter_15m["kW"].to_numpy() * outage_15 * 0.25
        diesel_litre_15 = outage_kwh_15 * sfc
        grid_kwh_15 = main_meter_15m["kW"].to_numpy() * (1 - outage_15) * 0.25
    else:
        grid_kwh_15 = main_meter_15m["kW"].to_numpy() * 0.25

    refrigerant_leak_kg_15 = np.zeros(len(main_meter_15m))
    leak_key = ("CHILLER-SCR-01", "refrigerant_leak")
    if leak_key in fault_masks:
        mag = fault_masks[leak_key]["magnitude"]
        mask15 = aggregate_15min(ts, pd.DataFrame({"m": fault_masks[leak_key]["mask"].astype(float)}))["m"].to_numpy()
        last_idx = np.flatnonzero(mask15 > 0)
        if len(last_idx):
            refrigerant_leak_kg_15[last_idx[-1]] = 25.0 * mag / 0.35

    solar_kwh_15 = assets_15m["SOLAR-SASWAD-01"]["kW_self_consumed"].to_numpy() * 0.25 + assets_15m["SOLAR-SASWAD-01"]["kW_exported"].to_numpy() * 0.25

    emissions_15 = em.compute_emissions_15m(grid_kwh_15, lpg_kg_15.to_numpy(), gas_kg_15.to_numpy(), diesel_litre_15, refrigerant_leak_kg_15, solar_kwh_15, config)
    emissions_15.insert(0, "ts", main_meter_15m["ts"])

    # dq noise/missing pattern keyed only off the two shipped scenario names, so
    # ad-hoc counterfactuals (ml/recommendations.py) get the SAME pattern as
    # baseline — otherwise a differing random dropout would contaminate the
    # kWh/Rs/tCO2 diff that's supposed to isolate just the policy/fault change.
    rng_dq = np.random.default_rng(config["seed"] + (1 if scenario == "optimized" else 0))
    fact_meter_rows = []
    for aid, df15 in assets_15m.items():
        if aid == "MAIN-METER":
            continue
        if "kW" in df15.columns:
            kw_col = df15["kW"].to_numpy()
        elif "kW_electrical" in df15.columns:
            kw_col = df15["kW_electrical"].to_numpy()
        elif "kW_generated" in df15.columns:
            kw_col = df15["kW_generated"].to_numpy()
        else:
            continue
        tmp = pd.DataFrame({"kW": kw_col})
        drift_asset = config["data_quality"]["meter_drift_asset"]
        tmp = noise_mod.apply_dq_effects(tmp, ["kW"], rng_dq, config, aid, drift_asset_id=drift_asset)
        state_col = df15["state"] if "state" in df15.columns else None
        fact_meter_rows.append(pd.DataFrame({
            "ts": df15["ts"],
            "asset_id": aid,
            "kW": tmp["kW"],
            "kWh": tmp["kW"] * 0.25,
            "state": state_col if state_col is not None else None,
            "dq_flag": tmp["dq_flag"],
        }))
    fact_meter = pd.concat(fact_meter_rows, ignore_index=True)

    return {
        "minute_df": minute_df,
        "assets_15m": assets_15m,
        "weather_15m": weather_15m,
        "daily_production": daily_prod,
        "fuel_events": fuel_events,
        "fault_labels": out["fault_labels"],
        "main_meter_15m": main_meter_15m,
        "emissions_15": emissions_15,
        "fact_meter": fact_meter,
    }


def write_db(db_path, config, built):
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)

    plants_df = pd.DataFrame(config["plants"])
    to_sql_batched(conn, "dim_plant", plants_df.rename(columns={}))

    asset_rows = []
    for a in config["assets"]:
        extra = {k: v for k, v in a.items() if k not in
                 {"asset_id", "type", "plant_id", "rated_kw", "rated_m3_per_min", "rated_tr", "rated_kwp"}}
        asset_rows.append({
            "asset_id": a["asset_id"], "type": a["type"], "plant_id": a["plant_id"],
            "rated_kw": a.get("rated_kw"), "rated_m3_per_min": a.get("rated_m3_per_min"),
            "rated_tr": a.get("rated_tr"), "rated_kwp": a.get("rated_kwp"),
            "extra_json": json.dumps(extra),
        })
    to_sql_batched(conn, "dim_asset", pd.DataFrame(asset_rows))

    tariff_rows = []
    for p in config["tariff"]["tod_periods"]:
        tariff_rows.append({
            "period_name": p["name"], "start_hhmm": p["hours"][0], "end_hhmm": p["hours"][1],
            "rate_rs_per_kwh": p["rate_rs_per_kwh"],
            "contract_demand_kva": config["tariff"]["contract_demand_kva"],
            "demand_charge_rs_per_kva": config["tariff"]["demand_charge_rs_per_kva"],
            "source_note": config["tariff"]["source_note"],
        })
    to_sql_batched(conn, "dim_tariff", pd.DataFrame(tariff_rows))

    ef = config["emission_factors"]
    ef_rows = [
        {"factor_name": "grid", "value": ef["grid_tco2_per_mwh"]["value"], "unit": "tCO2/MWh",
         "source": ef["grid_tco2_per_mwh"]["source"], "version": ef["grid_tco2_per_mwh"]["version"], "year": ef["grid_tco2_per_mwh"]["year"]},
        {"factor_name": "diesel", "value": ef["diesel_kgco2_per_litre"]["value"], "unit": "kgCO2/litre",
         "source": ef["diesel_kgco2_per_litre"]["source"], "version": ef["diesel_kgco2_per_litre"]["version"], "year": ef["diesel_kgco2_per_litre"]["year"]},
        {"factor_name": "lpg", "value": ef["lpg_kgco2_per_kg"]["value"], "unit": "kgCO2/kg",
         "source": ef["lpg_kgco2_per_kg"]["source"], "version": ef["lpg_kgco2_per_kg"]["version"], "year": ef["lpg_kgco2_per_kg"]["year"]},
        {"factor_name": "natural_gas", "value": ef["natural_gas_kgco2_per_kg"]["value"], "unit": "kgCO2/kg",
         "source": ef["natural_gas_kgco2_per_kg"]["source"], "version": ef["natural_gas_kgco2_per_kg"]["version"], "year": ef["natural_gas_kgco2_per_kg"]["year"]},
        {"factor_name": "refrigerant_r410a_gwp", "value": ef["refrigerant_gwp"]["r410a"]["value"], "unit": "GWP100",
         "source": ef["refrigerant_gwp"]["r410a"]["source"], "version": "AR5", "year": None},
    ]
    to_sql_batched(conn, "dim_emission_factor", pd.DataFrame(ef_rows))

    to_sql_batched(conn, "fact_weather", built["weather_15m"].rename(columns={}))
    to_sql_batched(conn, "fact_production", built["daily_production"].rename(columns={"is_surge": "is_surge"}).assign(
        date=lambda d: d["date"].astype(str), is_surge=lambda d: d["is_surge"].astype(int)))
    to_sql_batched(conn, "fact_fuel_event", built["fuel_events"])
    to_sql_batched(conn, "fact_fault_label", built["fault_labels"])
    to_sql_batched(conn, "fact_main_meter", built["main_meter_15m"][["ts", "kW", "kVA", "pf", "peak_flag", "cost_rs"]])
    to_sql_batched(conn, "fact_emissions", built["emissions_15"])
    to_sql_batched(conn, "fact_meter", built["fact_meter"])

    for aid, df15 in built["assets_15m"].items():
        if aid in COMPRESSOR_IDS:
            cols = ["ts", "kW", "pressure_bar", "pressure_bar_min", "pressure_bar_max", "flow_m3min",
                    "leak_flow_m3min", "specific_power_kwh_m3", "load_fraction", "cycle_count", "sequencing_state"]
            sub = df15.reindex(columns=cols)
            sub.insert(1, "asset_id", aid)
            to_sql_batched(conn, "fact_compressor", sub)
        elif aid in CHILLER_IDS:
            cols = ["ts", "TR", "kW", "kw_per_tr", "COP", "chw_supply_c", "chw_return_c",
                    "condenser_approach_c", "refrigerant_charge_kg", "kW_electrical", "kWh_thermal",
                    "thermal_cop", "fuel_kg", "fuel_type"]
            sub = df15.reindex(columns=cols)
            sub.insert(1, "asset_id", aid)
            to_sql_batched(conn, "fact_chiller", sub)
        elif aid == "FURNACE-HT-01":
            to_sql_batched(conn, "fact_furnace", df15[["ts", "batch_id", "batch_mass_kg", "setpoint_temp_c", "state", "kW", "fuel_kg"]])
        elif aid == "PAINT-BOOTH-01":
            to_sql_batched(conn, "fact_paint_booth", df15[["ts", "kW", "air_draw_m3min", "fan_running", "oven_on"]])
        elif aid == "SOLAR-SASWAD-01":
            to_sql_batched(conn, "fact_solar", df15[["ts", "kW_generated", "kW_self_consumed", "kW_exported"]])

    build_rollups(conn, built, config)

    conn.commit()
    conn.close()


def build_rollups(conn, built, config):
    fact_meter = built["fact_meter"].copy()
    fact_meter["ts"] = pd.to_datetime(fact_meter["ts"])
    fact_meter["ts_hour"] = fact_meter["ts"].dt.floor("h")
    fact_meter["date"] = fact_meter["ts"].dt.date.astype(str)

    hourly = fact_meter.groupby(["ts_hour", "asset_id"]).agg(kWh=("kWh", "sum"), max_kW=("kW", "max")).reset_index()
    hourly["ts_hour"] = hourly["ts_hour"].astype(str)
    to_sql_batched(conn, "rollup_hourly_asset", hourly)

    daily_asset = fact_meter.groupby(["date", "asset_id"]).agg(kWh=("kWh", "sum"), max_kW=("kW", "max")).reset_index()
    to_sql_batched(conn, "rollup_daily_asset", daily_asset)

    asset_plant = {a["asset_id"]: a["plant_id"] for a in config["assets"]}
    fact_meter["plant_id"] = fact_meter["asset_id"].map(asset_plant)

    emissions = built["emissions_15"].copy()
    emissions["date"] = pd.to_datetime(emissions["ts"]).dt.date.astype(str)
    daily_emissions = emissions.groupby("date").agg(scope1_tco2=("scope1_tco2", "sum"), scope2_tco2=("scope2_tco2", "sum")).reset_index()

    main_meter = built["main_meter_15m"].copy()
    main_meter["date"] = pd.to_datetime(main_meter["ts"]).dt.date.astype(str)
    daily_cost = main_meter.groupby("date").agg(cost_rs=("cost_rs", "sum")).reset_index()

    daily_plant = fact_meter.dropna(subset=["plant_id"]).groupby(["date", "plant_id"]).agg(kWh=("kWh", "sum")).reset_index()
    daily_plant = daily_plant.merge(daily_emissions, on="date", how="left").merge(daily_cost, on="date", how="left")
    to_sql_batched(conn, "rollup_daily_plant", daily_plant)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["baseline", "optimized"], default="baseline")
    args = parser.parse_args()

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    db_name = "kpcl_energy.db" if args.scenario == "baseline" else "kpcl_energy_optimized.db"
    print(f"Simulating scenario='{args.scenario}' -> {db_name} ...")
    built = build(config, args.scenario)
    print("Writing SQLite database ...")
    write_db(db_name, config, built)
    print(f"Done: {db_name}")


if __name__ == "__main__":
    main()
