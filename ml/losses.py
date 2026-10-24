"""Energy-loss costing: turns compressed-air leaks and flagged anomalies into
kWh, Rs and kg CO2 so the dashboard can say what a problem is costing.

Two estimates, both deliberately simple and stated as such in the API:
  - Leak loss: leak flow (m3/min) x the compressor's specific power (kWh/m3)
    x 60 = kW burned making air that escapes. "Avoidable" leak is the part
    above each compressor's background floor (5th percentile over the year),
    since a small leak level is normal for any real compressed-air network.
  - Anomaly excess: on intervals the anomaly detector flagged, the draw above
    the asset's normal draw for that (day-of-week, hour). Electric only — the
    furnace's gas use is not in kW.

Rs uses the ToD rate for each interval; CO2 uses the grid factor (Scope 2).
"""
import numpy as np
import pandas as pd

from ml.peak_shaving import tod_rate_array

COMPRESSORS = ["CMP-CENT-01", "CMP-SCR-01", "CMP-REC-01"]
STEP_H = 0.25


def _rate_for(ts, rates):
    return rates[(ts.dt.hour * 4 + ts.dt.minute // 15).to_numpy()]


def grid_kg_per_kwh(config):
    return config["emission_factors"]["grid_tco2_per_mwh"]["value"]   # t/MWh == kg/kWh


def leak_losses(conn, config):
    """Per-interval leak kW/Rs/kg for each compressor, with an avoidable share."""
    rates = tod_rate_array(config)
    ef = grid_kg_per_kwh(config)
    df = pd.read_sql("SELECT ts, asset_id, leak_flow_m3min, specific_power_kwh_m3 FROM fact_compressor "
                     f"WHERE asset_id IN ({','.join(repr(a) for a in COMPRESSORS)}) ORDER BY ts", conn)
    df["ts"] = pd.to_datetime(df["ts"])
    out = []
    # CMP-SCR-01 is the standby unit (no flow of its own), so its leak is served by the
    # running compressors — cost it at the fleet's median specific power instead.
    fleet_sp = float(df["specific_power_kwh_m3"].median())
    for asset, g in df.groupby("asset_id"):
        g = g.copy()
        g["specific_power_kwh_m3"] = g["specific_power_kwh_m3"].fillna(fleet_sp)
        g["leak_flow_m3min"] = g["leak_flow_m3min"].fillna(0.0)
        floor = float(g["leak_flow_m3min"].quantile(0.05))
        g["leak_kw"] = g["leak_flow_m3min"] * g["specific_power_kwh_m3"] * 60
        g["avoidable_kw"] = (g["leak_flow_m3min"] - floor).clip(lower=0) * g["specific_power_kwh_m3"] * 60
        g["rate"] = _rate_for(g["ts"], rates)
        g["leak_floor_m3min"] = floor
        out.append(g)
    return pd.concat(out, ignore_index=True), ef


def leak_summary(conn, config):
    df, ef = leak_losses(conn, config)
    df["date"] = df["ts"].dt.strftime("%Y-%m-%d")
    df["kwh"] = df["avoidable_kw"] * STEP_H
    df["rs"] = df["kwh"] * df["rate"]
    df["total_kwh"] = df["leak_kw"] * STEP_H
    df["total_rs"] = df["total_kwh"] * df["rate"]

    daily = df.groupby(["date", "asset_id"]).agg(
        avoidable_kwh=("kwh", "sum"), avoidable_rs=("rs", "sum"),
        total_leak_kwh=("total_kwh", "sum"), total_leak_rs=("total_rs", "sum"),
    ).reset_index()
    daily["avoidable_kgco2"] = daily["avoidable_kwh"] * ef

    by_asset = df.groupby("asset_id").agg(
        avoidable_kwh=("kwh", "sum"), avoidable_rs=("rs", "sum"),
        total_leak_kwh=("total_kwh", "sum"), total_leak_rs=("total_rs", "sum"),
        leak_floor_m3min=("leak_floor_m3min", "first"), peak_leak_m3min=("leak_flow_m3min", "max"),
    ).reset_index()
    by_asset["avoidable_tco2"] = by_asset["avoidable_kwh"] * ef / 1000
    return daily, by_asset


def anomaly_excess(conn, config, anomalies):
    """Excess draw on flagged intervals vs normal for that (dow, hour) per asset."""
    rates = tod_rate_array(config)
    ef = grid_kg_per_kwh(config)
    meter = pd.read_sql("SELECT ts, asset_id, kW FROM fact_meter WHERE asset_id != 'SOLAR-SASWAD-01'", conn)
    meter["ts"] = pd.to_datetime(meter["ts"])
    flags = anomalies[["ts", "asset_id", "final_flag"]]
    m = meter.merge(flags, on=["ts", "asset_id"], how="left")
    m["final_flag"] = m["final_flag"].eq(True)
    flagged_assets = set(flags.loc[flags["final_flag"], "asset_id"])
    m = m[m["asset_id"].isin(flagged_assets)].copy()
    m["dow"] = m["ts"].dt.dayofweek
    m["hour"] = m["ts"].dt.hour
    # "normal" = typical draw for that slot over ALL intervals (flag-agnostic): for loads like the CNC,
    # where a plain rule flags most working intervals, a non-flagged baseline would be the idle level
    # and every working interval would count as excess.
    normal = m.groupby(["asset_id", "dow", "hour"])["kW"].median().rename("normal_kw")
    m = m.merge(normal, on=["asset_id", "dow", "hour"], how="left")
    f = m[m["final_flag"]].copy()
    f["excess_kw"] = (f["kW"] - f["normal_kw"]).clip(lower=0).fillna(0.0)
    f["excess_kwh"] = f["excess_kw"] * STEP_H
    f["excess_rs"] = f["excess_kwh"] * _rate_for(f["ts"], rates)
    by_asset = f.groupby("asset_id").agg(
        flagged_intervals=("kW", "size"), excess_kwh=("excess_kwh", "sum"), excess_rs=("excess_rs", "sum"),
    ).reset_index()
    by_asset["excess_tco2"] = by_asset["excess_kwh"] * ef / 1000
    return by_asset.sort_values("excess_rs", ascending=False)
