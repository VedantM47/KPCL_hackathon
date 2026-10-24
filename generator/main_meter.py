"""Stage 2: main meter — sum of asset meters + unmetered losses - solar self-consumed.
Derives kVA from kW and power factor, and peak demand vs contract demand.
"""
import numpy as np
import pandas as pd


def simulate_main_meter(total_asset_kw, solar_self_consumed_kw, config, rng):
    n = len(total_asset_kw)
    lo, hi = config["data_quality"]["unmetered_loss_fraction"]
    unmetered_frac = rng.uniform(lo, hi)
    unmetered_kw = total_asset_kw * unmetered_frac

    main_kw = total_asset_kw + unmetered_kw - solar_self_consumed_kw
    main_kw = np.maximum(main_kw, 0.0)

    pf_target = config["tariff"]["power_factor_target"]
    pf = pf_target - np.abs(rng.normal(0, 0.012, n))
    pf = np.clip(pf, 0.85, 0.99)
    kva = main_kw / pf

    return pd.DataFrame({
        "kW": main_kw,
        "kVA": kva,
        "pf": pf,
        "unmetered_kw": unmetered_kw,
    })


def compute_cost_and_peak(main_meter_15m, config):
    """Operates on a 15-minute resolution DataFrame with columns ts, kW, kVA."""
    tod_periods = config["tariff"]["tod_periods"]
    contract_kva = config["tariff"]["contract_demand_kva"]

    def rate_for_minute(hhmm):
        for period in tod_periods:
            start, end = period["hours"]
            if start <= end:
                if start <= hhmm < end:
                    return period["rate_rs_per_kwh"]
            else:  # wraps midnight
                if hhmm >= start or hhmm < end:
                    return period["rate_rs_per_kwh"]
        return tod_periods[0]["rate_rs_per_kwh"]

    hhmm = main_meter_15m["ts"].dt.strftime("%H:%M")
    rates = hhmm.map(rate_for_minute)
    energy_kwh = main_meter_15m["kW"] * 0.25
    cost_rs = energy_kwh * rates

    peak_flag = main_meter_15m["kVA"] > contract_kva
    return cost_rs, peak_flag
