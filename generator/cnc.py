"""Stage 2: CNC-GEAR-01 — off / idle / cutting states, units produced -> kWh/unit."""
import numpy as np
import pandas as pd


def simulate_cnc(minute_df, asset_cfg, daily_production, rng,
                  idle_shutdown_policy=False, idle_drift_window_mask=None):
    n = len(minute_df)
    is_prod = (minute_df["shift"] != "OFF").to_numpy()
    rated_kw = asset_cfg["rated_kw"]
    base_idle_kw = asset_cfg["idle_kw"]

    idle_kw_series = np.full(n, base_idle_kw)
    if idle_drift_window_mask is not None and idle_drift_window_mask.any():
        idx = np.flatnonzero(idle_drift_window_mask)
        ramp = np.linspace(base_idle_kw, 8.0, len(idx))
        idle_kw_series[idx] = ramp

    gearbox = daily_production[daily_production["family"] == "gearbox"]
    gearbox_by_date = gearbox.groupby("date")["units"].sum().to_dict()

    units_this_minute = np.zeros(n)
    cutting = np.zeros(n, dtype=bool)
    dates = minute_df["date"].to_numpy()
    shift_arr = minute_df["shift"].to_numpy()

    for d, total_units in gearbox_by_date.items():
        if total_units <= 0:
            continue
        day_mask = (dates == d) & is_prod
        idx = np.flatnonzero(day_mask)
        if len(idx) == 0:
            continue
        cnc_minutes_per_unit = 35
        busy_minutes = min(len(idx), int(total_units * cnc_minutes_per_unit))
        busy_idx = rng.choice(idx, size=busy_minutes, replace=False) if busy_minutes > 0 else []
        cutting[busy_idx] = True
        if busy_minutes > 0:
            units_this_minute[busy_idx[::cnc_minutes_per_unit if cnc_minutes_per_unit else 1]] = 1

    state = np.where(cutting, "cutting", np.where(is_prod, "idle", "off"))
    if idle_shutdown_policy:
        shutdown_mask = (~is_prod) & (~cutting)
        kw = np.where(cutting, rated_kw * rng.uniform(0.7, 1.0, n), np.where(shutdown_mask, 0.3, idle_kw_series))
        state = np.where(shutdown_mask, "shutdown", state)
    else:
        kw = np.where(cutting, rated_kw * rng.uniform(0.7, 1.0, n), np.where(is_prod, idle_kw_series, idle_kw_series * 0.6))

    return pd.DataFrame({
        "kW": kw,
        "state": state,
        "units_produced": units_this_minute,
    })
