"""Stage 7: ranked recommended actions, each with kWh/Rs/tCO2 saved computed from
a real baseline-vs-counterfactual simulation diff — never guessed.

Two kinds of counterfactual:
  - policy change: re-run simulate() with one baseline policy field swapped to
    its optimized value (isolates that single lever, since the shipped
    "optimized" scenario bundles five policy changes at once).
  - fault fix: re-run simulate() with one fault removed from config entirely
    (isolates "what would fixing this leak/fouling/overrun be worth").

Usage: python ml/recommendations.py
"""
import copy

import pandas as pd
import yaml

import build_db
from ml import plant_cfg

POLICY_ACTIONS = [
    {"name": "Lower compressor pressure setpoint by 0.5 bar",
     "overrides": {"compressor_pressure_lower_bar": 6.3, "compressor_pressure_upper_bar": 6.9}},
    {"name": "Shift CNG test rig to off-peak ToD (09:00 -> 22:30)",
     "overrides": {"test_rig_start_time": "22:30"}},
    {"name": "Enable CNC idle shutdown",
     "overrides": {"cnc_idle_shutdown": True}},
    {"name": "Start furnace earlier to avoid peak-ToD overlap",
     "overrides": {"furnace_start_time": "06:15"}},
    {"name": "Switch chiller sequencing to SCR-lead",
     "overrides": {"chiller_sequencing": "SCR_lead"}},
]

FAULT_FIX_ACTIONS = [
    {"name": "Fix CMP-SCR-01 header leak before it grows", "asset_id": "CMP-SCR-01", "fault_type": "leak_growth"},
    {"name": "Clean CHILLER-SCR-01 condenser (fouling)", "asset_id": "CHILLER-SCR-01", "fault_type": "condenser_fouling"},
    {"name": "Stop PAINT-BOOTH-01 fan overrun after shift end", "asset_id": "PAINT-BOOTH-01", "fault_type": "paint_fan_overrun"},
]


# assets each action touches — a plant only gets the action if it owns one of them. Per-plant
# figures are an allocation of the company meter, so an action elsewhere would otherwise leak
# small spurious +/- amounts into plants it cannot affect.
ACTION_ASSETS = {
    "Lower compressor pressure setpoint by 0.5 bar": {"CMP-CENT-01", "CMP-SCR-01", "CMP-REC-01", "TEST-RIG-CNG-01"},
    "Shift CNG test rig to off-peak ToD (09:00 -> 22:30)": {"TEST-RIG-CNG-01"},
    "Enable CNC idle shutdown": {"CNC-GEAR-01"},
    "Start furnace earlier to avoid peak-ToD overlap": {"FURNACE-HT-01"},
    "Switch chiller sequencing to SCR-lead": {"CHILLER-SCR-01", "CHILLER-VAM-01"},
    "Fix CMP-SCR-01 header leak before it grows": {"CMP-SCR-01"},
    "Clean CHILLER-SCR-01 condenser (fouling)": {"CHILLER-SCR-01"},
    "Stop PAINT-BOOTH-01 fan overrun after shift end": {"PAINT-BOOTH-01"},
}


def relevant(config, plant_id, name):
    return plant_id == "ALL" or bool(ACTION_ASSETS[name] & plant_cfg.assets_of(config, plant_id))


def totals(built):
    """Annual kWh / Rs / tCO2 / peak kVA for the whole company (ALL) and for each plant."""
    mm = built["main_meter_15m"]
    em = built["emissions_15"]
    out = {"ALL": {"kWh": mm["kW"].sum() * 0.25, "cost_rs": mm["cost_rs"].sum(),
                   "tco2": em["scope1_tco2"].sum() + em["scope2_tco2"].sum()}}
    for plant_id, g in built["plant_meter_15m"].groupby("plant_id"):
        out[plant_id] = {"kWh": g["kW"].sum() * 0.25, "cost_rs": g["cost_rs"].sum(),
                         "tco2": g["scope1_tco2"].sum() + g["scope2_tco2"].sum()}
    return out


def run_policy_variant(config, overrides):
    variant = copy.deepcopy(config)
    variant["policy"]["_variant"] = {**variant["policy"]["baseline"], **overrides}
    built = build_db.build(variant, "_variant")
    return totals(built)


def run_fault_fix_variant(config, asset_id, fault_type):
    variant = copy.deepcopy(config)
    variant["faults"] = [f for f in variant["faults"]
                          if not (f["asset_id"] == asset_id and f["fault_type"] == fault_type)]
    built = build_db.build(variant, "baseline")
    return totals(built)


def _job(args):
    config, kind, spec = args
    if kind == "policy":
        return spec["name"], run_policy_variant(config, spec["overrides"])
    return spec["name"], run_fault_fix_variant(config, spec["asset_id"], spec["fault_type"])


def main():
    from concurrent.futures import ProcessPoolExecutor

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    jobs = [(config, "policy", a) for a in POLICY_ACTIONS] + [(config, "fault_fix", a) for a in FAULT_FIX_ACTIONS]
    kinds = {a["name"]: "policy" for a in POLICY_ACTIONS} | {a["name"]: "fault_fix" for a in FAULT_FIX_ACTIONS}
    print(f"Simulating baseline + {len(jobs)} counterfactuals in parallel ...", flush=True)
    with ProcessPoolExecutor(max_workers=8) as pool:
        base_future = pool.submit(_baseline, config)
        futures = [pool.submit(_job, j) for j in jobs]
        baseline_totals = base_future.result()
        results = dict(f.result() for f in futures)

    print(f"Baseline annual (company): {baseline_totals['ALL']['kWh']:.0f} kWh, "
          f"Rs {baseline_totals['ALL']['cost_rs']:.0f}, {baseline_totals['ALL']['tco2']:.1f} tCO2\n")

    rows = []
    for name, variant in results.items():
        for plant_id in baseline_totals:
            if not relevant(config, plant_id, name):
                continue
            rows.append({
                "plant_id": plant_id, "action": name, "type": kinds[name],
                "kWh_saved": baseline_totals[plant_id]["kWh"] - variant[plant_id]["kWh"],
                "rs_saved": baseline_totals[plant_id]["cost_rs"] - variant[plant_id]["cost_rs"],
                "tco2_saved": baseline_totals[plant_id]["tco2"] - variant[plant_id]["tco2"],
            })

    report = pd.DataFrame(rows).sort_values(["plant_id", "rs_saved"], ascending=[True, False]).reset_index(drop=True)
    report["rank"] = report.groupby("plant_id").cumcount() + 1

    print("=== Ranked recommendations (annual impact, company) ===")
    print(report[report["plant_id"] == "ALL"][["rank", "action", "type", "kWh_saved", "rs_saved", "tco2_saved"]].to_string(index=False))

    report.to_csv("recommendations.csv", index=False)
    print("\nWritten to recommendations.csv (rows per plant_id; ALL = company)")
    print("\nNote: 'Switch chiller sequencing to SCR-lead' trades a large Scope 1 (gas) reduction")
    print("for an even larger Scope 2 (grid electricity) increase. 'Start furnace earlier' is")
    print("sensitive to ToD boundaries and shows a small negative saving.")
    return report


def _baseline(config):
    return totals(build_db.build(config, "baseline"))


if __name__ == "__main__":
    main()
