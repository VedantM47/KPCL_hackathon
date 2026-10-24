"""Stage 3: fault schedule -> boolean minute-level masks + fact_fault_label rows,
plus hard-negative (normal-but-unusual) labels."""
import datetime as dt
import numpy as np
import pandas as pd


def _window_mask(minute_df, start_date, end_date):
    ts = minute_df["ts"]
    start = pd.Timestamp(start_date, tz=ts.dt.tz)
    end = pd.Timestamp(end_date, tz=ts.dt.tz) + pd.Timedelta(days=1)
    return ((ts >= start) & (ts < end)).to_numpy()


def build_fault_masks(minute_df, config):
    """Return dict: (asset_id, fault_type) -> {'mask': bool array, 'magnitude': float,
    'start': str, 'end': str}."""
    masks = {}
    for f in config["faults"]:
        mask = _window_mask(minute_df, f["start"], f["end"])
        masks[(f["asset_id"], f["fault_type"])] = {
            "mask": mask,
            "magnitude": f["magnitude"],
            "start": f["start"],
            "end": f["end"],
        }
    return masks


def build_fault_label_rows(config):
    """fact_fault_label rows — one per configured fault, asset-level."""
    rows = []
    for f in config["faults"]:
        rows.append({
            "asset_id": f["asset_id"],
            "fault_type": f["fault_type"],
            "start_ts": f["start"],
            "end_ts": f["end"],
            "magnitude": f["magnitude"],
            "label_class": "fault",
        })
    for hn in config.get("hard_negatives", []):
        rows.append({
            "asset_id": None,
            "fault_type": hn["label_type"],
            "start_ts": hn["start"],
            "end_ts": hn["end"],
            "magnitude": None,
            "label_class": "normal",
        })
    return pd.DataFrame(rows)


def outage_mask(minute_df, config):
    """Boolean mask for injected grid-outage windows (DG diesel covers load instead)."""
    n = len(minute_df)
    mask = np.zeros(n, dtype=bool)
    ts = minute_df["ts"]
    for o in config.get("grid_outages", []):
        day = pd.Timestamp(o["date"], tz=ts.dt.tz)
        start = day + pd.Timedelta(hours=int(o["start"].split(":")[0]), minutes=int(o["start"].split(":")[1]))
        end = day + pd.Timedelta(hours=int(o["end"].split(":")[0]), minutes=int(o["end"].split(":")[1]))
        mask |= ((ts >= start) & (ts < end)).to_numpy()
    return mask


def heat_wave_mask(minute_df, config):
    for hn in config.get("hard_negatives", []):
        if hn["label_type"] == "heat_wave":
            return _window_mask(minute_df, hn["start"], hn["end"])
    return np.zeros(len(minute_df), dtype=bool)
