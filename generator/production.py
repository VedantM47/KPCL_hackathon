"""Stage 1: production plan — daily orders per product family, drives air demand, CNC, furnace batches."""
import numpy as np
import pandas as pd


def build_daily_production(minute_df, config, rng):
    """Return a daily-resolution DataFrame: date, shift, family, units.

    Units are assigned per (date, shift, family) for production minutes only.
    A production surge hard-negative multiplies volumes on flagged days.
    """
    dates = sorted(minute_df["date"].unique())
    surge_days = set()
    surge_prob = config["production"]["surge_probability_per_day"]
    surge_lo, surge_hi = config["production"]["surge_multiplier"]

    rows = []
    for d in dates:
        day_rows = minute_df[minute_df["date"] == d]
        shifts_today = [s for s in day_rows["shift"].unique() if s != "OFF"]
        if not shifts_today:
            continue
        is_surge = rng.random() < surge_prob
        if is_surge:
            surge_days.add(d)
        for fam in config["production"]["product_families"]:
            for shift in shifts_today:
                mean = fam["units_per_shift_mean"]
                std = fam["units_per_shift_std"]
                units = max(0, rng.normal(mean, std))
                if is_surge:
                    units *= rng.uniform(surge_lo, surge_hi)
                rows.append({
                    "date": d,
                    "shift": shift,
                    "family": fam["family"],
                    "plant_id": fam["plant_id"],
                    "units": round(units, 1),
                    "is_surge": is_surge,
                })
    return pd.DataFrame(rows)


def production_air_demand_m3min(daily_production, config):
    """Aggregate per (date, shift) air demand in m3/min contributed by production units."""
    fam_lookup = {f["family"]: f for f in config["production"]["product_families"]}
    df = daily_production.copy()
    df["air_demand_m3min"] = df.apply(
        lambda r: r["units"] * fam_lookup[r["family"]]["air_demand_m3min_per_unit"], axis=1
    )
    return df.groupby(["date", "shift"])["air_demand_m3min"].sum().reset_index()
