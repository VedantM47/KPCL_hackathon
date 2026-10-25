"""Stage 8: FastAPI backend for the KPCL energy dashboard.

Reads from the pre-built rollup tables where possible for fast responses.
kpcl_energy.db is treated as "current" data; kpcl_energy_optimized.db is only
used by /scenario/compare. Anomaly detection and the forecast models are
expensive (seconds), so they're computed once at startup and cached in memory.

Most endpoints take an optional ?plant=<plant_id>; omitted or ALL means the
whole company (the original main meter). Per-plant figures come from
fact_plant_meter, an allocation of the main meter (see generator/plants.py).

Run: uvicorn api.main:app --reload --port 8000
"""
import io
import os
import pickle
import sqlite3
from contextlib import asynccontextmanager

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from api import devconsole
from api import live as live_mod
from ml import anomaly as anomaly_mod
from ml import forecast as forecast_mod
from ml import losses as losses_mod
from ml import plant_cfg
from ml.peak_shaving import PeakPlanner

BASELINE_DB = "kpcl_energy.db"
OPTIMIZED_DB = "kpcl_energy_optimized.db"

CACHE = {}


def get_conn(db_path=BASELINE_DB):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return conn


def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


CACHE_DIR = ".cache"
CACHE_FILE = os.path.join(CACHE_DIR, "startup_models.pkl")


def _cache_fingerprint(plants):
    """Anything that changes the trained models: the data, the config and the model code."""
    files = [BASELINE_DB, "config.yaml", "ml/anomaly.py", "ml/forecast.py", "ml/plant_cfg.py"]
    parts = [(f, os.path.getsize(f), int(os.path.getmtime(f))) for f in files if os.path.exists(f)]
    return repr((parts, plants))


def _load_model_cache(plants):
    try:
        with open(CACHE_FILE, "rb") as f:
            blob = pickle.load(f)
        if blob.get("fingerprint") == _cache_fingerprint(plants):
            return blob["anomalies"], blob["forecast"]
    except Exception:
        pass   # missing, stale or unreadable cache: retrain
    return None


def _save_model_cache(plants):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "wb") as f:
            pickle.dump({"fingerprint": _cache_fingerprint(plants), "anomalies": CACHE["anomalies"],
                         "forecast": CACHE["forecast"]}, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"[startup] could not write model cache: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    CACHE["config"] = config
    plants = [plant_cfg.ALL] + plant_cfg.plant_ids(config)

    conn = get_conn()
    cached = _load_model_cache(plants)
    if cached:
        print("[startup] loaded anomaly + forecast models from .cache (delete .cache to retrain)")
        CACHE["anomalies"], CACHE["forecast"] = cached
    else:
        print("[startup] running anomaly detection (first run, ~1 min; cached to disk afterwards) ...")
        flagged = {}
        for asset_id, (table, cols, rule_fn) in anomaly_mod.ASSET_SPECS.items():
            flagged[asset_id] = anomaly_mod.run_asset(conn, asset_id, table, cols, rule_fn)
        CACHE["anomalies"] = pd.concat(flagged.values(), ignore_index=True)

        print("[startup] walk-forward day-ahead forecasts (company + each plant, ~30 s) ...")
        CACHE["forecast"] = {p: forecast_mod.run_forecast(config, conn, p) for p in plants}
        _save_model_cache(plants)

    try:
        CACHE["recommendations"] = pd.read_csv("recommendations.csv")
    except FileNotFoundError:
        CACHE["recommendations"] = None
        print("[startup] recommendations.csv not found — run `python -m ml.recommendations` first. /recommendations will 503 until then.")

    print("[startup] building peak-shaving planners and loss costing ...")
    CACHE["planner"] = {p: PeakPlanner(conn, config, CACHE["forecast"][p], p) for p in plants}
    CACHE["leaks_daily"], CACHE["leaks_by_asset"] = losses_mod.leak_summary(conn, config)
    CACHE["anomaly_excess"] = losses_mod.anomaly_excess(conn, config, CACHE["anomalies"])

    live_mod.start(conn, config, CACHE["anomalies"])

    conn.close()
    print("[startup] ready.")
    yield
    live_mod.stop()


app = FastAPI(title="KPCL Energy Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(live_mod.router)
app.include_router(devconsole.router)


def _records(df):
    """df.to_dict(orient='records') with NaN -> None. A float64 column can't
    hold Python None (pandas coerces it straight back to NaN), so this has to
    run on the plain-dict records, not on the DataFrame itself."""
    records = df.to_dict(orient="records")
    for r in records:
        for k, v in r.items():
            if isinstance(v, float) and v != v:
                r[k] = None
    return records


def _plant(plant):
    """Validate a ?plant= value; returns None for the whole company."""
    p = plant_cfg.norm(plant)
    if p is not None and p not in plant_cfg.plant_ids(CACHE["config"]):
        raise HTTPException(404, f"unknown plant {plant}")
    return p


def _date_filter_sql(from_, to):
    clauses = []
    if from_:
        clauses.append(f"ts >= '{from_}'")
    if to:
        # a bare date (len 10, "YYYY-MM-DD") must include the whole day, not
        # just midnight — "ts <= '2025-02-01'" would lexicographically exclude
        # every row stamped later that same day (e.g. '2025-02-01 00:15:00')
        to_bound = f"{to} 23:59:59" if len(to) == 10 else to
        clauses.append(f"ts <= '{to_bound}'")
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def _plant_name(plant):
    if plant is None:
        return "All plants"
    return next(p["name"] for p in CACHE["config"]["plants"] if p["plant_id"] == plant)


@app.get("/")
def root():
    return {"name": "KPCL Energy Dashboard API", "data_label": "benchmark-calibrated simulation"}


@app.get("/plants")
def plants_list():
    """Plants with their contract demand — the switcher's options."""
    cfg = CACHE["config"]
    out = [{"plant_id": plant_cfg.ALL, "name": "All plants", "city": "", "division": "Company roll-up",
            "contract_kva": plant_cfg.contract_kva(cfg, None)}]
    for p in cfg["plants"]:
        out.append({"plant_id": p["plant_id"], "name": p["name"], "city": p["city"], "division": p["division"],
                    "contract_kva": plant_cfg.contract_kva(cfg, p["plant_id"])})
    return out


def _kpi_numbers(conn, plant, from_, to):
    where = _date_filter_sql(from_, to)
    if plant is None:
        meter = pd.read_sql(f"SELECT ts, kW, kVA, cost_rs FROM fact_main_meter{where}", conn)
        emissions = pd.read_sql(f"SELECT ts, scope1_tco2, scope2_tco2, solar_avoided_tco2 FROM fact_emissions{where}", conn)
    else:
        extra = f"plant_id = '{plant}'"
        w = (where + f" AND {extra}") if where else f" WHERE {extra}"
        meter = pd.read_sql(f"SELECT ts, kW, kVA, cost_rs FROM fact_plant_meter{w}", conn)
        emissions = pd.read_sql(f"SELECT ts, scope1_tco2, scope2_tco2, solar_avoided_tco2 FROM fact_plant_meter{w}", conn)
    solar = pd.read_sql(f"SELECT ts, kW_self_consumed FROM fact_solar{where}", conn)
    main_kw = pd.read_sql(f"SELECT ts, kW FROM fact_main_meter{where}", conn)

    prod_clauses = []
    if from_:
        prod_clauses.append(f"date >= '{from_[:10]}'")
    if to:
        prod_clauses.append(f"date <= '{to[:10]}'")
    if plant is not None:
        prod_clauses.append(f"plant_id = '{plant}'")
    prod_where = (" WHERE " + " AND ".join(prod_clauses)) if prod_clauses else ""
    production = pd.read_sql(f"SELECT units FROM fact_production{prod_where}", conn)

    grid_kwh = meter["kW"].sum() * 0.25
    # solar self-consumed credit is shared across plants in proportion to load (see generator/plants.py)
    if plant is None or main_kw["kW"].sum() <= 0:
        solar_share_factor = 1.0
    else:
        solar_share_factor = meter["kW"].sum() / main_kw["kW"].sum()
    solar_self_kwh = solar["kW_self_consumed"].sum() * 0.25 * solar_share_factor
    total_energy_kwh = grid_kwh + solar_self_kwh
    total_units = production["units"].sum()
    return {
        "total_energy_kwh": round(total_energy_kwh, 1),
        "grid_energy_kwh": round(grid_kwh, 1),
        "cost_rs": round(meter["cost_rs"].sum(), 2),
        "peak_demand_kw": round(meter["kW"].max() if len(meter) else 0.0, 1),
        "peak_demand_kva": round(meter["kVA"].max() if len(meter) else 0.0, 1),
        "scope1_tco2": round(emissions["scope1_tco2"].sum(), 3),
        "scope2_tco2": round(emissions["scope2_tco2"].sum(), 3),
        "solar_avoided_tco2": round(emissions["solar_avoided_tco2"].sum(), 3),
        "energy_intensity_kwh_per_unit": round(total_energy_kwh / total_units, 3) if total_units > 0 else None,
        "solar_share": round(solar_self_kwh / total_energy_kwh, 4) if total_energy_kwh > 0 else None,
    }


@app.get("/kpis")
def kpis(plant: str | None = None, from_: str | None = Query(None, alias="from"), to: str | None = None):
    p = _plant(plant)
    conn = get_conn()
    out = _kpi_numbers(conn, p, from_, to)
    conn.close()
    return {"plant": p or plant_cfg.ALL, "from": from_, "to": to,
            "contract_kva": plant_cfg.contract_kva(CACHE["config"], p), **out,
            "data_label": "benchmark-calibrated simulation"}


@app.get("/production/daily")
def production_daily(plant: str | None = None):
    """Daily production units (by shift/family) joined with that day's total
    plant kWh, for energy-per-unit and shift-comparison views."""
    p = _plant(plant)
    conn = get_conn()
    if p is None:
        prod = pd.read_sql("SELECT date, shift, family, units, is_surge FROM fact_production", conn)
        mm = pd.read_sql("SELECT ts, kW FROM fact_main_meter", conn)
    else:
        prod = pd.read_sql("SELECT date, shift, family, units, is_surge FROM fact_production WHERE plant_id = ?",
                           conn, params=(p,))
        mm = pd.read_sql("SELECT ts, kW, kVA FROM fact_plant_meter WHERE plant_id = ?", conn, params=(p,))
    conn.close()

    mm["date"] = pd.to_datetime(mm["ts"]).dt.strftime("%Y-%m-%d")
    daily_kwh = mm.groupby("date")["kW"].sum() * 0.25

    if len(prod) == 0:   # a plant with no production records (e.g. test-rig-only site)
        out = pd.DataFrame({"kWh": daily_kwh})
        out["total_units"] = 0.0
        out["A"] = 0.0
        out["B"] = 0.0
        out["energy_per_unit_kwh"] = None
        return _records(out.reset_index().rename(columns={"index": "date"}))

    daily_units = prod.groupby("date")["units"].sum()
    daily_shift_units = prod.groupby(["date", "shift"])["units"].sum().unstack(fill_value=0)

    out = pd.DataFrame({"total_units": daily_units, "kWh": daily_kwh}).dropna()
    out = out.join(daily_shift_units, how="left").fillna(0)
    out["energy_per_unit_kwh"] = out["kWh"] / out["total_units"].replace(0, pd.NA)
    out = out.reset_index().rename(columns={"index": "date"})
    return _records(out)


@app.get("/plants/compare")
def plants_compare():
    """Per-plant energy, cost, emissions and peak from the per-plant meter."""
    conn = get_conn()
    df = pd.read_sql(
        "SELECT r.plant_id, p.name as plant_name, p.city, p.division, SUM(r.kWh) as kwh_total, "
        "SUM(r.cost_rs) as cost_rs, SUM(r.scope1_tco2) as scope1_tco2, SUM(r.scope2_tco2) as scope2_tco2 "
        "FROM rollup_daily_plant r LEFT JOIN dim_plant p ON r.plant_id = p.plant_id "
        "GROUP BY r.plant_id ORDER BY kwh_total DESC", conn)
    peaks = pd.read_sql("SELECT plant_id, MAX(kVA) as peak_kva FROM fact_plant_meter GROUP BY plant_id", conn)
    prod = pd.read_sql("SELECT plant_id, SUM(units) as units FROM fact_production GROUP BY plant_id", conn)
    conn.close()
    df = df.merge(peaks, on="plant_id", how="left").merge(prod, on="plant_id", how="left")
    df["contract_kva"] = df["plant_id"].map(lambda p: plant_cfg.contract_kva(CACHE["config"], p))
    df["kwh_per_unit"] = df["kwh_total"] / df["units"].where(df["units"] > 0)
    return _records(df)


@app.get("/assets")
def assets(plant: str | None = None):
    p = _plant(plant)
    conn = get_conn()
    df = pd.read_sql("SELECT a.*, p.name as plant_name, p.city, p.division FROM dim_asset a "
                      "LEFT JOIN dim_plant p ON a.plant_id = p.plant_id", conn)
    conn.close()
    if p is not None:
        df = df[df["plant_id"] == p]
    return _records(df)


RES_RULE = {"15m": "15min", "1h": "1h", "1d": "1D"}
ASSET_TABLE = {
    "CMP-CENT-01": "fact_compressor", "CMP-SCR-01": "fact_compressor",
    "CMP-REC-01": "fact_compressor", "TEST-RIG-CNG-01": "fact_compressor",
    "CHILLER-SCR-01": "fact_chiller", "CHILLER-VAM-01": "fact_chiller",
    "FURNACE-HT-01": "fact_furnace", "PAINT-BOOTH-01": "fact_paint_booth",
    "SOLAR-SASWAD-01": "fact_solar",
}


@app.get("/assets/{asset_id}/series")
def asset_series(asset_id: str, from_: str | None = Query(None, alias="from"), to: str | None = None, res: str = "15m"):
    if res not in RES_RULE:
        raise HTTPException(400, f"res must be one of {list(RES_RULE)}")
    conn = get_conn()
    where = _date_filter_sql(from_, to)

    table = ASSET_TABLE.get(asset_id, "fact_meter")
    if table in ("fact_furnace", "fact_paint_booth", "fact_solar"):
        q = f"SELECT * FROM {table}{where}"
    else:
        extra = f" AND asset_id='{asset_id}'" if where else f" WHERE asset_id='{asset_id}'"
        q = f"SELECT * FROM {table}{where}{extra}"
    df = pd.read_sql(q, conn)
    conn.close()
    if len(df) == 0:
        raise HTTPException(404, f"no data for asset_id={asset_id}")

    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts")
    numeric_cols = df.select_dtypes(include="number").columns
    if res == "15m":
        out = df.reset_index()
    else:
        out = df[numeric_cols].resample(RES_RULE[res]).mean().reset_index()
    out["ts"] = out["ts"].astype(str)
    return _records(out)


def _replay_tomorrow():
    """The day after the live replay's current simulated day (what a planner would be looking at)."""
    e = live_mod.ENGINE.get("e")
    if e is None:
        return None
    return (e.ts.iloc[e.idx].normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


@app.get("/forecast/demand")
def forecast_demand(plant: str | None = None, date: str | None = None):
    """Day-ahead forecast for one day (default: the replay's tomorrow) with a P10-P90 band, the
    day's peak/breach-risk forecast, and walk-forward evaluation metrics."""
    p = _plant(plant)
    cached = CACHE.get("forecast", {}).get(p or plant_cfg.ALL)
    if cached is None:
        raise HTTPException(503, "forecast model not ready")
    iv, days = cached["intervals"], cached["days"]
    if date is None:
        date = _replay_tomorrow() or iv["ts"].max().strftime("%Y-%m-%d")
    try:
        day = pd.Timestamp(date).normalize()
    except ValueError:
        raise HTTPException(400, f"unparseable date: {date}")
    if day.year != 2025:   # the replay wraps around a single simulated year
        day = day.replace(year=2025)
    rows = iv[iv["date"] == day].copy()
    covered = len(rows) > 0
    if not covered:
        # before the first forecast origin (Jan-Feb): show what was metered, say there is no forecast
        rows = _plant_day_actuals(p, day)
    rows["ts"] = rows["ts"].astype(str)
    cols = ["ts", "kW", "kVA", "pred_kw", "p10_kw", "p90_kw", "pred_kva", "p10_kva", "p90_kva", "breach_flag"]
    for c in cols:
        if c not in rows:
            rows[c] = None
    d = days.loc[day] if day in days.index else None
    m = cached["metrics"]
    return {
        "plant_id": p or plant_cfg.ALL,
        "date": day.strftime("%Y-%m-%d"),
        "covered": covered,
        "first_forecast_date": cached["first_forecast_date"],
        "method": "walk-forward day-ahead (retrained monthly on past data only); "
                  "mean + conformal P10-P90 band; separate daily-peak quantile model",
        "day": None if d is None else {
            "peak_p10_kva": round(float(d["peak_p10_kva"]), 1), "peak_p50_kva": round(float(d["peak_p50_kva"]), 1),
            "peak_p90_kva": round(float(d["peak_p90_kva"]), 1), "breach_risk": round(float(d["breach_risk"]), 3),
            "near_contract_risk": round(float(d["near_risk"]), 3),
            "actual_peak_kva": None if pd.isna(d["peak_kva"]) else round(float(d["peak_kva"]), 1),
        },
        "metrics": {
            # older fields, kept for existing clients
            "mape_pct": round(cached["mape"], 2),
            "wape_pct": round(cached["wape"], 2),
            "naive_climatology_wape_pct": round(cached["naive_wape"], 2),
            "contract_kva": cached["contract_kva"],
            "n_breaches_in_test_period": cached["n_breaches"],
        },
        "evaluation": m,
        "last_24h": _records(rows[cols]),
    }


def _plant_day_actuals(p, day):
    conn = get_conn()
    try:
        lo, hi = day.strftime("%Y-%m-%d"), (day + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if p is None:
            df = pd.read_sql("SELECT ts, kW, kVA FROM fact_main_meter WHERE ts >= ? AND ts < ? ORDER BY ts", conn, params=(lo, hi))
        else:
            df = pd.read_sql("SELECT ts, kW, kVA FROM fact_plant_meter WHERE plant_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
                             conn, params=(p, lo, hi))
        return df
    finally:
        conn.close()


def _anomaly_frame(plant, asset_id=None):
    df = CACHE.get("anomalies")
    if df is None:
        raise HTTPException(503, "anomaly cache not ready")
    out = df[df["final_flag"]].copy()
    # ranked over the whole flagged set, so a plant/asset filter does not change a row's severity
    out["severity"] = live_mod.score_severity(out)
    if plant is not None:
        out = out[out["asset_id"].isin(plant_cfg.assets_of(CACHE["config"], plant))]
    if asset_id:
        out = out[out["asset_id"] == asset_id]
    return out


@app.get("/anomalies")
def anomalies(from_: str | None = Query(None, alias="from"), to: str | None = None, asset_id: str | None = None,
              plant: str | None = None):
    out = _anomaly_frame(_plant(plant), asset_id)
    if from_:
        out = out[out["ts"] >= from_]
    if to:
        # same end-of-day boundary issue as _date_filter_sql: a bare date must
        # cover the whole day, not just its midnight instant
        to_bound = pd.Timestamp(to) + pd.Timedelta(days=1) if len(to) == 10 else pd.Timestamp(to)
        out = out[out["ts"] < to_bound]
    out = out.sort_values("anomaly_score", ascending=False)
    out["ts"] = out["ts"].astype(str)
    return _records(out[["ts", "asset_id", "anomaly_score", "severity", "model_flag", "rule_flag"]])


@app.get("/anomalies/daily")
def anomalies_daily(plant: str | None = None):
    """Day x asset worst-severity grid — aggregated server-side because the raw
    15-min anomaly feed is ~6MB for a full year, far too heavy for a timeline
    widget that only needs one value per (asset, day)."""
    out = _anomaly_frame(_plant(plant))
    out["date"] = out["ts"].dt.strftime("%Y-%m-%d")
    out["rank"] = out["severity"].map({"low": 1, "medium": 2, "high": 3, "critical": 4}).astype(int)
    daily = out.groupby(["asset_id", "date"])["rank"].max().reset_index()
    return _records(daily)


@app.get("/schedule/days")
def schedule_days(top_n: int = 40, plant: str | None = None, rank_by: str = "actual"):
    """Days to pick for the peak-shaving plan, ranked by metered peak (default — the phone's
    "Jump to peak day" relies on this being a day that really breached) or by forecast breach
    risk (rank_by=risk). Each row carries both the metered peak and the day-ahead forecast."""
    p = _plant(plant)
    if rank_by not in ("actual", "risk"):
        raise HTTPException(400, "rank_by must be actual or risk")
    return CACHE["planner"][p or plant_cfg.ALL].risk_days(max(1, min(top_n, 366)), rank_by=rank_by)


@app.get("/schedule/plan")
def schedule_plan(date: str, plant: str | None = None):
    p = _plant(plant)
    plan = CACHE["planner"][p or plant_cfg.ALL].plan(date)
    if plan is None:
        raise HTTPException(404, f"no complete data for {date}")
    return plan


def _losses_for(plant):
    ids = plant_cfg.assets_of(CACHE["config"], plant)
    leaks = CACHE["leaks_by_asset"]
    excess = CACHE["anomaly_excess"]
    return leaks[leaks["asset_id"].isin(ids)], excess[excess["asset_id"].isin(ids)]


@app.get("/losses/summary")
def losses_summary(plant: str | None = None):
    """What leaks and flagged anomalies cost: kWh, Rs (ToD-weighted) and CO2."""
    leaks, excess = _losses_for(_plant(plant))
    return {
        "leaks_by_asset": _records(leaks),
        "anomaly_excess_by_asset": _records(excess),
        "totals": {
            "avoidable_leak_rs": round(float(leaks["avoidable_rs"].sum()), 0),
            "avoidable_leak_kwh": round(float(leaks["avoidable_kwh"].sum()), 0),
            "avoidable_leak_tco2": round(float(leaks["avoidable_tco2"].sum()), 2),
            "anomaly_excess_rs": round(float(excess["excess_rs"].sum()), 0),
            "anomaly_excess_kwh": round(float(excess["excess_kwh"].sum()), 0),
        },
        "method": "Leak loss = leak flow x specific power x 60; 'avoidable' is the part above each "
                  "compressor's background floor (5th percentile). Anomaly excess = draw above normal "
                  "for that (weekday, hour) on flagged intervals, electric loads only. Rs are ToD-weighted. "
                  "CMP-SCR-01 is the standby unit, so its leak is costed at the fleet median specific power. "
                  "The two figures overlap (leaks raise compressor draw) — do not add them.",
        "data_label": "benchmark-calibrated simulation",
    }


@app.get("/losses/leaks/daily")
def losses_leaks_daily(plant: str | None = None):
    ids = plant_cfg.assets_of(CACHE["config"], _plant(plant))
    d = CACHE["leaks_daily"]
    return _records(d[d["asset_id"].isin(ids)].round(2))


def _csv_for_plant(path, plant):
    """Rows of a precomputed CSV for a plant. Files written before per-plant
    support have no plant_id column and only describe the whole company."""
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return None
    if "plant_id" not in df.columns:
        df["plant_id"] = plant_cfg.ALL
    return df[df["plant_id"] == (plant or plant_cfg.ALL)]


@app.get("/whatif/grid")
def whatif_grid(plant: str | None = None):
    """Precomputed one-lever-at-a-time simulation diffs (see ml/whatif.py)."""
    p = _plant(plant)
    grid = _csv_for_plant("whatif_grid.csv", p)
    base_all = _csv_for_plant("whatif_baseline.csv", p)
    if grid is None or base_all is None:
        raise HTTPException(503, "whatif_grid.csv not found — run `python -m ml.whatif` first")
    if len(base_all) == 0:
        raise HTTPException(404, "no what-if results for this plant — re-run `python -m ml.whatif`")
    base = base_all.iloc[0].to_dict()
    levers = []
    for lever, g in grid.groupby("lever", sort=False):
        levers.append({"lever": lever, "label": g["lever_label"].iloc[0],
                       "options": _records(g.drop(columns=["lever", "lever_label", "plant_id"]).round(2))})
    return {"plant_id": p or plant_cfg.ALL,
            "baseline": {k: v for k, v in base.items() if k not in ("scenario", "plant_id")}, "levers": levers,
            "note": "Each row is a full-year re-simulation with one policy lever changed. Combined "
                    "totals add the rows and ignore interactions between levers.",
            "data_label": "benchmark-calibrated simulation"}


@app.get("/recommendations")
def recommendations(plant: str | None = None):
    p = _plant(plant)
    if CACHE.get("recommendations") is None:
        raise HTTPException(503, "recommendations.csv not found — run `python -m ml.recommendations` first")
    df = _csv_for_plant("recommendations.csv", p)
    df = df[df["rs_saved"].abs() > 0] if len(df) else df
    return _records(df.sort_values("rs_saved", ascending=False).assign(rank=lambda d: range(1, len(d) + 1)))


def _scenario_totals(db_path, plant):
    conn = get_conn(db_path)
    if plant is None:
        mm = pd.read_sql("SELECT kW, cost_rs FROM fact_main_meter", conn)
        em = pd.read_sql("SELECT scope1_tco2, scope2_tco2 FROM fact_emissions", conn)
    else:
        mm = pd.read_sql("SELECT kW, cost_rs, scope1_tco2, scope2_tco2 FROM fact_plant_meter WHERE plant_id = ?",
                         conn, params=(plant,))
        em = mm
    conn.close()
    return {
        "kWh": round(mm["kW"].sum() * 0.25, 1),
        "cost_rs": round(mm["cost_rs"].sum(), 2),
        "tco2": round((em["scope1_tco2"] + em["scope2_tco2"]).sum(), 2),
    }


@app.get("/scenario/compare")
def scenario_compare(plant: str | None = None):
    p = _plant(plant)
    results = {label: _scenario_totals(path, p) for label, path in [("baseline", BASELINE_DB), ("optimized", OPTIMIZED_DB)]}
    results["savings"] = {k: round(results["baseline"][k] - results["optimized"][k], 2) for k in ("kWh", "cost_rs", "tco2")}
    return results


def _carbon_monthly(conn, plant=None):
    if plant is None:
        emissions = pd.read_sql("SELECT ts, scope1_tco2, scope2_tco2, solar_avoided_tco2 FROM fact_emissions", conn)
        fuel_events = pd.read_sql("SELECT ts, asset_id, fuel_type, amount_kg FROM fact_fuel_event", conn)
    else:
        emissions = pd.read_sql("SELECT ts, scope1_tco2, scope2_tco2, solar_avoided_tco2 FROM fact_plant_meter "
                                "WHERE plant_id = ?", conn, params=(plant,))
        fuel_events = pd.read_sql("SELECT ts, asset_id, fuel_type, amount_kg FROM fact_fuel_event", conn)
        ids = plant_cfg.assets_of(CACHE["config"], plant)
        # outage diesel is booked on the main meter; share it by the plant's load that month
        share = pd.read_sql("SELECT ts, kW, kVA FROM fact_plant_meter WHERE plant_id = ?", conn, params=(plant,))
        total = pd.read_sql("SELECT ts, kW FROM fact_main_meter", conn)
        m = pd.to_datetime(share["ts"]).dt.strftime("%Y-%m")
        mt = pd.to_datetime(total["ts"]).dt.strftime("%Y-%m")
        month_share = (share.groupby(m)["kW"].sum() / total.groupby(mt)["kW"].sum()).to_dict()
        fuel_events["month"] = pd.to_datetime(fuel_events["ts"]).dt.strftime("%Y-%m")
        is_main = fuel_events["asset_id"] == "MAIN-METER"
        fuel_events.loc[is_main, "amount_kg"] = fuel_events.loc[is_main, "amount_kg"] * fuel_events.loc[is_main, "month"].map(month_share).fillna(0)
        fuel_events = fuel_events[fuel_events["asset_id"].isin(ids) | is_main]

    emissions["month"] = pd.to_datetime(emissions["ts"]).dt.strftime("%Y-%m")
    monthly = emissions.groupby("month").agg(
        scope1_tco2=("scope1_tco2", "sum"), scope2_tco2=("scope2_tco2", "sum"),
        solar_avoided_tco2=("solar_avoided_tco2", "sum"),
    ).reset_index()
    monthly["total_tco2"] = monthly["scope1_tco2"] + monthly["scope2_tco2"]

    fuel_events["month"] = pd.to_datetime(fuel_events["ts"]).dt.strftime("%Y-%m")
    fuel_by_type = fuel_events.groupby(["month", "fuel_type"])["amount_kg"].sum().unstack(fill_value=0).reset_index()
    return monthly, fuel_by_type


@app.get("/carbon/monthly")
def carbon_monthly(plant: str | None = None):
    conn = get_conn()
    monthly, fuel_by_type = _carbon_monthly(conn, _plant(plant))
    conn.close()
    return {"monthly": _records(monthly), "fuel_by_type": _records(fuel_by_type)}


@app.get("/carbon/report")
def carbon_report(format: str = "csv", plant: str | None = None):
    if format not in ("csv", "pdf"):
        raise HTTPException(400, "format must be 'csv' or 'pdf'")
    p = _plant(plant)
    name = _plant_name(p)
    slug = (p or "all").lower()

    conn = get_conn()
    monthly, fuel_by_type = _carbon_monthly(conn, p)
    conn.close()

    if format == "csv":
        buf = io.StringIO()
        buf.write(f"# KPCL BRSR-style carbon report — {name} — benchmark-calibrated simulation. "
                   "VERIFY all emission factors in config.yaml before external use.\n")
        monthly.to_csv(buf, index=False)
        buf.write("\n# Scope 1 fuel breakdown by month (kg, or litres for diesel)\n")
        fuel_by_type.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                  headers={"Content-Disposition": f"attachment; filename=kpcl_carbon_report_{slug}.csv"})

    return StreamingResponse(_render_carbon_pdf(monthly, fuel_by_type, name), media_type="application/pdf",
                              headers={"Content-Disposition": f"attachment; filename=kpcl_carbon_report_{slug}.pdf"})


def _pdf_table(df, header_color="#2c3e50"):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    rounded = df.round(2)
    t = Table([list(rounded.columns)] + rounded.values.tolist(), repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    return t


def _render_carbon_pdf(monthly, fuel_by_type, plant_name="All plants"):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f"KPCL Carbon Report (BRSR-style) — {plant_name}", styles["Title"]),
        Paragraph("Benchmark-calibrated simulation. All figures are synthetic. Emission factors are config "
                  "placeholders — VERIFY before external use.", styles["Italic"]),
        Spacer(1, 12),
        Paragraph("Monthly Scope 1 / Scope 2 / Solar-avoided (tCO2e)", styles["Heading2"]),
        _pdf_table(monthly),
        Spacer(1, 16),
        Paragraph("Scope 1 Fuel Breakdown by Month", styles["Heading2"]),
        _pdf_table(fuel_by_type),
    ]
    doc.build(elements)
    buf.seek(0)
    return buf


@app.get("/reports/plant")
def plant_report(plant: str | None = None):
    """Detailed management report for a plant (or the whole company) — see api/reports.py."""
    from api.reports import build_plant_report

    p = _plant(plant)
    cfg = CACHE["config"]
    conn = get_conn()
    k = _kpi_numbers(conn, p, None, None)
    company = _kpi_numbers(conn, None, None, None)
    _, fuel_by_type = _carbon_monthly(conn, p)
    leaks, excess = _losses_for(p)
    recs = _csv_for_plant("recommendations.csv", p)
    ids = plant_cfg.assets_of(cfg, p)
    anomalies = CACHE["anomalies"]
    buf = build_plant_report(
        conn, cfg, p, plant_name=_plant_name(p), kpis=k, planner=CACHE["planner"][p or plant_cfg.ALL],
        leaks=leaks, excess=excess, recs=recs, anomalies=anomalies[anomalies["asset_id"].isin(ids)],
        company_kwh=company["total_energy_kwh"], company_cost=company["cost_rs"],
        company_tco2=company["scope1_tco2"] + company["scope2_tco2"], fuel_by_type=fuel_by_type)
    conn.close()
    slug = (p or "all").lower()
    return StreamingResponse(buf, media_type="application/pdf",
                              headers={"Content-Disposition": f"attachment; filename=kpcl_plant_report_{slug}.pdf"})
