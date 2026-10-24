"""Stage 4: fact_fuel_event rows — furnace LPG per batch, VAM gas (daily), refrigerant
top-up after a leak repair, and DG diesel during injected grid outages."""
import numpy as np
import pandas as pd


def build_fuel_events(minute_df, assets, config, fault_masks, main_meter_kw=None, outage_mask_arr=None):
    rows = []

    furnace = assets["FURNACE-HT-01"]
    batch_ids = furnace["batch_id"].to_numpy()
    fuel_kg = furnace["fuel_kg"].to_numpy()
    ts = minute_df["ts"]
    for bid in np.unique(batch_ids):
        if bid == 0:
            continue
        bmask = batch_ids == bid
        total_fuel = fuel_kg[bmask].sum()
        if total_fuel <= 0:
            continue
        first_ts = ts[bmask].iloc[0]
        rows.append({"asset_id": "FURNACE-HT-01", "ts": first_ts, "fuel_type": "LPG",
                     "amount_kg": float(total_fuel), "note": f"heat-treat batch {bid}"})

    vam = assets["CHILLER-VAM-01"]
    vam_df = pd.DataFrame({"ts": ts, "fuel_kg": vam["fuel_kg"].to_numpy()}).set_index("ts")
    daily_gas = vam_df["fuel_kg"].resample("1D").sum()
    fuel_type = vam["fuel_type"].iloc[0]
    for day_ts, amt in daily_gas.items():
        if amt > 0:
            rows.append({"asset_id": "CHILLER-VAM-01", "ts": day_ts, "fuel_type": fuel_type,
                         "amount_kg": float(amt), "note": "daily VAM heat-input fuel"})

    leak_key = ("CHILLER-SCR-01", "refrigerant_leak")
    if leak_key in fault_masks:
        mask = fault_masks[leak_key]["mask"]
        idx = np.flatnonzero(mask)
        if len(idx) > 0:
            mag = fault_masks[leak_key]["magnitude"]
            topup_kg = 25.0 * mag / 0.35
            end_ts = ts.iloc[idx[-1]]
            rows.append({"asset_id": "CHILLER-SCR-01", "ts": end_ts, "fuel_type": "r410a_topup",
                         "amount_kg": float(topup_kg), "note": "refrigerant top-up after leak repair"})

    if main_meter_kw is not None and outage_mask_arr is not None and outage_mask_arr.any():
        sfc = config["dg_fuel_litre_per_kwh"]
        outage_df = pd.DataFrame({"ts": ts, "kw": main_meter_kw, "outage": outage_mask_arr}).set_index("ts")
        outage_only = outage_df[outage_df["outage"]]
        daily_outage_kwh = (outage_only["kw"] / 60.0).resample("1D").sum()
        for day_ts, kwh in daily_outage_kwh.items():
            if kwh > 0:
                rows.append({"asset_id": "MAIN-METER", "ts": day_ts, "fuel_type": "diesel_litre",
                             "amount_kg": float(kwh * sfc), "note": "DG diesel during grid outage"})

    return pd.DataFrame(rows)
