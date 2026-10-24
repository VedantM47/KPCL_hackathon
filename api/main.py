"""Stage 8: FastAPI backend for the KPCL energy dashboard.

Reads from the pre-built rollup tables where possible for fast responses.
kpcl_energy.db is treated as "current" data; kpcl_energy_optimized.db is only
used by /scenario/compare. Anomaly detection and the forecast model are both
expensive (seconds), so they're computed once at startup and cached in memory
— /anomalies and /forecast/demand serve from that cache.

Run: uvicorn api.main:app --reload --port 8000
"""
import io
import sqlite3
from contextlib import asynccontextmanager

import pandas as pd
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from ml import anomaly as anomaly_mod
from ml import forecast as forecast_mod

BASELINE_DB = "kpcl_energy.db"
OPTIMIZED_DB = "kpcl_energy_optimized.db"

CACHE = {}


def get_conn(db_path=BASELINE_DB):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return conn


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    CACHE["config"] = config

    conn = get_conn()
    print("[startup] running anomaly detection (cached for the process lifetime) ...")
    flagged = {}
    for asset_id, (table, cols, rule_fn) in anomaly_mod.ASSET_SPECS.items():
        flagged[asset_id] = anomaly_mod.run_asset(conn, asset_id, table, cols, rule_fn)
    CACHE["anomalies"] = pd.concat(flagged.values(), ignore_index=True)

    print("[startup] training the day-ahead forecast model (cached for the process lifetime) ...")
    CACHE["forecast"] = forecast_mod.run_forecast(config, conn)

    try:
        CACHE["recommendations"] = pd.read_csv("recommendations.csv")
    except FileNotFoundError:
        CACHE["recommendations"] = None
        print("[startup] recommendations.csv not found — run `python -m ml.recommendations` first. /recommendations will 503 until then.")

    conn.close()
    print("[startup] ready.")
    yield


app = FastAPI(title="KPCL Energy Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/")
def root():
    return {"name": "KPCL Energy Dashboard API", "data_label": "benchmark-calibrated simulation"}


@app.get("/kpis")
def kpis(plant: str | None = None, from_: str | None = Query(None, alias="from"), to: str | None = None):
    conn = get_conn()
    where = _date_filter_sql(from_, to)

    main_meter = pd.read_sql(f"SELECT ts, kW, cost_rs FROM fact_main_meter{where}", conn)
    emissions = pd.read_sql(f"SELECT ts, scope1_tco2, scope2_tco2, solar_avoided_tco2 FROM fact_emissions{where}", conn)
    solar = pd.read_sql(f"SELECT ts, kW_self_consumed, kW_exported FROM fact_solar{where}", conn)

    prod_where = ""
    if from_ or to:
        clauses = []
        if from_:
            clauses.append(f"date >= '{from_[:10]}'")
        if to:
            clauses.append(f"date <= '{to[:10]}'")
        prod_where = " WHERE " + " AND ".join(clauses)
    production = pd.read_sql(f"SELECT units FROM fact_production{prod_where}", conn)

    grid_kwh = main_meter["kW"].sum() * 0.25
    cost_rs = main_meter["cost_rs"].sum()
    peak_kw = main_meter["kW"].max() if len(main_meter) else 0.0
    scope1 = emissions["scope1_tco2"].sum()
    scope2 = emissions["scope2_tco2"].sum()
    solar_avoided = emissions["solar_avoided_tco2"].sum()
    total_units = production["units"].sum()

    # main meter kWh is already net-of-solar-self-consumption, so the plant's
    # true gross consumption is grid + self-consumed solar (exported solar
    # never reaches plant load, so it's excluded from the "share" calc)
    solar_self_kwh = solar["kW_self_consumed"].sum() * 0.25
    total_energy_kwh = grid_kwh + solar_self_kwh
    solar_share = solar_self_kwh / total_energy_kwh if total_energy_kwh > 0 else None
    energy_intensity = total_energy_kwh / total_units if total_units > 0 else None

    conn.close()
    return {
        "plant": plant, "from": from_, "to": to,
        "total_energy_kwh": round(total_energy_kwh, 1),
        "grid_energy_kwh": round(grid_kwh, 1),
        "cost_rs": round(cost_rs, 2),
        "peak_demand_kw": round(peak_kw, 1),
        "scope1_tco2": round(scope1, 3),
        "scope2_tco2": round(scope2, 3),
        "solar_avoided_tco2": round(solar_avoided, 3),
        "energy_intensity_kwh_per_unit": round(energy_intensity, 3) if energy_intensity else None,
        "solar_share": round(solar_share, 4) if solar_share is not None else None,
        "data_label": "benchmark-calibrated simulation",
    }


@app.get("/production/daily")
def production_daily():
    """Daily production units (by shift/family) joined with that day's total
    plant kWh, for energy-per-unit and shift-comparison views."""
    conn = get_conn()
    prod = pd.read_sql("SELECT date, shift, family, units, is_surge FROM fact_production", conn)
    mm = pd.read_sql("SELECT ts, kW FROM fact_main_meter", conn)
    conn.close()

    mm["date"] = pd.to_datetime(mm["ts"]).dt.strftime("%Y-%m-%d")
    daily_kwh = mm.groupby("date")["kW"].sum() * 0.25

    daily_units = prod.groupby("date")["units"].sum()
    daily_shift_units = prod.groupby(["date", "shift"])["units"].sum().unstack(fill_value=0)

    out = pd.DataFrame({"total_units": daily_units, "kWh": daily_kwh}).dropna()
    out = out.join(daily_shift_units, how="left").fillna(0)
    out["energy_per_unit_kwh"] = out["kWh"] / out["total_units"].replace(0, pd.NA)
    out = out.reset_index().rename(columns={"index": "date"})
    return _records(out)


@app.get("/plants/compare")
def plants_compare():
    """Per-plant kWh from rollup_daily_plant — the only genuinely plant-specific
    column there. scope1/scope2/cost on that table are whole-plant totals
    broadcast onto every plant's row (see DATABASE_AND_GENERATOR.md), so they
    are deliberately NOT included here to avoid implying a false per-plant split."""
    conn = get_conn()
    df = pd.read_sql(
        "SELECT r.plant_id, p.name as plant_name, p.city, p.division, SUM(r.kWh) as kwh_total "
        "FROM rollup_daily_plant r LEFT JOIN dim_plant p ON r.plant_id = p.plant_id "
        "GROUP BY r.plant_id ORDER BY kwh_total DESC", conn)
    conn.close()
    return _records(df)


@app.get("/assets")
def assets():
    conn = get_conn()
    df = pd.read_sql("SELECT a.*, p.name as plant_name, p.city, p.division FROM dim_asset a "
                      "LEFT JOIN dim_plant p ON a.plant_id = p.plant_id", conn)
    conn.close()
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


@app.get("/forecast/demand")
def forecast_demand():
    cached = CACHE.get("forecast")
    if cached is None:
        raise HTTPException(503, "forecast model not ready")
    test = cached["test"].tail(forecast_mod.HORIZON_STEPS).copy()
    test["ts"] = test["ts"].astype(str)
    return {
        "metrics": {
            "mape_pct": round(cached["mape"], 2),
            "wape_pct": round(cached["wape"], 2),
            "naive_climatology_wape_pct": round(cached["naive_wape"], 2),
            "contract_kva": cached["contract_kva"],
            "n_breaches_in_test_period": cached["n_breaches"],
        },
        "last_24h": _records(test[["ts", "kW", "pred_kw", "pred_kva", "breach_flag"]]),
    }


@app.get("/anomalies")
def anomalies(from_: str | None = Query(None, alias="from"), to: str | None = None, asset_id: str | None = None):
    df = CACHE.get("anomalies")
    if df is None:
        raise HTTPException(503, "anomaly cache not ready")
    out = df[df["final_flag"]].copy()
    if asset_id:
        out = out[out["asset_id"] == asset_id]
    if from_:
        out = out[out["ts"] >= from_]
    if to:
        # same end-of-day boundary issue as _date_filter_sql: a bare date must
        # cover the whole day, not just its midnight instant
        to_bound = pd.Timestamp(to) + pd.Timedelta(days=1) if len(to) == 10 else pd.Timestamp(to)
        out = out[out["ts"] < to_bound]
    out = out.sort_values("anomaly_score", ascending=False)
    out["ts"] = out["ts"].astype(str)
    out["severity"] = pd.cut(out["anomaly_score"], bins=[-float("inf"), 0, 0.1, 0.2, float("inf")],
                              labels=["low", "medium", "high", "critical"]).astype(str)
    return _records(out[["ts", "asset_id", "anomaly_score", "severity", "model_flag", "rule_flag"]])


@app.get("/anomalies/daily")
def anomalies_daily():
    """Day x asset worst-severity grid — aggregated server-side because the raw
    15-min anomaly feed is ~6MB for a full year, far too heavy for a timeline
    widget that only needs one value per (asset, day)."""
    df = CACHE.get("anomalies")
    if df is None:
        raise HTTPException(503, "anomaly cache not ready")
    out = df[df["final_flag"]].copy()
    out["date"] = out["ts"].dt.strftime("%Y-%m-%d")
    out["rank"] = pd.cut(out["anomaly_score"], bins=[-float("inf"), 0, 0.1, 0.2, float("inf")], labels=[1, 2, 3, 4]).astype(int)
    daily = out.groupby(["asset_id", "date"])["rank"].max().reset_index()
    return _records(daily)


@app.get("/recommendations")
def recommendations():
    df = CACHE.get("recommendations")
    if df is None:
        raise HTTPException(503, "recommendations.csv not found — run `python -m ml.recommendations` first")
    return _records(df.sort_values("rs_saved", ascending=False))


@app.get("/scenario/compare")
def scenario_compare():
    results = {}
    for label, path in [("baseline", BASELINE_DB), ("optimized", OPTIMIZED_DB)]:
        conn = get_conn(path)
        mm = pd.read_sql("SELECT kW, cost_rs FROM fact_main_meter", conn)
        em = pd.read_sql("SELECT scope1_tco2, scope2_tco2 FROM fact_emissions", conn)
        conn.close()
        results[label] = {
            "kWh": round(mm["kW"].sum() * 0.25, 1),
            "cost_rs": round(mm["cost_rs"].sum(), 2),
            "tco2": round((em["scope1_tco2"] + em["scope2_tco2"]).sum(), 2),
        }
    results["savings"] = {
        "kWh": round(results["baseline"]["kWh"] - results["optimized"]["kWh"], 1),
        "cost_rs": round(results["baseline"]["cost_rs"] - results["optimized"]["cost_rs"], 2),
        "tco2": round(results["baseline"]["tco2"] - results["optimized"]["tco2"], 2),
    }
    return results


def _carbon_monthly(conn):
    emissions = pd.read_sql("SELECT ts, scope1_tco2, scope2_tco2, solar_avoided_tco2 FROM fact_emissions", conn)
    fuel_events = pd.read_sql("SELECT ts, fuel_type, amount_kg FROM fact_fuel_event", conn)

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
def carbon_monthly():
    conn = get_conn()
    monthly, fuel_by_type = _carbon_monthly(conn)
    conn.close()
    return {"monthly": _records(monthly), "fuel_by_type": _records(fuel_by_type)}


@app.get("/carbon/report")
def carbon_report(format: str = "csv"):
    if format not in ("csv", "pdf"):
        raise HTTPException(400, "format must be 'csv' or 'pdf'")

    conn = get_conn()
    monthly, fuel_by_type = _carbon_monthly(conn)
    conn.close()

    if format == "csv":
        buf = io.StringIO()
        buf.write("# KPCL BRSR-style carbon report — benchmark-calibrated simulation. "
                   "VERIFY all emission factors in config.yaml before external use.\n")
        monthly.to_csv(buf, index=False)
        buf.write("\n# Scope 1 fuel breakdown by month (kg, or litres for diesel)\n")
        fuel_by_type.to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                  headers={"Content-Disposition": "attachment; filename=kpcl_carbon_report.csv"})

    return StreamingResponse(_render_carbon_pdf(monthly, fuel_by_type), media_type="application/pdf",
                              headers={"Content-Disposition": "attachment; filename=kpcl_carbon_report.pdf"})


def _render_carbon_pdf(monthly, fuel_by_type):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("KPCL Carbon Report (BRSR-style) — Benchmark-Calibrated Simulation", styles["Title"]),
        Paragraph("All figures are synthetic. Emission factors are config placeholders — VERIFY before external use.", styles["Italic"]),
        Spacer(1, 12),
        Paragraph("Monthly Scope 1 / Scope 2 / Solar-avoided (tCO2e)", styles["Heading2"]),
    ]

    monthly_rounded = monthly.round(2)
    table_data = [list(monthly_rounded.columns)] + monthly_rounded.values.tolist()
    t = Table(table_data)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 16))
    elements.append(Paragraph("Scope 1 Fuel Breakdown by Month", styles["Heading2"]))

    fuel_rounded = fuel_by_type.round(2)
    fuel_table_data = [list(fuel_rounded.columns)] + fuel_rounded.values.tolist()
    t2 = Table(fuel_table_data)
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    elements.append(t2)

    doc.build(elements)
    buf.seek(0)
    return buf
