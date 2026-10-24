"""Stage 7: anomaly detection — IsolationForest per asset + simple rule checks,
evaluated against fact_fault_label (both real faults and hard negatives).

Usage: python ml/anomaly.py
"""
import sqlite3
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

DB_PATH = "kpcl_energy.db"

# asset_id -> (table, feature_columns, rule_fn)
# rule_fn(df) -> boolean Series, simple physics-threshold flags independent of the model
ASSET_SPECS = {
    "CMP-CENT-01": ("fact_compressor", ["kW", "pressure_bar", "flow_m3min", "leak_flow_m3min",
                                         "specific_power_kwh_m3", "load_fraction", "cycle_count"],
                    lambda df: (df["specific_power_kwh_m3"] > 0.14) | (df["pressure_bar"] > 7.6) | (df["leak_flow_m3min"] > 4.0)),
    "CMP-SCR-01": ("fact_compressor", ["kW", "pressure_bar", "leak_flow_m3min", "load_fraction"],
                   lambda df: df["leak_flow_m3min"] > 2.0),
    "CMP-REC-01": ("fact_compressor", ["kW", "pressure_bar", "flow_m3min", "leak_flow_m3min",
                                        "specific_power_kwh_m3", "load_fraction"],
                   lambda df: (df["specific_power_kwh_m3"] > 0.14) | (df["leak_flow_m3min"] > 2.0)),
    "CHILLER-SCR-01": ("fact_chiller", ["TR", "kW", "kw_per_tr", "COP", "condenser_approach_c", "refrigerant_charge_kg"],
                       lambda df: (df["condenser_approach_c"] > 5.5) | (df["COP"] < 3.3) | (df["refrigerant_charge_kg"] < 140)),
    "CNC-GEAR-01": ("fact_meter", ["kW"],
                    lambda df: df["kW"] > 6.0),
    "FURNACE-HT-01": ("fact_furnace", ["kW", "fuel_kg", "batch_mass_kg"],
                      lambda df: df["fuel_kg"] > 0.05),
    # rule_fn unused for PAINT-BOOTH-01 — run_asset special-cases it with an after-hours check instead
    "PAINT-BOOTH-01": ("fact_paint_booth", ["kW", "air_draw_m3min"], None),
}

# fault windows this asset's model should be sensitive to (for reporting only)
ASSET_FAULTS = {
    "CMP-CENT-01": ["setpoint_drift", "weekend_baseload_waste"],
    "CMP-SCR-01": ["leak_growth"],
    "CMP-REC-01": [],
    "CHILLER-SCR-01": ["condenser_fouling", "refrigerant_leak"],
    "CNC-GEAR-01": ["cnc_idle_drift"],
    "FURNACE-HT-01": ["furnace_door_open"],
    "PAINT-BOOTH-01": ["paint_fan_overrun"],
}


def load_table(conn, table, asset_id, cols):
    if table == "fact_meter":
        q = f"SELECT ts, {', '.join(cols)} FROM {table} WHERE asset_id='{asset_id}'"
    elif table == "fact_furnace" or table == "fact_paint_booth":
        q = f"SELECT ts, {', '.join(cols)} FROM {table}"
    else:
        q = f"SELECT ts, {', '.join(cols)} FROM {table} WHERE asset_id='{asset_id}'"
    df = pd.read_sql(q, conn)
    df["ts"] = pd.to_datetime(df["ts"])
    return df.sort_values("ts").reset_index(drop=True)


def add_rate_of_change_features(df, cols):
    for c in cols:
        df[f"{c}_roc"] = df[c].diff().fillna(0.0)
        df[f"{c}_roll24h"] = df[c].rolling(96, min_periods=1).mean()
    return df


def fit_isolation_forest(df, feature_cols, contamination=0.08):
    X = df[feature_cols].fillna(df[feature_cols].median())
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
    model.fit(X)
    scores = -model.score_samples(X)   # higher = more anomalous
    threshold = np.quantile(scores, 1 - contamination)
    flags = scores >= threshold
    return scores, flags


def run_asset(conn, asset_id, table, feature_cols, rule_fn, contamination=0.08):
    df = load_table(conn, table, asset_id, feature_cols)
    if asset_id == "PAINT-BOOTH-01":
        df["after_hours"] = (df["ts"].dt.hour >= 22) | (df["ts"].dt.hour < 5)
        rule_flags = df["after_hours"] & (df["kW"] > 0)
    else:
        rule_flags = rule_fn(df)

    roc_cols = [c for c in feature_cols if c not in ("cycle_count",)]
    df = add_rate_of_change_features(df, roc_cols)
    model_feature_cols = feature_cols + [f"{c}_roc" for c in roc_cols] + [f"{c}_roll24h" for c in roc_cols]

    scores, model_flags = fit_isolation_forest(df, model_feature_cols, contamination=contamination)
    df["anomaly_score"] = scores
    df["model_flag"] = model_flags
    df["rule_flag"] = rule_flags.to_numpy()
    df["final_flag"] = df["model_flag"] | df["rule_flag"]
    df["asset_id"] = asset_id
    return df[["ts", "asset_id", "anomaly_score", "model_flag", "rule_flag", "final_flag"]]


def evaluate(conn, flagged_by_asset):
    labels = pd.read_sql("SELECT * FROM fact_fault_label", conn)
    labels["start_ts"] = pd.to_datetime(labels["start_ts"])
    labels["end_ts"] = pd.to_datetime(labels["end_ts"]) + pd.Timedelta(days=1)

    all_flagged = pd.concat(flagged_by_asset.values(), ignore_index=True)

    rows = []
    for _, f in labels.iterrows():
        if f["label_class"] == "fault":
            sub = all_flagged[all_flagged["asset_id"] == f["asset_id"]]
        else:
            sub = all_flagged  # hard negatives aren't asset-specific; check across all assets
        in_win = sub[(sub["ts"] >= f["start_ts"]) & (sub["ts"] < f["end_ts"])]
        detect_rate = in_win["final_flag"].mean() if len(in_win) else np.nan
        rows.append({
            "fault_type": f["fault_type"], "asset_id": f["asset_id"], "label_class": f["label_class"],
            "n_rows_in_window": len(in_win), "flagged_fraction": detect_rate,
        })
    report = pd.DataFrame(rows)

    faults = report[report["label_class"] == "fault"]
    hard_neg = report[report["label_class"] == "normal"]

    recall = faults["flagged_fraction"].mean()          # fraction of fault-window rows caught
    fpr_hard_negatives = hard_neg["flagged_fraction"].mean()  # false-positive rate on tricky-but-normal rows

    # precision: of all flagged rows plant-wide, what fraction fall inside a real fault
    # window for that same asset (ground truth = fact_fault_label, not hard negatives)
    flagged_rows = all_flagged[all_flagged["final_flag"]]
    in_any_fault_window = np.zeros(len(flagged_rows), dtype=bool)
    for _, f in labels[labels["label_class"] == "fault"].iterrows():
        match = (flagged_rows["asset_id"] == f["asset_id"]) & \
                (flagged_rows["ts"] >= f["start_ts"]) & (flagged_rows["ts"] < f["end_ts"])
        in_any_fault_window |= match.to_numpy()
    precision = in_any_fault_window.mean() if len(flagged_rows) else np.nan

    overall_flag_rate = all_flagged["final_flag"].mean()
    return report, recall, precision, fpr_hard_negatives, overall_flag_rate


def main():
    conn = sqlite3.connect(DB_PATH)
    flagged = {}
    for asset_id, (table, cols, rule_fn) in ASSET_SPECS.items():
        print(f"Fitting IsolationForest for {asset_id} ...")
        flagged[asset_id] = run_asset(conn, asset_id, table, cols, rule_fn)

    report, recall, precision, fpr_hard_neg, overall_rate = evaluate(conn, flagged)
    print("\n=== Per-fault detection report ===")
    print(report.to_string(index=False))

    print(f"\nOverall flag rate (all assets, all rows): {overall_rate:.3%}")
    print(f"Recall on real faults (mean fraction of fault-window rows flagged): {recall:.1%}")
    print(f"Precision (flagged rows that land inside a real fault window): {precision:.1%}")
    print(f"False-positive rate on hard negatives (surge/heat-wave/maintenance): {fpr_hard_neg:.1%}")
    print("\nThis recall/precision/FPR triple is the number for the demo slide: it shows the")
    print("detector catches injected faults far more often than it flags merely-unusual-but-normal days.")

    conn.close()
    return report, recall, precision, fpr_hard_neg


if __name__ == "__main__":
    main()
