"""Peak-shaving schedule recommender.

For a given day it takes the plant's kVA profile (the walk-forward day-ahead
forecast, which covers every day from March; before that there is too little
history and the metered actuals are used, labelled as such),
finds the peak, and searches for time shifts of the schedulable loads (CNG test
rig, heat-treatment furnace, paint booth) that lower it. Each candidate shift
is scored on the new peak kVA and on the ToD energy-cost change. Also flags
CNC idle time that could be a full shutdown.

Shifts move an asset's whole metered profile for that day by k intervals
(circular within the day), so the asset's total energy is unchanged — only
*when* it runs changes. Savings are therefore pure demand/ToD effects; CO2 is
unchanged because the grid factor is flat in this model (said so in the API).

Usage: imported by api/main.py
"""
import numpy as np
import pandas as pd

from ml import plant_cfg

STEP_H = 0.25
STEPS_PER_DAY = 96

# asset_id -> (label, max shift in hours either direction)
SHIFTABLE = {
    "TEST-RIG-CNG-01": ("CNG test rig", 14),
    "FURNACE-HT-01": ("Heat-treatment furnace", 6),
    "PAINT-BOOTH-01": ("Paint booth", 3),
}
CNC_ID = "CNC-GEAR-01"
RISK_THRESHOLD = 0.85   # fraction of contract demand
NO_FORECAST = "actual (no forecast: insufficient history)"


def _hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def tod_rate_array(config):
    """Rs/kWh for each of the 96 intervals of a day, from config tariff.tod_periods."""
    rates = np.zeros(STEPS_PER_DAY)
    for period in config["tariff"]["tod_periods"]:
        start, end = _hhmm(period["hours"][0]), _hhmm(period["hours"][1])
        for i in range(STEPS_PER_DAY):
            minute = i * 15
            inside = (start <= minute < end) if start < end else (minute >= start or minute < end)
            if inside:
                rates[i] = period["rate_rs_per_kwh"]
    return rates


class PeakPlanner:
    def __init__(self, conn, config, forecast=None, plant_id=None):
        """``forecast`` is a run_forecast() result (or, for older callers, its interval DataFrame)."""
        plant_id = plant_cfg.norm(plant_id)
        self.plant_id = plant_id
        self.plant_assets = plant_cfg.assets_of(config, plant_id)
        self.contract_kva = plant_cfg.contract_kva(config, plant_id)
        self.demand_charge = float(config["tariff"]["demand_charge_rs_per_kva"])
        self.rates = tod_rate_array(config)

        if plant_id is None:
            mm = pd.read_sql("SELECT ts, kW, kVA, pf FROM fact_main_meter ORDER BY ts", conn)
        else:
            mm = pd.read_sql("SELECT ts, kW, kVA, pf FROM fact_plant_meter WHERE plant_id = ? ORDER BY ts",
                             conn, params=(plant_id,))
        mm["ts"] = pd.to_datetime(mm["ts"])
        mm["date"] = mm["ts"].dt.strftime("%Y-%m-%d")
        self.mm = mm

        self.forecast_kva = {}
        self.forecast_days = {}
        if forecast is not None:
            intervals = forecast["intervals"] if isinstance(forecast, dict) else forecast
            ft = intervals[["ts", "pred_kva"]].copy()
            ft["date"] = ft["ts"].dt.strftime("%Y-%m-%d")
            self.forecast_kva = {d: g["pred_kva"].to_numpy() for d, g in ft.groupby("date") if len(g) == STEPS_PER_DAY}
            if isinstance(forecast, dict) and "days" in forecast:
                fd = forecast["days"]
                self.forecast_days = {d.strftime("%Y-%m-%d"): r for d, r in fd.iterrows()}

        meter = pd.read_sql("SELECT ts, asset_id, kW, state FROM fact_meter ORDER BY ts", conn)
        meter["date"] = pd.to_datetime(meter["ts"]).dt.strftime("%Y-%m-%d")
        meter = meter[meter["asset_id"].isin(list(SHIFTABLE) + [CNC_ID])]
        self.asset_days = {}
        for (d, a), g in meter.groupby(["date", "asset_id"]):
            if len(g) == STEPS_PER_DAY:
                self.asset_days[(d, a)] = (g["kW"].fillna(0.0).to_numpy(), g["state"].to_numpy())

        self.day_cache = {d: g for d, g in mm.groupby("date") if len(g) == STEPS_PER_DAY}
        self._days_summary = None

    # -- profile ----------------------------------------------------------
    def _profile(self, date):
        g = self.day_cache.get(date)
        if g is None:
            return None
        if date in self.forecast_kva:
            return self.forecast_kva[date], "forecast", g
        return g["kVA"].ffill().fillna(0.0).to_numpy(), NO_FORECAST, g

    def risk_days(self, top_n=40, rank_by="actual"):
        """Days ranked by metered peak ("actual": what really happened, e.g. to replay the worst day)
        or by forecast breach risk then P90 peak ("risk": what the planner would have warned about)."""
        if self._days_summary is None:
            rows = []
            for date, g in self.day_cache.items():
                f = self.forecast_days.get(date)
                rows.append({
                    "date": date, "peak_kva": float(g["kVA"].max()),
                    "source": "forecast" if date in self.forecast_kva else NO_FORECAST,
                    "forecast_peak_kva": None if f is None else round(float(f["peak_p50_kva"]), 1),
                    "forecast_peak_p90_kva": None if f is None else round(float(f["peak_p90_kva"]), 1),
                    "breach_risk": None if f is None else round(float(f["breach_risk"]), 3),
                })
            df = pd.DataFrame(rows)
            df["contract_pct"] = df["peak_kva"] / self.contract_kva
            self._days_summary = df
        df = self._days_summary
        if rank_by == "risk":
            df = df.sort_values(["breach_risk", "forecast_peak_p90_kva"], ascending=False, na_position="last")
        else:
            df = df.sort_values("peak_kva", ascending=False)
        out = df.head(top_n).copy()
        out["peak_kva"] = out["peak_kva"].round(1)
        out["contract_pct"] = out["contract_pct"].round(4)
        out = out.astype(object).where(out.notna(), None)
        return out.to_dict(orient="records")

    # -- planning ---------------------------------------------------------
    def plan(self, date):
        prof = self._profile(date)
        if prof is None:
            return None
        base, source, g = prof
        base = np.asarray(base, dtype=float)
        pf = np.clip(g["pf"].fillna(0.94).to_numpy(), 0.85, 0.99)
        ts = [t.strftime("%H:%M") for t in g["ts"]]

        cur = base.copy()
        peak_before = float(cur.max())
        peak_i = int(cur.argmax())

        # order assets by how much they draw at the peak interval
        shiftable = [a for a in SHIFTABLE if a in self.plant_assets]
        contrib = {a: self.asset_days.get((date, a), (np.zeros(STEPS_PER_DAY), None))[0][peak_i] for a in shiftable}
        actions = []
        for asset in sorted(shiftable, key=lambda a: -contrib[a]):
            if (date, asset) not in self.asset_days:
                continue
            kw = self.asset_days[(date, asset)][0]
            if kw.max() < 1.0 or kw.sum() * STEP_H < 5.0:
                continue
            label, max_h = SHIFTABLE[asset]
            max_steps = int(max_h / STEP_H)
            cur_peak = cur.max()
            at_risk_day = cur_peak > RISK_THRESHOLD * self.contract_kva
            best = None
            for k in range(-max_steps, max_steps + 1):
                if k == 0:
                    continue
                delta_kw = np.roll(kw, k) - kw
                new = np.maximum(cur + delta_kw / pf, 0.0)   # net import cannot go below zero
                peak_new = new.max()
                energy_cost = float((delta_kw * STEP_H * self.rates).sum())   # negative = saving
                if at_risk_day:
                    score = (round(peak_new, 2), energy_cost, abs(k))
                elif peak_new <= cur_peak + 0.5:
                    score = (energy_cost, round(peak_new, 2), abs(k))   # safe day: chase cheaper ToD slots
                else:
                    continue
                if best is None or score < best[0]:
                    best = (score, k, new, energy_cost)
            if best is None:
                continue
            _, k, new, energy_cost = best
            kva_cut = float(cur_peak - new.max())
            worthwhile = (at_risk_day and kva_cut >= 3.0) or energy_cost < -20.0
            if not worthwhile or (energy_cost > 0 and kva_cut < 5.0):
                continue   # shifting this asset buys nothing worth the disruption
            nz = np.nonzero(kw > 0.5 * kw.max())[0]
            old_start = int(nz[0]) if len(nz) else 0
            new_start = (old_start + k) % STEPS_PER_DAY
            actions.append({
                "type": "shift", "asset_id": asset, "asset_label": label,
                "from_time": ts[old_start], "to_time": ts[new_start],
                "shift_hours": k * STEP_H,
                "kva_reduction": round(kva_cut, 1),
                "tod_energy_saving_rs": round(-energy_cost, 0),
                "message": f"Move {label} main run from {ts[old_start]} to {ts[new_start]} "
                           f"({'earlier' if k < 0 else 'later'} by {abs(k) * STEP_H:g} h)",
            })
            cur = new

        # idle-time advice: CNC sitting at idle draw instead of being shut down
        idle = self.asset_days.get((date, CNC_ID)) if CNC_ID in self.plant_assets else None
        if idle is not None:
            kw, state = idle
            idle_mask = state == "idle"
            off_kw = float(np.median(kw[state == "off"])) if (state == "off").any() else 2.3
            idle_kwh = float(np.clip(kw[idle_mask] - off_kw, 0, None).sum() * STEP_H)
            if idle_kwh > 0.5:
                idle_rs = float(((np.clip(kw - off_kw, 0, None) * STEP_H * self.rates)[idle_mask]).sum())
                actions.append({
                    "type": "idle_shutdown", "asset_id": CNC_ID, "asset_label": "CNC gear machine",
                    "from_time": None, "to_time": None, "shift_hours": 0,
                    "kva_reduction": 0.0, "tod_energy_saving_rs": round(idle_rs, 0),
                    "message": f"Shut CNC down during {int(idle_mask.sum())} idle intervals "
                               f"(saves {idle_kwh:.1f} kWh vs idle draw)",
                })

        peak_after = float(cur.max())
        return {
            "date": date, "plant_id": self.plant_id or plant_cfg.ALL, "source": source, "contract_kva": self.contract_kva,
            "peak_before_kva": round(peak_before, 1), "peak_after_kva": round(peak_after, 1),
            "peak_time": ts[peak_i],
            "kva_reduction": round(peak_before - peak_after, 1),
            "breach_before": bool(peak_before > self.contract_kva),
            "breach_after": bool(peak_after > self.contract_kva),
            "at_risk": bool(peak_before > RISK_THRESHOLD * self.contract_kva),
            "demand_charge_at_stake_rs": round((peak_before - peak_after) * self.demand_charge, 0),
            "tod_energy_saving_rs": round(sum(a["tod_energy_saving_rs"] for a in actions), 0),
            "actions": actions,
            "profile": [{"time": ts[i], "before": round(float(base[i]), 1), "after": round(float(cur[i]), 1)}
                        for i in range(STEPS_PER_DAY)],
            "notes": "Shifts keep each asset's daily energy unchanged, so kWh and CO2 are unchanged "
                     "(flat grid factor); savings are demand-charge exposure (billed on the month's max) "
                     "and ToD energy rate.",
            "data_label": "benchmark-calibrated simulation",
        }
