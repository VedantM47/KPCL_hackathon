"""Stage 7: day-ahead plant load forecast, built for what it is used for — daily peaks and
contract-breach risk — with honest walk-forward evaluation.

How it works
- Walk-forward (rolling origin): on the 1st of every month from March, models are retrained on
  everything before that month and forecast each day of the month 24 h ahead. Every day from March
  on therefore has a genuine forecast made only from the past. January-February have too little
  history and are reported as "no forecast", never back-filled with actuals.
- Day-ahead discipline: features are calendar, planned production, weather (actual weather used as a
  stand-in for a weather forecast; ``weather_noise_c`` simulates forecast error), and lags of exactly
  1 day / 1 week. Nothing from the target day itself.
- Level-relative target: load is predicted as a multiple of the trailing 7-day mean (known at the
  forecast origin), so slow drift such as Nashik's growing compressor leak is followed instead of
  extrapolated badly by the trees.
- Interval model: a mean model for the central line (so daily energy adds up) plus LightGBM quantile
  models for a P10-P90 band. A median is the wrong centre here: CNC load is bursty, so the median of an
  interval sits well below its mean and summed energy comes out far too low.
- Calibration: each month's band (and peak quantiles) are widened by conformalised quantile regression
  using the errors of the *earlier* walk-forward months only, so ~80% coverage holds out of sample.
- Daily-peak model: a separate day-level quantile model for the day's maximum kVA (P10/P50/P90/P95).
  The generator randomises *when* CNC and paint-booth load runs each day, so the 15-minute shape is
  largely unpredictable and a mean forecast smears the peak away; the size of the peak is
  predictable. Breach risk = P(peak > contract) read off those quantiles.
- kVA = kW / power-factor climatology for the slot (from training data), never the actual pf.

Usage: python -m ml.forecast
"""
import sqlite3

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

from ml import plant_cfg

DB_PATH = "kpcl_energy.db"
HORIZON_STEPS = 96          # 24h at 15-min resolution
LAG_DAY_STEPS = 96          # t-24h
LAG_WEEK_STEPS = 96 * 7     # t-7d
MIN_HISTORY_DAYS = 49       # first origin needs 7 weeks of history -> first forecast 1 March
QUANTILES = (0.1, 0.9)
BAND_TARGET = 0.8           # P10-P90 should contain 80% of outcomes
PEAK_QUANTILES = (0.1, 0.5, 0.9, 0.95)
NEAR_CONTRACT = 0.85
WARN_RISK = 0.3             # a day is "flagged" when the forecast puts >= 30% on the condition

INTERVAL_FEATURES = ["slot", "dow", "day_type", "is_holiday", "is_maintenance", "in_shift_a", "in_shift_b",
                     "planned_units", "ambient_temp_c", "wet_bulb_c", "lag1_rel", "lag7_rel", "clim_rel"]
PEAK_FEATURES = ["dow", "day_type", "is_holiday", "is_maintenance", "planned_units", "max_ambient_c",
                 "max_wet_bulb_c", "peak_lag1_rel", "peak_lag7_rel", "load_factor_lvl", "clim_peak_rel"]


def load_frame(conn, plant_id=None):
    plant_id = plant_cfg.norm(plant_id)
    if plant_id is None:
        mm = pd.read_sql("SELECT ts, kW, kVA, pf FROM fact_main_meter", conn)
    else:
        mm = pd.read_sql("SELECT ts, kW, kVA, pf FROM fact_plant_meter WHERE plant_id = ?", conn, params=(plant_id,))
    mm["ts"] = pd.to_datetime(mm["ts"])
    mm = mm.sort_values("ts").reset_index(drop=True)

    wx = pd.read_sql("SELECT ts, ambient_temp_c, wet_bulb_c FROM fact_weather", conn)
    wx["ts"] = pd.to_datetime(wx["ts"])

    if plant_id is None:
        prod = pd.read_sql("SELECT date, shift, units, is_surge FROM fact_production", conn)
    else:
        prod = pd.read_sql("SELECT date, shift, units, is_surge FROM fact_production WHERE plant_id = ?",
                           conn, params=(plant_id,))
    daily_units = prod.groupby("date")["units"].sum().rename("planned_units")
    daily_units.index = pd.to_datetime(daily_units.index)

    df = mm.merge(wx, on="ts", how="left")
    df["date"] = df["ts"].dt.normalize()
    df = df.merge(daily_units, left_on="date", right_index=True, how="left")
    df["planned_units"] = pd.to_numeric(df["planned_units"]).fillna(0.0)
    return df


def build_features(df, config, weather_noise_c=0.0, seed=0):
    """Interval-level features. Everything is known at the end of the day before the target day."""
    df = df.copy()
    df["slot"] = df["ts"].dt.hour * 4 + df["ts"].dt.minute // 15
    minute = df["slot"] * 15
    df["dow"] = df["ts"].dt.dayofweek

    holidays = {h["date"] for h in config["calendar"]["holidays_2025"]}
    maint = {m["date"] for m in config["calendar"]["planned_maintenance_days"]}
    date_str = df["ts"].dt.strftime("%Y-%m-%d")
    df["is_holiday"] = date_str.isin(holidays).astype(int)
    df["is_maintenance"] = date_str.isin(maint).astype(int)
    day_off = df["is_holiday"].astype(bool) | df["is_maintenance"].astype(bool) | (df["dow"] == 6)
    saturday = (df["dow"] == 5) & ~day_off
    # 0 = day off, 1 = Saturday half-day, 2 = full production day
    df["day_type"] = np.where(day_off, 0, np.where(saturday, 1, 2))
    df["in_shift_a"] = (~day_off & (minute >= 6 * 60) & (minute < 14 * 60)).astype(int)
    df["in_shift_b"] = (~day_off & ~saturday & (minute >= 14 * 60) & (minute < 22 * 60)).astype(int)

    if weather_noise_c:
        # a weather forecast is wrong by a roughly constant offset over a day, plus a little jitter
        rng = np.random.default_rng(seed)
        days = df["date"].factorize()[0]
        offset = rng.normal(0, weather_noise_c, days.max() + 1)[days]
        for col in ("ambient_temp_c", "wet_bulb_c"):
            df[col] = df[col] + offset + rng.normal(0, weather_noise_c / 3, len(df))

    # level known at the forecast origin: trailing 7-day mean, ending the day before the target
    daily = df.groupby("date").agg(day_kw=("kW", "mean"), day_peak=("kVA", "max"))
    daily["level_kw"] = daily["day_kw"].rolling(7, min_periods=5).mean().shift(1).clip(lower=1.0)
    daily["peak_level"] = daily["day_peak"].rolling(7, min_periods=5).mean().shift(1).clip(lower=1.0)
    df = df.merge(daily[["level_kw", "peak_level"]], left_on="date", right_index=True, how="left")

    df["rel"] = df["kW"] / df["level_kw"]
    df["lag1_rel"] = df["kW"].shift(LAG_DAY_STEPS) / df["level_kw"]
    df["lag7_rel"] = df["kW"].shift(LAG_WEEK_STEPS) / df["level_kw"]
    df["lag7_kw"] = df["kW"].shift(LAG_WEEK_STEPS)   # seasonal-naive baseline
    return df


def build_day_frame(df):
    """One row per day for the daily-peak model."""
    d = df.groupby("date").agg(
        dow=("dow", "first"), day_type=("day_type", "first"), is_holiday=("is_holiday", "first"),
        is_maintenance=("is_maintenance", "first"), planned_units=("planned_units", "first"),
        max_ambient_c=("ambient_temp_c", "max"), max_wet_bulb_c=("wet_bulb_c", "max"),
        level_kw=("level_kw", "first"), peak_level=("peak_level", "first"),
        peak_kva=("kVA", "max"), energy_kwh=("kW", lambda s: s.sum() * 0.25),
    )
    d["peak_lag1"] = d["peak_kva"].shift(1)
    d["peak_lag7"] = d["peak_kva"].shift(7)
    d["peak_lag1_rel"] = d["peak_lag1"] / d["peak_level"]
    d["peak_lag7_rel"] = d["peak_lag7"] / d["peak_level"]
    d["load_factor_lvl"] = d["level_kw"] / d["peak_level"]
    d["peak_rel"] = d["peak_kva"] / d["peak_level"]
    return d


def exceed_prob(q, alphas, threshold):
    """P(X > threshold) from predicted quantiles q (n x k, sorted) at levels alphas, by linear
    interpolation of the CDF, with linear tails continued from the outermost quantile pairs."""
    q = np.asarray(q, float)
    a = np.asarray(alphas, float)
    thr = np.broadcast_to(np.asarray(threshold, float), (q.shape[0],))
    cdf = np.empty(q.shape[0])
    for i in range(q.shape[0]):
        qi, t = q[i], thr[i]
        if t <= qi[0]:
            slope = (a[1] - a[0]) / max(qi[1] - qi[0], 1e-9)
            cdf[i] = a[0] - (qi[0] - t) * slope
        elif t >= qi[-1]:
            slope = (a[-1] - a[-2]) / max(qi[-1] - qi[-2], 1e-9)
            cdf[i] = a[-1] + (t - qi[-1]) * slope
        else:
            cdf[i] = np.interp(t, qi, a)
    return 1.0 - np.clip(cdf, 0.0, 1.0)


def _quantile_models(X, y, alphas, **params):
    models = {}
    for a in alphas:
        m = lgb.LGBMRegressor(objective="quantile", alpha=a, random_state=42, verbose=-1, **params)
        m.fit(X, y)
        models[a] = m
    return models


def _predict_sorted(models, X):
    p = np.column_stack([models[a].predict(X) for a in sorted(models)])
    return np.sort(p, axis=1)   # quantile crossing guard


def month_origins(df, origins=None):
    if origins is not None:
        return [pd.Timestamp(o) for o in origins]
    first = df["date"].min() + pd.Timedelta(days=MIN_HISTORY_DAYS)
    start = first if first.day == 1 else (first + pd.offsets.MonthBegin(1))
    end = df["date"].max()
    return list(pd.date_range(start.normalize(), end, freq="MS"))


def _cqr_margin(scores, target=BAND_TARGET):
    """Conformalised quantile regression: how far to widen a band so it covers ``target`` of the
    earlier out-of-sample outcomes (scores = how far each outcome fell outside its band)."""
    if len(scores) < 20:
        return 0.0
    n = len(scores)
    return max(0.0, float(np.quantile(scores, min(1.0, target * (n + 1) / n))))


def _fold(df, days, origin, until, contract, calib):
    """Train on everything before origin, forecast days in [origin, until). ``calib`` carries the
    band-miss scores of earlier folds; this fold's scores are appended after it is evaluated."""
    hist = df[(df["ts"] < origin)].dropna(subset=["rel", "lag1_rel", "lag7_rel", "level_kw"])
    target = df[(df["ts"] >= origin) & (df["ts"] < until)].copy()
    clim = hist.groupby(["slot", "day_type"]).agg(clim_rel=("rel", "mean"), clim_kw=("kW", "mean"),
                                                  pf_clim=("pf", "mean")).reset_index()
    hist = hist.merge(clim, on=["slot", "day_type"], how="left")
    target = target.merge(clim, on=["slot", "day_type"], how="left")
    target["pf_clim"] = target["pf_clim"].fillna(hist["pf"].mean()).clip(0.80, 0.99)
    target["clim_rel"] = target["clim_rel"].fillna(hist["rel"].mean())

    params = dict(n_estimators=120, learning_rate=0.06, num_leaves=31, min_child_samples=40)
    Xh, Xt = hist[INTERVAL_FEATURES], target[INTERVAL_FEATURES].fillna(0.0)
    mean_model = lgb.LGBMRegressor(random_state=42, verbose=-1, **params).fit(Xh, hist["rel"])
    iv_models = _quantile_models(Xh, hist["rel"], QUANTILES, **params)
    mean_rel = mean_model.predict(Xt)
    band = _predict_sorted(iv_models, Xt)
    m = _cqr_margin(calib["interval"])
    lo = np.minimum(band[:, 0] - m, mean_rel)
    hi = np.maximum(band[:, 1] + m, mean_rel)
    lvl = target["level_kw"].to_numpy()
    target["pred_kw"] = np.clip(mean_rel * lvl, 0.0, None)
    target["p10_kw"] = np.clip(lo * lvl, 0.0, None)
    target["p90_kw"] = np.clip(hi * lvl, 0.0, None)
    actual_rel = target["rel"].to_numpy()
    ok = ~np.isnan(actual_rel)
    calib["interval_next"] = np.maximum(band[ok, 0] - actual_rel[ok], actual_rel[ok] - band[ok, 1]).tolist()
    target["pred_kva"] = target["pred_kw"] / target["pf_clim"]
    target["p10_kva"] = target["p10_kw"] / target["pf_clim"]
    target["p90_kva"] = target["p90_kw"] / target["pf_clim"]

    # daily peak
    dh = days[(days.index < origin)].dropna(subset=["peak_rel", "peak_lag1_rel", "peak_lag7_rel", "peak_level"])
    dt = days[(days.index >= origin) & (days.index < until)].copy()
    clim_peak = dh.groupby("day_type")["peak_rel"].mean()
    dh = dh.assign(clim_peak_rel=dh["day_type"].map(clim_peak))
    dt["clim_peak_rel"] = dt["day_type"].map(clim_peak).fillna(dh["peak_rel"].mean())
    pk_models = _quantile_models(dh[PEAK_FEATURES], dh["peak_rel"], PEAK_QUANTILES,
                                 n_estimators=120, learning_rate=0.05, num_leaves=7, min_child_samples=8)
    raw = _predict_sorted(pk_models, dt[PEAK_FEATURES].fillna(0.0))
    # widen the outer quantiles by the earlier months' misses of the P10-P90 range (P50 unchanged)
    m = _cqr_margin(calib["peak"])
    adj = raw.copy()
    adj[:, 0] -= m
    adj[:, 2:] += m
    pq = adj * dt["peak_level"].to_numpy()[:, None]
    pr = dt["peak_rel"].to_numpy()
    okp = ~np.isnan(pr)
    calib["peak_next"] = np.maximum(raw[okp, 0] - pr[okp], pr[okp] - raw[okp, 2]).tolist()
    for j, a in enumerate(PEAK_QUANTILES):
        dt[f"peak_p{int(a * 100)}_kva"] = pq[:, j]
    dt["breach_risk"] = exceed_prob(pq, PEAK_QUANTILES, contract)
    dt["near_risk"] = exceed_prob(pq, PEAK_QUANTILES, NEAR_CONTRACT * contract)
    # baselines for the evaluation
    dt["peak_clim_kva"] = dt["day_type"].map(dh.groupby("day_type")["peak_kva"].mean())
    imp = pd.Series(mean_model.feature_importances_, index=INTERVAL_FEATURES)
    return target, dt, imp


def _metrics(iv, dd, contract):
    """Evaluation of the walk-forward forecasts against two simple baselines."""
    iv = iv.dropna(subset=["kW"])
    act = iv["kW"].to_numpy()
    wape = lambda pred: float(np.abs(act - pred).sum() / act.sum() * 100)
    lw = iv["lag7_kw"].fillna(iv["clim_kw"]).to_numpy()
    day_e = iv.groupby("date").agg(a=("kW", "sum"), p=("pred_kw", "sum"))
    dd = dd.dropna(subset=["peak_kva"])
    peak = dd["peak_kva"].to_numpy()

    def peak_stats(pred):
        err = pred - peak
        return round(float(np.abs(err).mean()), 1), round(float(err.mean()), 1)

    def flags(actual_hit, pred_hit):
        tp = int((actual_hit & pred_hit).sum())
        return {"actual_days": int(actual_hit.sum()), "flagged_days": int(pred_hit.sum()), "caught": tp,
                "recall": round(tp / actual_hit.sum(), 3) if actual_hit.sum() else None,
                "precision": round(tp / pred_hit.sum(), 3) if pred_hit.sum() else None}

    near_act, br_act = peak > NEAR_CONTRACT * contract, peak > contract
    lw_peak = dd["peak_lag7"].fillna(dd["peak_clim_kva"]).to_numpy()
    m_mae, m_bias = peak_stats(dd["peak_p50_kva"].to_numpy())
    lw_mae, lw_bias = peak_stats(lw_peak)
    c_mae, c_bias = peak_stats(dd["peak_clim_kva"].to_numpy())
    return {
        "days": int(len(dd)),
        "interval_wape_pct": round(wape(iv["pred_kw"].to_numpy()), 1),
        "interval_wape_climatology_pct": round(wape(iv["clim_kw"].fillna(0).to_numpy()), 1),
        "interval_wape_last_week_pct": round(wape(lw), 1),
        "daily_energy_error_pct": round(float(np.abs(day_e.p - day_e.a).sum() / day_e.a.sum() * 100), 1),
        "band_coverage_p10_p90": round(float(((act >= iv["p10_kw"]) & (act <= iv["p90_kw"])).mean()), 3),
        "peak_mae_kva": m_mae, "peak_bias_kva": m_bias,
        "peak_mae_last_week_kva": lw_mae, "peak_bias_last_week_kva": lw_bias,
        "peak_mae_climatology_kva": c_mae, "peak_bias_climatology_kva": c_bias,
        "peak_band_coverage_p10_p90": round(float(((peak >= dd["peak_p10_kva"]) & (peak <= dd["peak_p90_kva"])).mean()), 3),
        "near_contract": {**flags(near_act, dd["near_risk"].to_numpy() >= WARN_RISK),
                          "last_week_baseline": flags(near_act, lw_peak > NEAR_CONTRACT * contract)},
        "breach": {**flags(br_act, dd["breach_risk"].to_numpy() >= WARN_RISK),
                   "last_week_baseline": flags(br_act, lw_peak > contract)},
        "warn_threshold": WARN_RISK,
    }


def run_forecast(config, conn, plant_id=None, *, frame=None, origins=None, weather_noise_c=0.0):
    """Walk-forward day-ahead forecasts for one plant (or the company).

    Returns interval forecasts ("intervals", also "test" for older callers), per-day peak/risk
    forecasts ("days") and evaluation metrics. ``frame`` (a load_frame result) and ``origins``
    exist for tests."""
    contract = plant_cfg.contract_kva(config, plant_id)
    df = load_frame(conn, plant_id) if frame is None else frame
    df = build_features(df, config, weather_noise_c=weather_noise_c)
    days = build_day_frame(df)

    starts = month_origins(df, origins)
    parts, dparts, imps = [], [], []
    calib = {"interval": [], "peak": []}
    for o in starts:
        iv, dt, imp = _fold(df, days, o, o + pd.offsets.MonthBegin(1), contract, calib)
        # only now, after the month is over, do its errors join the calibration set
        calib["interval"] += calib.pop("interval_next")
        calib["peak"] += calib.pop("peak_next")
        parts.append(iv)
        dparts.append(dt)
        imps.append(imp)
    iv = pd.concat(parts, ignore_index=True)
    dd = pd.concat(dparts)
    iv["breach_flag"] = iv["date"].map(dd["breach_risk"]) >= WARN_RISK

    metrics = _metrics(iv, dd, contract)
    late = pd.Timestamp("2025-10-08")   # the old model's test window, for a like-for-like comparison
    metrics_late = _metrics(iv[iv["ts"] >= late], dd[dd.index >= late], contract) if (iv["ts"] >= late).any() else None

    keep_iv = ["ts", "date", "kW", "kVA", "pred_kw", "p10_kw", "p90_kw", "pred_kva", "p10_kva", "p90_kva", "breach_flag"]
    dd_out = dd[["day_type", "peak_kva", "peak_p10_kva", "peak_p50_kva", "peak_p90_kva", "peak_p95_kva",
                 "breach_risk", "near_risk"]].copy()
    intervals = iv[keep_iv].reset_index(drop=True)
    act = intervals.dropna(subset=["kW"])
    return {
        "intervals": intervals, "test": intervals, "days": dd_out,
        "metrics": metrics, "metrics_oct_dec": metrics_late,
        "first_forecast_date": starts[0].date().isoformat(), "cutoff": starts[0],
        "contract_kva": contract,
        "importances": pd.concat(imps, axis=1).mean(axis=1).sort_values(ascending=False),
        # older summary fields kept for existing callers
        "wape": metrics["interval_wape_pct"], "naive_wape": metrics["interval_wape_climatology_pct"],
        "mape": float(np.mean(np.abs(act["kW"] - act["pred_kw"]) / np.maximum(act["kW"], 1.0)) * 100),
        "n_breaches": int((dd["breach_risk"] >= WARN_RISK).sum()),
    }


def _print_metrics(name, m):
    nc, br = m["near_contract"], m["breach"]
    print(f"  {name}: {m['days']} days | interval WAPE {m['interval_wape_pct']}% "
          f"(climatology {m['interval_wape_climatology_pct']}%, last week {m['interval_wape_last_week_pct']}%) | "
          f"daily energy err {m['daily_energy_error_pct']}% | band coverage {m['band_coverage_p10_p90']:.0%}")
    print(f"    daily peak MAE {m['peak_mae_kva']} kVA, bias {m['peak_bias_kva']:+} "
          f"(last week {m['peak_mae_last_week_kva']}/{m['peak_bias_last_week_kva']:+}, "
          f"climatology {m['peak_mae_climatology_kva']}/{m['peak_bias_climatology_kva']:+}) | "
          f"peak band coverage {m['peak_band_coverage_p10_p90']:.0%}")
    for label, f in (("near-contract days", nc), ("breach days", br)):
        b = f["last_week_baseline"]
        print(f"    {label}: caught {f['caught']}/{f['actual_days']} with {f['flagged_days']} flagged "
              f"(last-week baseline {b['caught']}/{b['actual_days']} with {b['flagged_days']} flagged)")


def main():
    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    conn = sqlite3.connect(DB_PATH)
    for plant in [plant_cfg.ALL] + plant_cfg.plant_ids(config):
        r = run_forecast(config, conn, plant)
        print(f"\n{plant} (contract {r['contract_kva']:.0f} kVA, walk-forward from {r['first_forecast_date']})")
        _print_metrics("full walk-forward", r["metrics"])
        if r["metrics_oct_dec"]:
            _print_metrics("Oct 8 - Dec 31 (old test window)", r["metrics_oct_dec"])
    conn.close()


if __name__ == "__main__":
    main()
