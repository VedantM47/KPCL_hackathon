"""Stage 2: chiller physics — CHILLER-SCR-01 (electric screw) and CHILLER-VAM-01
(vapour absorption, heat-driven). Exact relations per spec:
  TR = 0.3307 * flow_m3h * deltaT_C
  kW = TR * kW_per_TR ; kW_per_TR = 0.85 + fouling(t) + wet-bulb term
  COP = TR * 3.517 / kW
"""
import numpy as np
import pandas as pd

CHW_DELTA_T_C = 5.5           # assumed chilled-water supply/return delta
KWTH_PER_TR = 3.517            # standard TR -> kW thermal conversion
GAS_HEATING_VALUE_KWH_PER_KG = 13.1   # assumed natural-gas LHV equivalent — VERIFY


def cooling_demand_tr(minute_df, rated_tr_total, wet_bulb_c, base_frac=0.25, peak_frac=0.85):
    """Process cooling-load schedule: higher during shifts, modulated by wet-bulb temp."""
    is_prod = (minute_df["shift"] != "OFF").to_numpy()
    wb_factor = np.clip((wet_bulb_c - 15.0) / 15.0, 0.0, 1.3)
    target_frac = np.where(is_prod, peak_frac, base_frac) * (0.7 + 0.3 * wb_factor)
    return np.clip(target_frac, 0.05, 1.05) * rated_tr_total


def allocate_sequenced(total_tr, lead_rated_tr, lag_rated_tr):
    lead_tr = np.minimum(total_tr, lead_rated_tr)
    remainder = np.maximum(total_tr - lead_rated_tr, 0.0)
    lag_tr = np.minimum(remainder, lag_rated_tr)
    return lead_tr, lag_tr


def simulate_screw_chiller(minute_df, asset_cfg, tr_demand, wet_bulb_c, rng,
                            fouling_window_mask=None, fouling_magnitude=1.0,
                            refrigerant_leak_window_mask=None, refrigerant_leak_magnitude=0.0):
    n = len(minute_df)
    kw_per_tr_base = asset_cfg.get("kw_per_tr_base", 0.85)

    days = np.arange(n) / (60.0 * 24.0)
    fouling = np.zeros(n)
    if fouling_window_mask is not None and fouling_window_mask.any():
        idx = np.flatnonzero(fouling_window_mask)
        ramp = np.linspace(0, 0.18 * fouling_magnitude, len(idx))   # up to +0.18 kW/TR at full fouling
        fouling[idx] = ramp

    wb_term = np.clip((wet_bulb_c - 20.0) * 0.004, -0.02, 0.05)
    kw_per_tr = kw_per_tr_base + fouling + wb_term

    cop_penalty = np.zeros(n)
    if refrigerant_leak_window_mask is not None and refrigerant_leak_window_mask.any():
        idx = np.flatnonzero(refrigerant_leak_window_mask)
        ramp = np.linspace(0, refrigerant_leak_magnitude, len(idx))
        cop_penalty[idx] = ramp
    kw_per_tr = kw_per_tr * (1.0 + cop_penalty)

    tr = np.maximum(tr_demand, 0.0)
    kw = tr * kw_per_tr
    cop = np.where(kw > 1e-6, tr * 3.517 / kw, np.nan)

    flow_m3h = tr / (0.3307 * CHW_DELTA_T_C)
    chw_supply_c = 7.0 + rng.normal(0, 0.15, n)
    chw_return_c = chw_supply_c + CHW_DELTA_T_C + rng.normal(0, 0.1, n)
    condenser_approach_c = 3.0 + fouling * 25.0 + rng.normal(0, 0.2, n)  # cleanest fouling indicator

    refrigerant_charge_kg = np.full(n, 150.0)  # assumed nominal charge
    if refrigerant_leak_window_mask is not None and refrigerant_leak_window_mask.any():
        idx = np.flatnonzero(refrigerant_leak_window_mask)
        drop = np.linspace(0, 25.0 * refrigerant_leak_magnitude / 0.35, len(idx))
        refrigerant_charge_kg[idx] -= drop

    return pd.DataFrame({
        "TR": tr,
        "kW": kw,
        "kw_per_tr": kw_per_tr,
        "COP": cop,
        "chw_supply_c": chw_supply_c,
        "chw_return_c": chw_return_c,
        "condenser_approach_c": condenser_approach_c,
        "refrigerant_charge_kg": refrigerant_charge_kg,
    })


def simulate_vam_chiller(minute_df, asset_cfg, tr_demand, rng, fuel_type="gas"):
    n = len(minute_df)
    thermal_cop = rng.uniform(0.7, 1.2, n)
    # smooth the random COP instead of i.i.d noise every minute
    thermal_cop = pd.Series(thermal_cop).rolling(180, min_periods=1, center=True).mean().to_numpy()

    tr = np.maximum(tr_demand, 0.0)
    kwth_cooling = tr * KWTH_PER_TR
    kwth_fuel_in = np.where(thermal_cop > 1e-6, kwth_cooling / thermal_cop, 0.0)

    pump_fan_kw = asset_cfg.get("aux_kw", 18.0) * np.where(tr > 0.5, 1.0, 0.35)  # assumed aux load

    if fuel_type == "gas":
        fuel_kg_per_min = kwth_fuel_in / GAS_HEATING_VALUE_KWH_PER_KG / 60.0
    else:  # steam — report as kWh_thermal consumed, no mass fuel
        fuel_kg_per_min = np.zeros(n)

    return pd.DataFrame({
        "TR": tr,
        "kW_electrical": pump_fan_kw,
        "kWh_thermal": kwth_fuel_in / 60.0,
        "thermal_cop": thermal_cop,
        "fuel_kg": fuel_kg_per_min,
        "fuel_type": fuel_type,
    })
