"""Stage 2: PAINT-BOOTH-01 — constant fan kW while running, compressed-air draw that
must also load the compressor header, plus batch curing oven.
"""
import numpy as np
import pandas as pd

OVEN_BATCH_MIN = 90


def simulate_paint_booth(minute_df, asset_cfg, rng, fan_overrun_window_mask=None, overrun_minutes=60):
    n = len(minute_df)
    is_prod = (minute_df["shift"] != "OFF").to_numpy()
    fan_kw = asset_cfg["fan_kw"]
    oven_kw = asset_cfg["oven_kw"]
    air_draw = asset_cfg["air_draw_m3min"]

    running = is_prod.copy()

    if fan_overrun_window_mask is not None and fan_overrun_window_mask.any():
        shift_end_minute = (minute_df["ts"].dt.hour * 60 + minute_df["ts"].dt.minute).to_numpy()
        was_prod = np.r_[is_prod[1:], False]
        shift_just_ended = is_prod & ~was_prod
        overrun_idx = np.flatnonzero(shift_just_ended)
        for idx in overrun_idx:
            if idx < n and fan_overrun_window_mask[idx]:
                end = min(idx + 1 + overrun_minutes, n)
                running[idx + 1:end] = True

    fan_state = running.astype(float)
    kw = fan_state * fan_kw
    air_draw_m3min = fan_state * air_draw

    n_batches_per_day = asset_cfg.get("batches_per_day_mean", 3)
    dates = minute_df["date"].to_numpy()
    unique_dates = pd.unique(dates)
    oven_on = np.zeros(n, dtype=bool)
    day_start_idx = np.flatnonzero(minute_df["ts"].dt.hour.to_numpy() == 0)
    for i, d in enumerate(unique_dates):
        day_mask = dates == d
        day_prod_idx = np.flatnonzero(day_mask & is_prod)
        if len(day_prod_idx) == 0:
            continue
        n_batches = max(1, int(round(rng.normal(n_batches_per_day, 0.6))))
        starts = rng.choice(day_prod_idx, size=min(n_batches, len(day_prod_idx)), replace=False)
        for s in sorted(starts):
            end = min(s + OVEN_BATCH_MIN, n)
            oven_on[s:end] = True

    kw += np.where(oven_on, oven_kw, 0.0)

    return pd.DataFrame({
        "kW": kw,
        "air_draw_m3min": air_draw_m3min,
        "fan_running": fan_state.astype(bool),
        "oven_on": oven_on,
    })
