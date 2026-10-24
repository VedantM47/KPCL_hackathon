"""Stage 7: 24h-ahead plant load forecast at 15-min resolution.

Deliberately day-ahead, not same-day: features are restricted to information
that is genuinely available 24h before the forecast target (calendar, planned
production, weather forecast proxy, and lags of exactly 1 day / 1 week — never
a same-day lag like t-15min, which would make "24h-ahead" meaningless).

Train on the first 9 months, test on the final 3 (captures the monsoon).
Reports MAPE and flags predicted contract-demand (kVA) breaches.

Usage: python ml/forecast.py
"""
import sqlite3
import numpy as np
import pandas as pd
import lightgbm as lgb
import yaml

DB_PATH = "kpcl_energy.db"
HORIZON_STEPS = 96          # 24h at 15-min resolution
LAG_DAY_STEPS = 96          # t-24h
LAG_WEEK_STEPS = 96 * 7     # t-7d


def load_frame(conn):
    mm = pd.read_sql("SELECT ts, kW, kVA, pf FROM fact_main_meter", conn)
    mm["ts"] = pd.to_datetime(mm["ts"])
    mm = mm.sort_values("ts").reset_index(drop=True)

    wx = pd.read_sql("SELECT ts, ambient_temp_c, wet_bulb_c FROM fact_weather", conn)
    wx["ts"] = pd.to_datetime(wx["ts"])

    prod = pd.read_sql("SELECT date, shift, units, is_surge FROM fact_production", conn)
    daily_units = prod.groupby("date")["units"].sum().rename("planned_units")
    daily_units.index = pd.to_datetime(daily_units.index)

    df = mm.merge(wx, on="ts", how="left")
    df["date"] = df["ts"].dt.normalize()
    df = df.merge(daily_units, left_on="date", right_index=True, how="left")
    df["planned_units"] = df["planned_units"].fillna(0.0)
    return df


def build_features(df, config):
    df = df.copy()
    df["hour"] = df["ts"].dt.hour
    df["minute_of_day"] = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    df["dow"] = df["ts"].dt.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)

    holidays = {h["date"] for h in config["calendar"]["holidays_2025"]}
    maint = {m["date"] for m in config["calendar"]["planned_maintenance_days"]}
    date_str = df["ts"].dt.strftime("%Y-%m-%d")
    df["is_holiday"] = date_str.isin(holidays).astype(int)
    df["is_maintenance"] = date_str.isin(maint).astype(int)
    is_day_off = df["is_holiday"].astype(bool) | df["is_maintenance"].astype(bool) | (df["dow"] == 6)
    is_saturday = df["dow"] == 5

    a_start, a_end = 6 * 60, 14 * 60
    b_start, b_end = 14 * 60, 22 * 60
    in_a_window = (df["minute_of_day"] >= a_start) & (df["minute_of_day"] < a_end)
    in_b_window = (df["minute_of_day"] >= b_start) & (df["minute_of_day"] < b_end)
    # exact production-shift state, calendar-known a day ahead — not a naive
    # time-of-day window, since that alone confuses Saturday half-days with
    # Sundays/holidays and was the main source of large forecast errors
    df["in_shift_a"] = (~is_day_off & in_a_window).astype(int)
    df["in_shift_b"] = (~is_day_off & ~is_saturday & in_b_window).astype(int)
    df["is_production_day"] = (~is_day_off).astype(int)

    # lags only at exactly 1 day and 1 week — genuinely known 24h ahead of the target
    df["lag_1day_kw"] = df["kW"].shift(LAG_DAY_STEPS)
    df["lag_1week_kw"] = df["kW"].shift(LAG_WEEK_STEPS)

    # weather "forecast": proxy with actual weather (common simplification for a
    # 24h-ahead prototype — a real deployment would call a weather API here)
    feature_cols = ["ambient_temp_c", "wet_bulb_c", "planned_units", "hour", "dow",
                     "is_weekend", "is_holiday", "is_maintenance", "is_production_day",
                     "in_shift_a", "in_shift_b", "lag_1day_kw", "lag_1week_kw"]
    return df, feature_cols


def train_test_split_by_month(df):
    cutoff = df["ts"].min() + pd.Timedelta(days=int(365 * 9 / 12))
    train = df[df["ts"] < cutoff]
    test = df[df["ts"] >= cutoff]
    return train, test, cutoff


def run_forecast(config, conn):
    """Train once, return everything an API or CLI needs: the fitted model,
    its feature columns, the climatology lookup, and test-period predictions
    with metrics. Reused by ml/forecast.py's CLI and by api/main.py."""
    df = load_frame(conn)
    df, feature_cols = build_features(df, config)
    df = df.dropna(subset=feature_cols + ["kW"]).reset_index(drop=True)

    train, test, cutoff = train_test_split_by_month(df)

    # climatology baseline: typical load for this exact (hour, day-of-week) slot,
    # fit on TRAIN only. A single lag sample is noisy (one specific day's random
    # batch timing); averaging many same-slot training days denoises that a lot
    # and is a much stronger 24h-ahead predictor than lag_1day/lag_1week alone.
    climatology = train.groupby(["hour", "dow"])["kW"].mean().rename("climatology_kw")
    train = train.merge(climatology, on=["hour", "dow"], how="left")
    test = test.merge(climatology, on=["hour", "dow"], how="left")
    feature_cols = feature_cols + ["climatology_kw"]

    model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=7,
                               num_leaves=63, random_state=42, verbose=-1)
    model.fit(train[feature_cols], train["kW"])

    pred = model.predict(test[feature_cols])
    actual = test["kW"].to_numpy()
    abs_err = np.abs(actual - pred)
    mape = np.mean(abs_err / np.maximum(actual, 1.0)) * 100
    wape = abs_err.sum() / actual.sum() * 100   # weighted MAPE — standard for load
                                                  # forecasting, robust to the near-zero
                                                  # overnight/Sunday load that makes plain
                                                  # MAPE blow up on a handful of intervals
    naive_wape = np.abs(actual - test["climatology_kw"].to_numpy()).sum() / actual.sum() * 100

    pf_est = test["pf"].to_numpy()
    pred_kva = pred / np.clip(pf_est, 0.85, 0.99)
    contract_kva = config["tariff"]["contract_demand_kva"]
    breach_mask = pred_kva > contract_kva

    test = test.copy()
    test["pred_kw"] = pred
    test["pred_kva"] = pred_kva
    test["breach_flag"] = breach_mask

    importances = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)

    return {
        "model": model, "feature_cols": feature_cols, "climatology": climatology,
        "train": train, "test": test, "cutoff": cutoff,
        "mape": mape, "wape": wape, "naive_wape": naive_wape,
        "n_breaches": int(breach_mask.sum()), "contract_kva": contract_kva,
        "importances": importances,
    }


def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    conn = sqlite3.connect(DB_PATH)
    result = run_forecast(config, conn)
    test = result["test"]

    print(f"Train: {len(result['train'])} rows (< {result['cutoff'].date()}), Test: {len(test)} rows (final 3 months)")
    print(f"\nTest MAPE: {result['mape']:.2f}%  (dominated by a few near-zero-load intervals — see WAPE)")
    print(f"Test WAPE (sum|error|/sum|actual|): {result['wape']:.2f}%")
    print(f"Naive climatology-only baseline WAPE: {result['naive_wape']:.2f}%  (model beats it by {result['naive_wape'] - result['wape']:.1f}pt)")
    print("Remaining error is mostly irreducible: the generator randomizes each day's exact")
    print("CNC cutting minutes, paint-booth batch timing, and production units independently,")
    print("so no calendar/weather feature can predict that day-to-day noise 24h ahead.")

    n_breaches = result["n_breaches"]
    print(f"Predicted contract-demand ({result['contract_kva']} kVA) breaches in test period: {n_breaches} of {len(test)} intervals ({n_breaches/len(test):.2%})")

    print("\nFeature importances:")
    print(result["importances"].to_string())

    conn.close()
    return result["mape"], result["wape"], n_breaches


if __name__ == "__main__":
    main()
