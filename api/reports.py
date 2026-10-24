"""Detailed per-plant management report (PDF).

One document a plant manager can read in ten minutes and sign off: executive summary, energy and
cost (incl. time-of-day split), demand against contract, power factor, emissions, equipment
breakdown, losses and anomalies, the peak-shaving plan, recommended actions, data quality, and a
methodology/assumptions page with a sign-off block.

Everything is computed from the same tables the dashboard uses; nothing here is typed in by hand.
All figures come from a benchmark-calibrated simulation and say so on every page.
"""
import io
from datetime import datetime

import numpy as np
import pandas as pd
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from ml import plant_cfg
from ml.peak_shaving import STEPS_PER_DAY, tod_rate_array

BRAND = colors.HexColor("#0F3D5E")
ACCENT = colors.HexColor("#2A9D8F")
WARN = colors.HexColor("#EF6C00")
BAD = colors.HexColor("#C62828")
GREY = colors.HexColor("#F2F4F6")
LABEL = "Benchmark-calibrated simulation — synthetic data, assumed tariff and emission factors (VERIFY before external use)"

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], textColor=BRAND, fontSize=20, spaceAfter=4)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], textColor=BRAND, fontSize=13, spaceBefore=10, spaceAfter=4, keepWithNext=1)
BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontSize=9, leading=12)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=7.5, leading=9.5, textColor=colors.grey)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8, leading=10)


def _fmt_rs(v):
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e7:
        return f"{sign}Rs {a / 1e7:.2f} Cr"
    if a >= 1e5:
        return f"{sign}Rs {a / 1e5:.2f} L"
    return f"{sign}Rs {a:,.0f}"


def _table(rows, header=True, widths=None, align_right_from=1, zebra=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CFD8DC")),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    if zebra:
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), GREY))
    t.setStyle(TableStyle(style))
    return t


def _bar_chart(categories, series, names, colors_, height=150, width=480, stacked=False):
    d = Drawing(width, height + 30)
    c = VerticalBarChart()
    c.x, c.y, c.width, c.height = 40, 28, width - 60, height - 20
    c.data = series
    c.categoryAxis.categoryNames = categories
    c.categoryAxis.labels.fontSize = 7
    c.valueAxis.labels.fontSize = 7
    c.valueAxis.valueMin = 0
    c.groupSpacing = 6
    if stacked:
        c.categoryAxis.style = "stacked"
    for i, col in enumerate(colors_):
        c.bars[i].fillColor = col
        c.bars[i].strokeColor = None
    d.add(c)
    leg = Legend()
    leg.x, leg.y, leg.fontSize = 45, height + 22, 7
    leg.alignment = "right"
    leg.columnMaximum = 1
    leg.deltax = 80
    leg.colorNamePairs = list(zip(colors_, names))
    d.add(leg)
    return d


def _line_chart(xs, series, names, colors_, ref=None, height=150, width=480, xlabel="hour of day"):
    d = Drawing(width, height + 30)
    p = LinePlot()
    p.x, p.y, p.width, p.height = 40, 28, width - 60, height - 20
    p.data = [list(zip(xs, s)) for s in series]
    for i, col in enumerate(colors_):
        p.lines[i].strokeColor = col
        p.lines[i].strokeWidth = 1.4
    p.xValueAxis.labelTextFormat = "%d"
    p.xValueAxis.labels.fontSize = 7
    p.yValueAxis.labels.fontSize = 7
    p.xValueAxis.valueMin, p.xValueAxis.valueMax = min(xs), max(xs)
    p.yValueAxis.valueMin = 0
    d.add(p)
    if ref is not None:
        top = max(max(s) for s in series)
        top = max(top, ref) * 1.05
        p.yValueAxis.valueMax = top
        y = p.y + p.height * (ref / top)
        d.add(Line(p.x, y, p.x + p.width, y, strokeColor=BAD, strokeDashArray=[4, 3], strokeWidth=1))
        d.add(String(p.x + p.width - 2, y + 3, "contract", fontSize=7, fillColor=BAD, textAnchor="end"))
    leg = Legend()
    leg.x, leg.y, leg.fontSize = 45, height + 22, 7
    leg.alignment = "right"
    leg.columnMaximum = 1
    leg.deltax = 90
    leg.colorNamePairs = list(zip(colors_, names))
    d.add(leg)
    d.add(String(width / 2, 8, xlabel, fontSize=7, textAnchor="middle", fillColor=colors.grey))
    return d


def _tod_names(config):
    names = [""] * STEPS_PER_DAY
    for period in config["tariff"]["tod_periods"]:
        s = int(period["hours"][0][:2]) * 60 + int(period["hours"][0][3:])
        e = int(period["hours"][1][:2]) * 60 + int(period["hours"][1][3:])
        for i in range(STEPS_PER_DAY):
            m = i * 15
            inside = (s <= m < e) if s < e else (m >= s or m < e)
            if inside:
                names[i] = period["name"].rstrip("2")
    return np.array(names)


def _meter_frame(conn, plant):
    if plant is None:
        mm = pd.read_sql("SELECT ts, kW, kVA, pf, cost_rs FROM fact_main_meter", conn)
        em = pd.read_sql("SELECT scope1_tco2, scope2_tco2, solar_avoided_tco2 FROM fact_emissions", conn)
        df = pd.concat([mm, em], axis=1)
    else:
        df = pd.read_sql("SELECT ts, kW, kVA, pf, cost_rs, scope1_tco2, scope2_tco2, solar_avoided_tco2 "
                         "FROM fact_plant_meter WHERE plant_id = ?", conn, params=(plant,))
    df["ts"] = pd.to_datetime(df["ts"])
    df["kWh"] = df["kW"] * 0.25
    df["month"] = df["ts"].dt.strftime("%Y-%m")
    df["date"] = df["ts"].dt.strftime("%Y-%m-%d")
    df["slot"] = df["ts"].dt.hour * 4 + df["ts"].dt.minute // 15
    return df


def build_plant_report(conn, config, plant, *, plant_name, kpis, planner, leaks, excess, recs, anomalies,
                       company_kwh, company_cost, company_tco2, fuel_by_type):
    contract = plant_cfg.contract_kva(config, plant)
    df = _meter_frame(conn, plant)
    names = _tod_names(config)
    rates = tod_rate_array(config)
    df["tod"] = names[df["slot"].to_numpy()]
    df["rate"] = rates[df["slot"].to_numpy()]

    total_kwh = df["kWh"].sum()
    total_cost = df["cost_rs"].sum()
    total_tco2 = df["scope1_tco2"].sum() + df["scope2_tco2"].sum()
    over = df[df["kVA"] > contract]
    breach_days = over["date"].nunique()
    near = df[df["kVA"] > 0.85 * contract]
    low_pf = df[df["pf"] < config["tariff"].get("pf_penalty_below", 0.90)]

    daily_peak = df.groupby("date")["kVA"].max().sort_values(ascending=False)
    worst_day = daily_peak.index[0]
    plan = planner.plan(worst_day)

    monthly = df.groupby("month").agg(kWh=("kWh", "sum"), cost=("cost_rs", "sum"), kva=("kVA", "max"),
                                      s1=("scope1_tco2", "sum"), s2=("scope2_tco2", "sum"),
                                      solar=("solar_avoided_tco2", "sum")).reset_index()

    # ---- findings (auto-written) ----
    top_rec = recs.sort_values("rs_saved", ascending=False).iloc[0] if recs is not None and len(recs) else None
    findings = [
        f"Consumed <b>{total_kwh / 1000:,.0f} MWh</b> costing <b>{_fmt_rs(total_cost)}</b>"
        f" ({total_kwh / company_kwh * 100:.0f}% of company energy, {total_cost / company_cost * 100:.0f}% of company cost).",
        f"Emitted <b>{total_tco2:,.0f} tCO2e</b> (Scope 1: {df['scope1_tco2'].sum():,.0f}, Scope 2: {df['scope2_tco2'].sum():,.0f}); "
        f"solar credit avoided {df['solar_avoided_tco2'].sum():,.0f} tCO2e.",
    ]
    if breach_days:
        findings.append(f"<font color='#C62828'><b>Contract demand of {contract:.0f} kVA was exceeded on {breach_days} day(s)</b></font> "
                        f"(peak {df['kVA'].max():.0f} kVA, {df['kVA'].max() / contract * 100:.0f}% of contract).")
    else:
        findings.append(f"Peak demand {df['kVA'].max():.0f} kVA stayed within the {contract:.0f} kVA contract "
                        f"({df['kVA'].max() / contract * 100:.0f}% utilisation).")
    if len(leaks) and leaks["avoidable_rs"].sum() > 0:
        findings.append(f"Compressed-air leaks above the background floor wasted about <b>{_fmt_rs(leaks['avoidable_rs'].sum())}</b> "
                        f"({leaks['avoidable_kwh'].sum() / 1000:,.0f} MWh).")
    if top_rec is not None and top_rec["rs_saved"] > 0:
        findings.append(f"Largest single saving opportunity: <b>{top_rec['action']}</b> — about {_fmt_rs(top_rec['rs_saved'])}/yr "
                        f"and {top_rec['tco2_saved']:.1f} tCO2e/yr.")
    if plan and plan["actions"]:
        findings.append(f"On the highest-demand day ({worst_day}) rescheduling loads would cut the peak from "
                        f"{plan['peak_before_kva']:.0f} to {plan['peak_after_kva']:.0f} kVA.")

    # ---- document ----
    buf = io.BytesIO()
    generated = datetime.now().strftime("%d %b %Y %H:%M")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 9 * mm, f"KPCL Energy Ops · {plant_name} · {LABEL}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=f"KPCL Plant Report — {plant_name}")
    W = A4[0] - 30 * mm
    el = []

    el += [Paragraph(f"Plant Energy &amp; Carbon Report", H1),
           Paragraph(f"<b>{plant_name}</b> · reporting period {df['ts'].min():%d %b %Y} – {df['ts'].max():%d %b %Y} · generated {generated}", BODY),
           Paragraph(LABEL, SMALL), Spacer(1, 6)]

    # 1. summary
    el.append(Paragraph("1. Executive summary", H2))
    for f in findings:
        el.append(Paragraph("• " + f, BODY))
    el.append(Spacer(1, 6))
    kpi_rows = [
        ["Indicator", "Value", "Note"],
        ["Energy consumed", f"{total_kwh / 1000:,.1f} MWh", "grid + allocated solar self-use"],
        ["Energy cost", _fmt_rs(total_cost), f"avg Rs {total_cost / total_kwh:.2f}/kWh (ToD weighted)"],
        ["Peak demand", f"{df['kVA'].max():.0f} kVA", f"contract {contract:.0f} kVA"],
        ["Contract utilisation", f"{df['kVA'].max() / contract * 100:.0f}%", f"{len(near) / len(df) * 100:.1f}% of intervals above 85%"],
        ["Average power factor", f"{df['pf'].mean():.3f}", f"{len(low_pf) / len(df) * 100:.1f}% of intervals below {config['tariff']['pf_penalty_below']}"],
        ["Scope 1 emissions", f"{df['scope1_tco2'].sum():,.1f} tCO2e", "fuel + refrigerant + diesel"],
        ["Scope 2 emissions", f"{df['scope2_tco2'].sum():,.1f} tCO2e", "grid electricity"],
        ["Carbon intensity", f"{total_tco2 / (total_kwh / 1000):.2f} tCO2e/MWh", "Scope 1 + 2 per MWh"],
        ["Energy per unit produced", f"{kpis['energy_intensity_kwh_per_unit']:.1f} kWh/unit" if kpis.get("energy_intensity_kwh_per_unit") else "n/a",
         "no production records" if not kpis.get("energy_intensity_kwh_per_unit") else "total energy / units"],
    ]
    el.append(_table(kpi_rows, widths=[W * .30, W * .25, W * .45], align_right_from=1))

    # 2. energy & cost
    el.append(Paragraph("2. Energy and cost", H2))
    cats = [m[5:] for m in monthly["month"]]
    el.append(_bar_chart(cats, [list(monthly["kWh"] / 1000)], ["Energy (MWh)"], [BRAND]))
    tod = df.groupby("tod").agg(kWh=("kWh", "sum"), cost=("cost_rs", "sum")).reset_index()
    tod["share"] = tod["kWh"] / tod["kWh"].sum() * 100
    tod["rate"] = tod["cost"] / tod["kWh"]
    order = {"off_peak": 0, "normal": 1, "peak": 2}
    tod = tod.sort_values("tod", key=lambda s: s.map(order))
    el.append(Paragraph("Time-of-day split — moving load from <i>peak</i> to <i>off-peak</i> lowers cost without changing kWh.", BODY))
    el.append(_table([["Period", "Energy (MWh)", "Share of kWh", "Cost", "Avg Rs/kWh"]] +
                     [[r.tod.replace("_", "-"), f"{r.kWh / 1000:,.1f}", f"{r.share:.0f}%", _fmt_rs(r.cost), f"{r.rate:.2f}"] for r in tod.itertuples()],
                     widths=[W * .2, W * .2, W * .2, W * .2, W * .2]))
    el.append(Spacer(1, 4))
    el.append(KeepTogether(_table([["Month", "MWh", "Cost", "Peak kVA", "tCO2e"]] +
                     [[r.month, f"{r.kWh / 1000:,.1f}", _fmt_rs(r.cost), f"{r.kva:.0f}", f"{r.s1 + r.s2:.1f}"] for r in monthly.itertuples()],
                     widths=[W * .2, W * .2, W * .2, W * .2, W * .2])))

    # 3. demand & contract
    el.append(Paragraph("3. Demand against contract", H2))
    wk = df[df["ts"].dt.dayofweek < 5]
    hourly = wk.groupby(wk["ts"].dt.hour)["kVA"].agg(["mean", "max"])
    el.append(Paragraph("Weekday load profile — average and maximum apparent power by hour, against contract demand.", BODY))
    el.append(_line_chart(list(hourly.index), [list(hourly["mean"]), list(hourly["max"])], ["Average kVA", "Maximum kVA"],
                          [BRAND, WARN], ref=contract))
    top5 = daily_peak.head(5)
    el.append(Paragraph("Five highest-demand days", BODY))
    rows = [["Date", "Peak kVA", "% of contract", "Status"]]
    for d, v in top5.items():
        rows.append([d, f"{v:.0f}", f"{v / contract * 100:.0f}%", "BREACH" if v > contract else ("near limit" if v > .85 * contract else "ok")])
    t = _table(rows, widths=[W * .25, W * .25, W * .25, W * .25])
    el.append(t)
    el.append(Paragraph(f"Intervals above contract: {len(over)} ({len(over) / len(df) * 100:.2f}% of the year). "
                        f"Demand charge exposure per kVA above contract is assumed at Rs {config['tariff']['demand_charge_rs_per_kva']}/kVA/month.", BODY))

    if plan:
        el.append(Paragraph(f"Peak-shaving plan for {worst_day} ({plan['source']})", H2))
        el.append(Paragraph(f"Peak {plan['peak_before_kva']:.0f} kVA at {plan['peak_time']} → {plan['peak_after_kva']:.0f} kVA after the plan "
                            f"({'breach avoided' if plan['breach_before'] and not plan['breach_after'] else 'within limits' if not plan['breach_before'] else 'still above contract'}). "
                            f"Demand-charge exposure avoided {_fmt_rs(plan['demand_charge_at_stake_rs'])}, ToD energy effect {_fmt_rs(plan['tod_energy_saving_rs'])} for the day.", BODY))
        if plan["actions"]:
            el.append(_table([["Action", "kVA cut", "ToD effect"]] +
                             [[Paragraph(a["message"], CELL), f"{a['kva_reduction']:.0f}", _fmt_rs(a["tod_energy_saving_rs"])] for a in plan["actions"]],
                             widths=[W * .64, W * .16, W * .20]))
        else:
            el.append(Paragraph("No schedulable load at this plant can usefully be moved on that day.", BODY))

    # 4. emissions
    el.append(Paragraph("4. Emissions (Scope 1 and Scope 2)", H2))
    el.append(_bar_chart(cats, [list(monthly["s1"]), list(monthly["s2"])], ["Scope 1", "Scope 2"], [WARN, BRAND], stacked=True))
    if fuel_by_type is not None and len(fuel_by_type):
        cols = [c for c in fuel_by_type.columns if c != "month"]
        tot = fuel_by_type[cols].sum()
        tot = tot[tot > 0]
        if len(tot):
            el.append(Paragraph("Scope 1 fuel use (kg; diesel in litres)", BODY))
            el.append(_table([["Fuel"] + [c for c in tot.index], ["Annual quantity"] + [f"{v:,.0f}" for v in tot.values]]))
    ef = config["emission_factors"]["grid_tco2_per_mwh"]
    el.append(Paragraph(f"Scope 2 uses a grid factor of {ef['value']} tCO2/MWh ({str(ef['source']).replace(chr(226)+chr(8364)+chr(8221), '-')}). Solar credit avoided "
                        f"{df['solar_avoided_tco2'].sum():,.1f} tCO2e (shared across plants by load share).", SMALL))

    # 5. equipment
    el.append(Paragraph("5. Equipment energy breakdown", H2))
    ids = sorted(plant_cfg.assets_of(config, plant) - {"SOLAR-SASWAD-01"})
    meter = pd.read_sql("SELECT asset_id, kW, kWh, dq_flag FROM fact_meter", conn)
    meter = meter[meter["asset_id"].isin(ids)]
    by_asset = meter.groupby("asset_id").agg(kwh=("kWh", "sum"), avg=("kW", "mean"), mx=("kW", "max"),
                                             missing=("kW", lambda s: s.isna().mean() * 100)).reset_index()
    flagged = anomalies[anomalies["final_flag"]].groupby("asset_id").size() / anomalies.groupby("asset_id").size() * 100
    by_asset["flag"] = by_asset["asset_id"].map(flagged).fillna(0.0)
    by_asset["share"] = by_asset["kwh"] / by_asset["kwh"].sum() * 100
    by_asset = by_asset.sort_values("kwh", ascending=False)
    el.append(_table([["Asset", "Energy (MWh)", "Share", "Avg kW", "Max kW", "Flagged intervals", "Missing data"]] +
                     [[r.asset_id, f"{r.kwh / 1000:,.1f}", f"{r.share:.0f}%", f"{r.avg:.1f}", f"{r.mx:.0f}", f"{r.flag:.0f}%", f"{r.missing:.1f}%"]
                      for r in by_asset.itertuples()], widths=[W * .26, W * .14, W * .10, W * .12, W * .12, W * .14, W * .12]))
    el.append(Paragraph("Metered asset energy excludes unmetered losses (5–8% of load) and the solar offset, so it will not match the plant total exactly.", SMALL))

    # 6. losses
    el.append(Paragraph("6. Losses and anomalies", H2))
    if len(leaks):
        el.append(Paragraph("Compressed-air leaks — energy above each compressor's background floor", BODY))
        el.append(_table([["Compressor", "Floor m3/min", "Avoidable MWh", "Cost", "tCO2e"]] +
                         [[r.asset_id, f"{r.leak_floor_m3min:.1f}", f"{r.avoidable_kwh / 1000:,.1f}", _fmt_rs(r.avoidable_rs), f"{r.avoidable_tco2:.1f}"]
                          for r in leaks.itertuples()], widths=[W * .26, W * .16, W * .2, W * .22, W * .16]))
    if len(excess):
        el.append(Spacer(1, 4))
        el.append(Paragraph("Draw above normal on intervals flagged by the anomaly detector", BODY))
        el.append(_table([["Asset", "Flagged intervals", "Excess MWh", "Cost", "tCO2e"]] +
                         [[r.asset_id, f"{int(r.flagged_intervals)}", f"{r.excess_kwh / 1000:,.1f}", _fmt_rs(r.excess_rs), f"{r.excess_tco2:.1f}"]
                          for r in excess.itertuples()], widths=[W * .26, W * .18, W * .18, W * .22, W * .16]))
    el.append(Paragraph("Leak and anomaly figures overlap (a leak raises compressor draw) — do not add them together.", SMALL))

    # 7. recommendations
    el.append(Paragraph("7. Recommended actions", H2))
    if recs is not None and len(recs):
        r2 = recs.sort_values("rs_saved", ascending=False)
        el.append(_table([["#", "Action", "kWh/yr", "Rs/yr", "tCO2e/yr"]] +
                         [[str(i + 1), Paragraph(r.action, CELL), f"{r.kWh_saved:,.0f}", _fmt_rs(r.rs_saved), f"{r.tco2_saved:.1f}"]
                          for i, r in enumerate(r2.itertuples())], widths=[W * .06, W * .50, W * .14, W * .18, W * .12], align_right_from=2))
        el.append(Paragraph("Each saving is a full-year baseline-versus-counterfactual simulation diff. Negative rows are real trade-offs "
                            "(for example switching the chiller lead unit moves emissions from gas to grid electricity).", SMALL))
    else:
        el.append(Paragraph("No simulated actions apply to this plant's equipment.", BODY))

    # 8. data quality, method, sign-off
    el.append(Paragraph("8. Data quality", H2))
    miss = meter["kW"].isna().mean() * 100
    el.append(Paragraph(f"Asset meters: {miss:.1f}% of readings missing or dropped; some sensors freeze for 1–4 hours and one meter drifts "
                        f"(injected on purpose so the analytics are tested against realistic data). Plant totals come from the main meter and are unaffected.", BODY))

    el.append(Paragraph("9. Method and assumptions", H2))
    for line in [
        "All data is synthetic, generated from a physics-based plant simulation at 1-minute resolution and aggregated to 15 minutes.",
        "Plant figures are an allocation of the single company meter: load, cost and Scope 2 follow each plant's share of metered asset load; "
        "Scope 1 follows asset ownership; the solar credit is shared in proportion to load (virtual net-metering).",
        "Tariff: illustrative time-of-day rates and an assumed demand charge — not an official tariff order. Contract demand per plant is assumed.",
        "Emission factors are placeholders (CEA grid average, IPCC fuels, AR5 GWP) and must be verified before any external or BRSR disclosure.",
        "Anomalies: Isolation Forest per asset plus physics rules. Forecast: LightGBM day-ahead model; accuracy is limited by day-to-day randomness in the simulated plant.",
        "Peak-shaving plans shift a load's whole daily profile in time without changing its energy; CO2 is therefore unchanged by scheduling.",
    ]:
        el.append(Paragraph("• " + line, BODY))

    el.append(Spacer(1, 16))
    sign = Table([["Prepared by", "Reviewed by (Plant Manager)", "Approved by (Energy Head)"],
                  ["\n\n\n", "\n\n\n", "\n\n\n"], ["Name / date", "Name / date", "Name / date"]], colWidths=[W / 3] * 3)
    sign.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                              ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey), ("TEXTCOLOR", (0, 2), (-1, 2), colors.grey),
                              ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
    el.append(KeepTogether([Paragraph("10. Sign-off", H2), sign]))

    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf
