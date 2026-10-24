"""What-if grid: one-lever-at-a-time counterfactual simulations, precomputed.

A full-year re-simulation takes too long to run per slider move, so each lever
is simulated at a handful of settings offline and written to whatif_grid.csv.
The dashboard snaps its controls to these settings. Every row is a real
baseline-vs-variant simulation diff (same seed, same faults, one policy field
changed) — the same method as ml/recommendations.py.

Combining levers in the UI adds the individual deltas. That ignores
interactions between levers (e.g. test-rig timing and furnace timing both
affect the evening peak), so the UI labels combined totals as approximate.

Usage: python -m ml.whatif       (several minutes; ~14 full-year simulations)
"""
import copy

import pandas as pd
import yaml

import build_db
from ml import plant_cfg

LEVER_ASSETS = {
    "compressor_pressure": {"CMP-CENT-01", "CMP-SCR-01", "CMP-REC-01", "TEST-RIG-CNG-01"},
    "test_rig_start": {"TEST-RIG-CNG-01"},
    "furnace_start": {"FURNACE-HT-01"},
    "cnc_idle_shutdown": {"CNC-GEAR-01"},
    "chiller_sequencing": {"CHILLER-SCR-01", "CHILLER-VAM-01"},
}

LEVERS = [
    {"lever": "compressor_pressure", "label": "Compressor pressure band",
     "options": [
         {"label": "-0.8 bar", "value": -0.8}, {"label": "-0.5 bar", "value": -0.5},
         {"label": "-0.25 bar", "value": -0.25}, {"label": "+0.25 bar", "value": 0.25}],
     "overrides": lambda v, base: {"compressor_pressure_lower_bar": round(base["compressor_pressure_lower_bar"] + v, 2),
                                    "compressor_pressure_upper_bar": round(base["compressor_pressure_upper_bar"] + v, 2)}},
    {"lever": "test_rig_start", "label": "CNG test rig start time",
     "options": [{"label": t, "value": t} for t in ["06:00", "12:00", "18:00", "22:30"]],
     "overrides": lambda v, base: {"test_rig_start_time": v}},
    {"lever": "furnace_start", "label": "Furnace start time",
     "options": [{"label": t, "value": t} for t in ["05:00", "06:15", "09:00", "13:00"]],
     "overrides": lambda v, base: {"furnace_start_time": v}},
    {"lever": "cnc_idle_shutdown", "label": "CNC idle shutdown",
     "options": [{"label": "On", "value": True}],
     "overrides": lambda v, base: {"cnc_idle_shutdown": v}},
    {"lever": "chiller_sequencing", "label": "Chiller lead unit",
     "options": [{"label": "SCR lead (electric)", "value": "SCR_lead"}],
     "overrides": lambda v, base: {"chiller_sequencing": v}},
]


def totals(built):
    """Annual totals for the company (ALL) and each plant."""
    mm, em = built["main_meter_15m"], built["emissions_15"]
    out = {"ALL": {"kWh": float(mm["kW"].sum() * 0.25), "cost_rs": float(mm["cost_rs"].sum()),
                   "scope1": float(em["scope1_tco2"].sum()), "scope2": float(em["scope2_tco2"].sum()),
                   "peak_kva": float(mm["kVA"].max())}}
    for plant_id, g in built["plant_meter_15m"].groupby("plant_id"):
        out[plant_id] = {"kWh": float(g["kW"].sum() * 0.25), "cost_rs": float(g["cost_rs"].sum()),
                         "scope1": float(g["scope1_tco2"].sum()), "scope2": float(g["scope2_tco2"].sum()),
                         "peak_kva": float(g["kVA"].max())}
    return out


def _run_one(args):
    config, base_policy, li, oi = args
    lever = LEVERS[li]
    opt = lever["options"][oi]
    variant = copy.deepcopy(config)
    variant["policy"]["_variant"] = {**base_policy, **lever["overrides"](opt["value"], base_policy)}
    return li, oi, totals(build_db.build(variant, "_variant"))


def _run_baseline(config):
    return totals(build_db.build(config, "baseline"))


def main():
    from concurrent.futures import ProcessPoolExecutor

    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    base_policy = config["policy"]["baseline"]

    jobs = [(config, base_policy, li, oi) for li, lv in enumerate(LEVERS) for oi in range(len(lv["options"]))]
    print(f"Simulating baseline + {len(jobs)} variants in parallel ...", flush=True)
    with ProcessPoolExecutor(max_workers=8) as pool:
        base_future = pool.submit(_run_baseline, config)
        futures = [pool.submit(_run_one, j) for j in jobs]
        base = base_future.result()
        results = {}
        for fut in futures:
            li, oi, t = fut.result()
            results[(li, oi)] = t
            print(f"  done {LEVERS[li]['lever']} = {LEVERS[li]['options'][oi]['label']}", flush=True)

    rows = []
    for (li, oi), t in sorted(results.items()):
        lever, opt = LEVERS[li], LEVERS[li]["options"][oi]
        for plant_id in base:
            if plant_id != "ALL" and not (LEVER_ASSETS[lever["lever"]] & plant_cfg.assets_of(config, plant_id)):
                continue
            b, v = base[plant_id], t[plant_id]
            rows.append({
                "plant_id": plant_id, "lever": lever["lever"], "lever_label": lever["label"],
                "option_label": opt["label"], "option_value": str(opt["value"]),
                "kWh_saved": b["kWh"] - v["kWh"],
                "rs_saved": b["cost_rs"] - v["cost_rs"],
                "tco2_saved": (b["scope1"] + b["scope2"]) - (v["scope1"] + v["scope2"]),
                "scope1_saved": b["scope1"] - v["scope1"],
                "scope2_saved": b["scope2"] - v["scope2"],
                "peak_kva_reduction": b["peak_kva"] - v["peak_kva"],
            })

    df = pd.DataFrame(rows)
    df.to_csv("whatif_grid.csv", index=False)
    pd.DataFrame([{**v, "plant_id": k, "scenario": "baseline"} for k, v in base.items()]).to_csv(
        "whatif_baseline.csv", index=False)
    print(df.round(1).to_string(index=False))
    print("Written to whatif_grid.csv and whatif_baseline.csv")


if __name__ == "__main__":
    main()
