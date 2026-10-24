"""Stage 2: compressor room physics — lead/lag sequencing, pressure hysteresis,
load/unload cycling, leak growth, specific power. Simulated at 1-minute resolution
because load/unload cycling is faster than the 15-minute output resolution.
"""
import numpy as np
import pandas as pd

PRESSURE_GAIN_BAR_PER_M3MIN = 0.00028   # tuned so a header completes a load/unload
                                          # cycle every ~3-8 minutes at typical mismatch
FAULT_LEAK_GROWTH_PER_DAY = 0.0015      # assumed: fault-driven leak grows much faster
                                          # than slow background pipework leakage


def _setpoint_series(n, base_lower, base_upper, fault_window_mask, fault_magnitude_bar):
    """Linear drift of +magnitude bar across the fault window, reset at the end."""
    lower = np.full(n, base_lower, dtype=float)
    upper = np.full(n, base_upper, dtype=float)
    if fault_window_mask is not None and fault_window_mask.any():
        idx = np.flatnonzero(fault_window_mask)
        ramp = np.linspace(0, fault_magnitude_bar, len(idx))
        lower[idx] += ramp
        upper[idx] += ramp
    return lower, upper


def system_leak_flow_m3min(ts, start_date, header_rated_capacity_m3min, growth_per_day, start_fraction):
    """Slow background pipework leak, expressed as a flow draw on the whole header.
    Attributed to the lead asset's reporting column. Capped well below the point
    where it would dominate specific power on a normally-running header."""
    days = (ts - start_date).dt.total_seconds().to_numpy() / 86400.0
    leak_fraction = np.clip(start_fraction + growth_per_day * days, 0.0, 0.30)
    return leak_fraction * header_rated_capacity_m3min


def fault_leak_extra_flow_m3min(n, rated_m3min, fault_window_mask, fault_magnitude):
    """Fault-specific accelerated leak on one asset: ramps up across the fault window
    (representing a worsening, undetected leak) and drops back to zero once the
    window ends (representing the maintenance fix)."""
    extra_frac = np.zeros(n)
    if fault_window_mask is not None and fault_window_mask.any():
        idx = np.flatnonzero(fault_window_mask)
        window_days = len(idx) / (60.0 * 24.0)
        max_extra_frac = FAULT_LEAK_GROWTH_PER_DAY * fault_magnitude * window_days
        extra_frac[idx] = np.linspace(0, max_extra_frac, len(idx))
    return extra_frac * rated_m3min


def simulate_header(minute_df, room_assets_cfg, demand_m3min, lower_bar, upper_bar):
    """Run the lead/lag hysteresis control loop for one compressed-air header.

    room_assets_cfg: list of asset config dicts, first entry is lead.
    Returns: pressure (np.array), loaded (dict asset_id -> bool array),
             cycles (dict asset_id -> cumulative load-start count array).
    """
    n = len(minute_df)
    ids = [a["asset_id"] for a in room_assets_cfg]
    rated = {a["asset_id"]: a["rated_m3_per_min"] for a in room_assets_cfg}
    lead_id = ids[0]
    lag_ids = ids[1:]

    pressure = np.zeros(n)
    loaded = {aid: np.zeros(n, dtype=bool) for aid in ids}
    cycles = {aid: np.zeros(n, dtype=np.int32) for aid in ids}

    p = float((lower_bar[0] + upper_bar[0]) / 2.0)
    cur = {aid: False for aid in ids}
    prev = dict(cur)
    cyc = {aid: 0 for aid in ids}

    demand = demand_m3min
    for i in range(n):
        d = demand[i]
        lo = lower_bar[i]
        hi = upper_bar[i]
        if p <= lo:
            cur[lead_id] = True
            if lag_ids and d > rated[lead_id] * 0.85:
                for lid in lag_ids:
                    cur[lid] = True
        elif p >= hi:
            cur[lead_id] = False
            for lid in lag_ids:
                cur[lid] = False
        total_cap = sum(rated[aid] for aid in ids if cur[aid])
        net = total_cap - d
        p = p + net * PRESSURE_GAIN_BAR_PER_M3MIN
        p = min(max(p, lo - 0.4), hi + 0.4)
        pressure[i] = p
        for aid in ids:
            loaded[aid][i] = cur[aid]
            if cur[aid] and not prev[aid]:
                cyc[aid] += 1
            cycles[aid][i] = cyc[aid]
        prev = dict(cur)

    return pressure, loaded, cycles


AUTO_STOP_MINUTES = 5          # assumed: modern load/unload compressors auto-stop the
                                # motor after sitting unloaded this long, rather than idling forever
AUTO_STOP_STANDBY_KW = 2.0     # assumed: control-panel standby draw while auto-stopped


def _auto_stop_mask(loaded_bool, threshold_min=AUTO_STOP_MINUTES):
    """True where the unit has been continuously unloaded for longer than the
    auto-stop timer, i.e. the motor itself has stopped (not just unloaded)."""
    unloaded = ~loaded_bool
    run_id = np.cumsum(loaded_bool)          # increments each time it's loaded
    s = pd.Series(run_id)
    run_len = s.groupby(s).cumcount().to_numpy() + 1
    return unloaded & (run_len > threshold_min)


def compute_asset_output(asset_cfg, pressure, loaded, cycles, own_leak_flow_m3min, overpressure_penalty_rate,
                          off_standby_kw=None, auto_stop=False):
    """Given header-level pressure/loaded state, compute per-asset kW/flow/specific_power.
    own_leak_flow_m3min: this asset's own attributed leak draw (system leak for the
    lead asset, fault-specific leak for a faulted asset, else zeros).
    off_standby_kw: if given, a lag/standby asset that almost never loads is fully
    stopped (this low standby draw) rather than left idling at idle_kw forever —
    a real plant powers down its standby compressor, it doesn't leave it spinning.
    auto_stop: if True, apply the auto-stop timer (see _auto_stop_mask) even to a
    unit that does cycle (e.g. the lead), instead of only an always-idle lag unit."""
    full_kw = asset_cfg["rated_kw"]
    idle_kw = asset_cfg["idle_fraction_of_full_load"] * full_kw
    rated_flow = asset_cfg["rated_m3_per_min"]

    load_frac = loaded.astype(float)
    pressure_factor = 1.0 + (pressure - 7.0) * overpressure_penalty_rate
    running_kw = (idle_kw + load_frac * (full_kw - idle_kw)) * pressure_factor

    if auto_stop:
        stopped = _auto_stop_mask(loaded)
        kw = np.where(stopped, AUTO_STOP_STANDBY_KW, running_kw)
    elif off_standby_kw is not None:
        kw = np.where(load_frac > 0, running_kw, off_standby_kw)
    else:
        kw = running_kw

    leak_flow = own_leak_flow_m3min
    flow = np.where(load_frac > 0, np.maximum(rated_flow - leak_flow, 0.0), 0.0)

    flow_m3_per_hr = flow * 60.0
    specific_power = np.where(flow_m3_per_hr > 1e-6, kw / flow_m3_per_hr, np.nan)

    return pd.DataFrame({
        "kW": kw,
        "pressure_bar": pressure,
        "flow_m3min": flow,
        "leak_flow_m3min": leak_flow,
        "specific_power_kwh_m3": specific_power,
        "load_fraction": load_frac,
        "cycle_count": cycles,
    })


def build_test_rig(minute_df, asset_cfg, start_time_str, run_minutes, rng, fault_mult_series=None):
    """TEST-RIG-CNG-01 runs an independent scheduled test window each production day,
    ramp -> steady -> ramp down, not tied to the main compressed-air header.
    """
    n = len(minute_df)
    full_kw = asset_cfg["rated_kw"]
    idle_kw = asset_cfg["idle_fraction_of_full_load"] * full_kw
    rated_flow = asset_cfg["rated_m3_per_min"]

    h, m = start_time_str.split(":")
    start_min = int(h) * 60 + int(m)
    minute_of_day = (minute_df["ts"].dt.hour * 60 + minute_df["ts"].dt.minute).to_numpy()
    is_prod_day = (minute_df["shift"] != "OFF").to_numpy()

    load_frac = np.zeros(n)
    window_len = run_minutes
    ramp = max(5, window_len // 10)
    rel = minute_of_day - start_min
    in_window = (rel >= 0) & (rel < window_len) & is_prod_day
    rel_in = rel[in_window]
    lf = np.ones_like(rel_in, dtype=float)
    lf = np.where(rel_in < ramp, rel_in / ramp, lf)
    lf = np.where(rel_in > window_len - ramp, (window_len - rel_in) / ramp, lf)
    load_frac[in_window] = np.clip(lf, 0, 1)

    standby_off_kw = 0.5   # assumed: rig is powered down outside its test window, not idling
    kw = np.where(load_frac > 0, idle_kw + load_frac * (full_kw - idle_kw), standby_off_kw)
    leak_frac = 0.08
    flow = np.where(load_frac > 0.02, load_frac * rated_flow * (1 - leak_frac), 0.0)
    pressure = 6.8 + load_frac * 0.5

    flow_m3_per_hr = flow * 60.0
    specific_power = np.where(flow_m3_per_hr > 1e-6, kw / flow_m3_per_hr, np.nan)

    cycle = (in_window & (np.r_[False, np.diff(in_window.astype(int)) == 1])).astype(int)
    cycle_count = np.cumsum(cycle)

    return pd.DataFrame({
        "kW": kw,
        "pressure_bar": pressure,
        "flow_m3min": flow,
        "leak_flow_m3min": np.where(load_frac > 0.02, leak_frac * rated_flow, 0.0),
        "specific_power_kwh_m3": specific_power,
        "load_fraction": load_frac,
        "cycle_count": cycle_count,
    })
