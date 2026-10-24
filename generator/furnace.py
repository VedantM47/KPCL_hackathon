"""Stage 2: FURNACE-HT-01 — batch heat-treatment: ramp -> hold -> cool-down.
Fuel per batch proportional to load mass x temperature lift / efficiency, plus
standby loss. Electric-assist kW tracks fans/controls, not the primary heat source.
"""
import numpy as np
import pandas as pd

STEEL_SPECIFIC_HEAT_KJ_PER_KGK = 0.49   # assumed, typical alloy steel
LPG_HEATING_VALUE_KWH_PER_KG = 12.8     # assumed LPG LHV equivalent — VERIFY
AMBIENT_REF_C = 25.0

RAMP_MIN = 75
HOLD_MIN = 180
COOLDOWN_MIN = 90
BATCH_TOTAL_MIN = RAMP_MIN + HOLD_MIN + COOLDOWN_MIN


def simulate_furnace(minute_df, asset_cfg, start_time_str, rng,
                      door_open_window_mask=None, door_open_magnitude=0.0):
    n = len(minute_df)
    h, m = start_time_str.split(":")
    start_min = int(h) * 60 + int(m)
    minute_of_day = (minute_df["ts"].dt.hour * 60 + minute_df["ts"].dt.minute).to_numpy()
    is_prod_day = (minute_df["shift"] == "A").to_numpy()   # one batch/day, started on A shift

    setpoint = asset_cfg["setpoint_temp_c"]
    efficiency = asset_cfg["efficiency"]
    standby_kw = asset_cfg["standby_loss_kw"]
    rated_kw = asset_cfg["rated_kw"]

    state = np.array(["off"] * n, dtype=object)
    kw = np.full(n, standby_kw * 0.3)
    fuel_kg = np.zeros(n)
    batch_mass = np.zeros(n)
    batch_id = np.zeros(n, dtype=np.int32)
    setpoint_arr = np.zeros(n)

    rel = minute_of_day - start_min
    in_batch = (rel >= 0) & (rel < BATCH_TOTAL_MIN) & is_prod_day
    bid = 0
    for day_start_idx in np.flatnonzero(is_prod_day & (rel == 0)):
        bid += 1
        mass = max(50.0, rng.normal(asset_cfg["batch_mass_kg_mean"], asset_cfg["batch_mass_kg_std"]))
        delta_t = setpoint - AMBIENT_REF_C
        total_fuel_kwh = mass * STEEL_SPECIFIC_HEAT_KJ_PER_KGK * delta_t / efficiency / 3600.0

        door_mult = 1.0
        if door_open_window_mask is not None:
            if door_open_window_mask[day_start_idx:day_start_idx + BATCH_TOTAL_MIN].any():
                door_mult = 1.0 + door_open_magnitude

        ramp_slice = slice(day_start_idx, min(day_start_idx + RAMP_MIN, n))
        hold_slice = slice(min(day_start_idx + RAMP_MIN, n), min(day_start_idx + RAMP_MIN + HOLD_MIN, n))
        cool_slice = slice(min(day_start_idx + RAMP_MIN + HOLD_MIN, n), min(day_start_idx + BATCH_TOTAL_MIN, n))

        state[ramp_slice] = "ramp"
        state[hold_slice] = "hold"
        state[cool_slice] = "cooldown"
        batch_mass[day_start_idx:min(day_start_idx + BATCH_TOTAL_MIN, n)] = mass
        batch_id[day_start_idx:min(day_start_idx + BATCH_TOTAL_MIN, n)] = bid
        setpoint_arr[day_start_idx:min(day_start_idx + BATCH_TOTAL_MIN, n)] = setpoint

        ramp_fuel_total = total_fuel_kwh * 0.60 * door_mult
        hold_fuel_total = total_fuel_kwh * 0.40 * door_mult

        ramp_len = ramp_slice.stop - ramp_slice.start
        if ramp_len > 0:
            fuel_kg[ramp_slice] = (ramp_fuel_total / LPG_HEATING_VALUE_KWH_PER_KG) / ramp_len
            kw[ramp_slice] = rated_kw * 0.6

        hold_len = hold_slice.stop - hold_slice.start
        if hold_len > 0:
            # thermostat cycling: on ~45% duty within hold
            duty = (np.arange(hold_len) % 12) < 5
            per_on_minute_fuel = (hold_fuel_total / LPG_HEATING_VALUE_KWH_PER_KG) / max(1, duty.sum())
            fuel_kg[hold_slice] = np.where(duty, per_on_minute_fuel, 0.0)
            kw[hold_slice] = np.where(duty, rated_kw * 0.35, standby_kw * 0.5)

        cool_len = cool_slice.stop - cool_slice.start
        if cool_len > 0:
            kw[cool_slice] = standby_kw * 0.3
            fuel_kg[cool_slice] = 0.0

    return pd.DataFrame({
        "batch_id": batch_id,
        "batch_mass_kg": batch_mass,
        "setpoint_temp_c": setpoint_arr,
        "state": state,
        "kW": kw,
        "fuel_kg": fuel_kg,
    })
