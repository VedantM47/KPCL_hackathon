"""Stage 2: measurement realism — noise, missing intervals, frozen-sensor stretches,
meter drift on one asset, dq_flag column.
"""
import numpy as np
import pandas as pd


def add_measurement_noise(kw_series, rng, config, is_transition=None):
    n = len(kw_series)
    base_pct = config["data_quality"]["noise_base_pct"]
    low_load_mult = config["data_quality"]["noise_low_load_multiplier"]

    max_kw = max(kw_series.max(), 1e-6)
    load_frac = kw_series / max_kw
    noise_scale = base_pct * np.where(load_frac < 0.15, low_load_mult, 1.0)
    if is_transition is not None:
        noise_scale = noise_scale * np.where(is_transition, 1.8, 1.0)

    noise = rng.normal(0, 1, n) * noise_scale * np.maximum(kw_series, 1.0)
    return np.maximum(kw_series + noise, 0.0)


def apply_dq_effects(df, value_cols, rng, config, asset_id, drift_asset_id=None):
    """Return df with dq_flag column, missing intervals set to NaN, frozen stretches,
    and meter drift applied to one designated asset."""
    n = len(df)
    dq_flag = np.array(["ok"] * n, dtype=object)

    lo, hi = config["data_quality"]["missing_fraction"]
    missing_frac = rng.uniform(lo, hi)
    missing_idx = rng.choice(n, size=int(n * missing_frac), replace=False)
    for col in value_cols:
        df.loc[missing_idx, col] = np.nan
    dq_flag[missing_idx] = "missing"

    n_stretches = config["data_quality"]["frozen_sensor_stretch_count"]
    lo_m, hi_m = config["data_quality"]["frozen_sensor_stretch_minutes"]
    for _ in range(max(0, n_stretches // 10)):  # distribute stretches sparsely per asset call
        if n < hi_m:
            break
        start = rng.integers(0, n - hi_m)
        length = rng.integers(lo_m, hi_m)
        frozen_value = df[value_cols[0]].iloc[start]
        for col in value_cols:
            df.loc[start:start + length, col] = frozen_value
        dq_flag[start:start + length] = "frozen"

    if drift_asset_id is not None and asset_id == drift_asset_id:
        drift_frac_per_month = config["data_quality"]["meter_drift_fraction_per_month"]
        months_elapsed = np.arange(n) / (60.0 * 24.0 * 30.0)
        drift_mult = 1.0 + drift_frac_per_month * months_elapsed
        for col in value_cols:
            df[col] = df[col] * drift_mult
        dq_flag = np.where(dq_flag == "ok", "drift", dq_flag)

    df["dq_flag"] = dq_flag
    return df
