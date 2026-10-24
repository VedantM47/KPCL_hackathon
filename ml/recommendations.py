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


def totals(built):
    kwh = built["main_meter_15m"]["kW"].sum() * 0.25
    cost_rs = built["main_meter_15m"]["cost_rs"].sum()
    tco2 = built["emissions_15"]["scope1_tco2"].sum() + built["emissions_15"]["scope2_tco2"].sum()
    return {"kWh": kwh, "cost_rs": cost_rs, "tco2": tco2}


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


def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    print("Simulating true baseline ...")
    baseline_totals = totals(build_db.build(config, "baseline"))
    print(f"Baseline annual: {baseline_totals['kWh']:.0f} kWh, Rs {baseline_totals['cost_rs']:.0f}, {baseline_totals['tco2']:.1f} tCO2\n")

    rows = []
    for action in POLICY_ACTIONS:
        print(f"Simulating counterfactual: {action['name']} ...")
        variant_totals = run_policy_variant(config, action["overrides"])
        rows.append({
            "action": action["name"], "type": "policy",
            "kWh_saved": baseline_totals["kWh"] - variant_totals["kWh"],
            "rs_saved": baseline_totals["cost_rs"] - variant_totals["cost_rs"],
            "tco2_saved": baseline_totals["tco2"] - variant_totals["tco2"],
        })

    for action in FAULT_FIX_ACTIONS:
        print(f"Simulating counterfactual: {action['name']} ...")
        variant_totals = run_fault_fix_variant(config, action["asset_id"], action["fault_type"])
        rows.append({
            "action": action["name"], "type": "fault_fix",
            "kWh_saved": baseline_totals["kWh"] - variant_totals["kWh"],
            "rs_saved": baseline_totals["cost_rs"] - variant_totals["cost_rs"],
            "tco2_saved": baseline_totals["tco2"] - variant_totals["tco2"],
        })

    report = pd.DataFrame(rows).sort_values("rs_saved", ascending=False).reset_index(drop=True)
    report["rank"] = report.index + 1

    print("\n=== Ranked recommendations (annual impact) ===")
    print(report[["rank", "action", "type", "kWh_saved", "rs_saved", "tco2_saved"]].to_string(index=False))

    report.to_csv("recommendations.csv", index=False)
    print("\nWritten to recommendations.csv")
    print("\nNote: 'Switch chiller sequencing to SCR-lead' trades a large Scope 1 (gas)")
    print("reduction for an even larger Scope 2 (grid electricity) increase, because")
    print("CHILLER-VAM-01 and CHILLER-SCR-01 are similarly rated — flipping lead/lag moves")
    print("the majority of the cooling load across fuel types, not a marginal shift.")
    print("'Start furnace earlier' shows a small negative saving here; its effect is")
    print("sensitive to ToD boundaries and is worth a second look before trusting in a demo.")
    return report


if __name__ == "__main__":
    main()
