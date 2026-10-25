"""Simulated live replay: a server-side "now" cursor walks the pre-generated
15-minute dataset so the dashboard can show a plant being monitored in real
time. Nothing here is real telemetry — every frame is labelled as a replay of
the benchmark-calibrated simulation.

The cursor is global (not per client) so every open browser tab stays in sync.
Frames are built per plant (ALL = whole company, or one plant_id).
"""
import asyncio
import json
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ml import losses as losses_mod
from ml import plant_cfg

router = APIRouter(prefix="/live", tags=["live"])

DATA_LABEL = "simulated live replay (benchmark-calibrated simulation)"
SEVERITY_LABELS = ["low", "medium", "high", "critical"]
# an anomaly only becomes critical once it has lasted 24 h without a break: in this dataset every such
# run is a real labelled fault, while shorter runs are mostly CNC-rule noise (~35% real)
SUSTAINED_INTERVALS = 96
COMPRESSORS = ("CMP-CENT-01", "CMP-SCR-01", "CMP-REC-01")
ENGINE = {}


def score_severity(flagged):
    """Severity of flagged anomaly rows from the score's rank within its own asset.

    Isolation-Forest scores sit around 0.4-0.8 and are not comparable across assets, so fixed
    bins put every flagged row in "critical". Ranking within the asset keeps the bands meaningful:
    top 5% critical, next 15% high, next 30% medium, the rest low.
    """
    pct = flagged.groupby("asset_id")["anomaly_score"].rank(pct=True)
    return pd.cut(pct, [0, 0.5, 0.8, 0.95, 1.0], labels=SEVERITY_LABELS, include_lowest=True).astype(str)


def _r(x, d):
    """round() that maps NaN to None so frames stay valid strict JSON."""
    x = float(x)
    return None if x != x else round(x, d)


class LiveEngine:
    def __init__(self, conn, config, anomalies):
        q = lambda sql: pd.read_sql(sql, conn)
        main = q("SELECT ts FROM fact_main_meter ORDER BY ts")
        self.ts = pd.to_datetime(main["ts"])
        self.n = len(main)
        day = self.ts.dt.date
        self.plant_ids = plant_cfg.plant_ids(config)

        self.solar_kw = q("SELECT kW_generated FROM fact_solar ORDER BY ts")["kW_generated"].to_numpy()
        self.ambient = q("SELECT ambient_temp_c FROM fact_weather ORDER BY ts")["ambient_temp_c"].to_numpy()

        meter = q("SELECT ts, asset_id, kW, state FROM fact_meter ORDER BY ts")
        asset_kw = meter.pivot(index="ts", columns="asset_id", values="kW").sort_index()
        asset_state = meter.pivot(index="ts", columns="asset_id", values="state").sort_index()
        self.assets = list(asset_kw.columns)
        self.asset_kw_np = asset_kw.to_numpy()
        self.asset_state_np = asset_state.to_numpy(dtype=object)

        comp = q("SELECT ts, asset_id, pressure_bar, specific_power_kwh_m3, leak_flow_m3min FROM fact_compressor "
                 "ORDER BY ts")
        self.comp = {a: g.reset_index(drop=True) for a, g in comp.groupby("asset_id")}
        self.kw_per_tr = q("SELECT kw_per_tr FROM fact_chiller WHERE asset_id='CHILLER-SCR-01' ORDER BY ts")["kw_per_tr"].to_numpy()

        # per-asset compressed-air leak burn, costed at the ToD rate
        leak_df, _ = losses_mod.leak_losses(conn, config)
        leak_by_asset = {}
        for a, g in leak_df.groupby("asset_id"):
            g = g.set_index("ts").reindex(self.ts).fillna(0.0)
            leak_by_asset[a] = {"kw": g["leak_kw"].to_numpy(), "rs": (g["leak_kw"] * g["rate"]).to_numpy(),
                                "avoid_rs": (g["avoidable_kw"] * g["rate"]).to_numpy()}

        pm = q("SELECT ts, plant_id, kW, kVA, pf, cost_rs, scope1_tco2, scope2_tco2 FROM fact_plant_meter ORDER BY ts")
        mm_all = q("SELECT ts, kW, kVA, pf, cost_rs FROM fact_main_meter ORDER BY ts")
        em_all = q("SELECT ts, scope1_tco2, scope2_tco2 FROM fact_emissions ORDER BY ts")

        self.series = {}
        for plant in [plant_cfg.ALL] + self.plant_ids:
            if plant == plant_cfg.ALL:
                d = mm_all.assign(scope1_tco2=em_all["scope1_tco2"].to_numpy(),
                                  scope2_tco2=em_all["scope2_tco2"].to_numpy())
            else:
                d = pm[pm["plant_id"] == plant].reset_index(drop=True)
            asset_ids = plant_cfg.assets_of(config, plant)
            comps = [a for a in COMPRESSORS if a in asset_ids]
            zeros = np.zeros(self.n)
            self.series[plant] = {
                "kw": d["kW"].to_numpy(), "kva": d["kVA"].to_numpy(), "pf": d["pf"].to_numpy(),
                "cost_today": d["cost_rs"].groupby(day).cumsum().to_numpy(),
                "s1_today": d["scope1_tco2"].groupby(day).cumsum().to_numpy(),
                "s2_today": d["scope2_tco2"].groupby(day).cumsum().to_numpy(),
                "contract": plant_cfg.contract_kva(config, plant),
                "asset_ids": asset_ids,
                "asset_cols": [j for j, a in enumerate(self.assets) if a in asset_ids],
                "lead_comp": next((a for a in ("CMP-CENT-01", "CMP-REC-01") if a in comps), None),
                "has_solar": "SOLAR-SASWAD-01" in asset_ids,
                "has_chiller": "CHILLER-SCR-01" in asset_ids,
                "leak_kw": sum((leak_by_asset[a]["kw"] for a in comps if a in leak_by_asset), zeros),
                "leak_rs": sum((leak_by_asset[a]["rs"] for a in comps if a in leak_by_asset), zeros),
                "avoid_rs": sum((leak_by_asset[a]["avoid_rs"] for a in comps if a in leak_by_asset), zeros),
            }

        self.pf_floor = float(config["tariff"].get("pf_penalty_below", 0.90))

        flagged = anomalies[anomalies["final_flag"]].copy()
        flagged["severity"] = score_severity(flagged)
        idx_of = pd.Series(np.arange(self.n), index=self.ts)
        flagged["idx"] = idx_of.reindex(flagged["ts"]).to_numpy()
        flagged = flagged.dropna(subset=["idx"])
        flagged["idx"] = flagged["idx"].astype(int)
        # alerts that happen once (anomaly start, sustained-anomaly escalation), keyed by tick index
        self.events_by_idx = {}
        for asset_id, g in flagged.groupby("asset_id"):
            g = g.sort_values("idx")
            idxs = g["idx"].to_numpy()
            run_id = np.cumsum(np.diff(idxs, prepend=idxs[0] - 2) != 1)
            for _, run in g.groupby(run_id):
                start, n = int(run["idx"].iloc[0]), len(run)
                first = run.iloc[0]
                src = "model+rule" if first.model_flag and first.rule_flag else ("rule" if first.rule_flag else "model")
                # a fresh anomaly is worth seeing, not worth waking someone: never critical at the start
                sev = "high" if first.severity == "critical" else first.severity
                self.events_by_idx.setdefault(start, []).append({
                    "asset_id": asset_id, "severity": sev, "kind": "anomaly", "source": src,
                    "score": _r(first.anomaly_score, 3), "key": f"anomaly:{asset_id}:{start}",
                    "message": f"{asset_id} anomaly started ({src}, score {_r(first.anomaly_score, 3)})"})
                # escalates when the run reaches 24 h, i.e. only what is known at that tick (no look-ahead)
                if n >= SUSTAINED_INTERVALS:
                    head = run.iloc[:SUSTAINED_INTERVALS]
                    at = start + SUSTAINED_INTERVALS - 1
                    self.events_by_idx.setdefault(at, []).append({
                        "asset_id": asset_id, "severity": "critical", "kind": "anomaly_sustained", "source": src,
                        "score": _r(head["anomaly_score"].max(), 3), "key": f"anomaly24h:{asset_id}:{start}",
                        "message": f"{asset_id} has been abnormal for 24 hours straight - inspect the machine"})

        faults = q("SELECT asset_id, fault_type, start_ts, end_ts FROM fact_fault_label WHERE label_class='fault'")
        self.fault_windows = faults.to_dict(orient="records")

        self.idx = 0
        self.ticks_per_sec = 1.0
        self.paused = False
        self.injected = []   # (seq, alert) pushed by /live/simulate-alert for demonstrations
        self.inject_seq = 0

    def frame(self, i, plant=plant_cfg.ALL, event_from=None):
        """One tick for one plant. Events (anomaly starts) in (event_from, i] are included too, so a
        client that skipped a few ticks at high replay speed does not lose them."""
        i = int(i) % self.n
        s = self.series[plant]
        contract_kva = s["contract"]
        kva, pf = float(s["kva"][i]), float(s["pf"][i])
        contract_pct = kva / contract_kva
        alerts = []
        status = "normal"
        # conditions repeat on every tick while they last; "key" lets clients page once per episode
        if contract_pct > 1.0:
            status = "critical"
            alerts.append({"asset_id": "PLANT", "severity": "critical", "kind": "breach", "source": "rule",
                           "key": f"breach:{plant}",
                           "message": f"Contract demand breached: {kva:.0f} kVA vs {contract_kva:.0f} kVA contract"})
        elif contract_pct > 0.85:
            status = "watch"
            alerts.append({"asset_id": "PLANT", "severity": "high", "kind": "near_contract", "source": "rule",
                           "key": f"near:{plant}", "message": f"Demand at {contract_pct * 100:.0f}% of contract"})
        if pf < self.pf_floor:
            alerts.append({"asset_id": "PLANT", "severity": "medium", "kind": "low_pf", "source": "rule",
                           "key": f"pf:{plant}",
                           "message": f"Power factor {pf:.2f} below {self.pf_floor:.2f} (penalty band)"})
        lo = event_from + 1 if event_from is not None and 0 < i - event_from <= 8 else i
        for j in range(lo, i + 1):
            for a in self.events_by_idx.get(j, []):
                if a["asset_id"] in s["asset_ids"]:
                    alerts.append(a)

        lead = self.comp.get(s["lead_comp"]) if s["lead_comp"] else None
        return {
            "idx": i,
            "ts": str(self.ts.iloc[i]),
            "plant_id": plant,
            "status": status,
            "plant": {"kW": _r(s["kw"][i], 2), "kVA": _r(kva, 2),
                      "pf": _r(pf, 3), "contract_kva": contract_kva,
                      "contract_pct": round(contract_pct, 4)},
            "today": {"cost_rs": _r(s["cost_today"][i], 1),
                      "scope1_tco2": _r(s["s1_today"][i], 4),
                      "scope2_tco2": _r(s["s2_today"][i], 4)},
            "solar_kw": _r(self.solar_kw[i], 2) if (s["has_solar"] or plant == plant_cfg.ALL) else None,
            "ambient_c": _r(self.ambient[i], 1),
            "compressor": {"pressure_bar": _r(lead["pressure_bar"][i], 2) if lead is not None else None,
                           "specific_power": _r(lead["specific_power_kwh_m3"][i], 4) if lead is not None else None,
                           "leak_m3min": _r(lead["leak_flow_m3min"][i], 2) if lead is not None else None,
                           "leak_kw": _r(s["leak_kw"][i], 1),
                           "leak_rs_per_hr": _r(s["leak_rs"][i], 0),
                           "avoidable_leak_rs_per_hr": _r(s["avoid_rs"][i], 0)},
            "chiller_kw_per_tr": _r(self.kw_per_tr[i], 3) if s["has_chiller"] else None,
            "assets": [{"asset_id": self.assets[j], "kW": _r(self.asset_kw_np[i, j], 2),
                        "state": self.asset_state_np[i, j]} for j in s["asset_cols"]],
            "alerts": alerts,
            "paused": self.paused,
            "speed": self.ticks_per_sec,
            "data_label": DATA_LABEL,
        }

    def inject(self, plant, message, severity):
        """Queue a fake alert that every connected client (web + phone) receives immediately."""
        self.inject_seq += 1
        n = self.inject_seq
        alert = {"asset_id": f"DEMO-{n}", "severity": severity, "kind": "demo", "source": "demo", "demo": True,
                 "key": f"demo:{n}", "message": message or "DEMO: contract demand breached, 432 kVA vs 400 kVA contract"}
        self.injected.append((n, alert))
        self.injected = self.injected[-20:]
        return n

    async def run(self):
        while True:
            await asyncio.sleep(1.0 / self.ticks_per_sec)
            if not self.paused:
                self.idx = (self.idx + 1) % self.n


def start(conn, config, anomalies):
    """Called from the API lifespan after the DB + anomaly cache are ready."""
    ENGINE["e"] = LiveEngine(conn, config, anomalies)
    ENGINE["task"] = asyncio.create_task(ENGINE["e"].run())


def stop():
    task = ENGINE.get("task")
    if task:
        task.cancel()


def _engine():
    e = ENGINE.get("e")
    if e is None:
        raise HTTPException(503, "live engine not ready")
    return e


def _plant(e, plant):
    plant = plant or plant_cfg.ALL
    if plant not in e.series:
        raise HTTPException(404, f"unknown plant {plant}")
    return plant


@router.get("/snapshot")
def snapshot(n: int = 96, plant: str = plant_cfg.ALL):
    """Last n frames up to the current cursor, to backfill charts on page load."""
    e = _engine()
    plant = _plant(e, plant)
    n = max(1, min(n, 672))
    end = e.idx
    return [e.frame(i, plant) for i in range(end - n + 1, end + 1)]


@router.get("/stream")
async def stream(plant: str = plant_cfg.ALL):
    e = _engine()
    plant = _plant(e, plant)

    async def gen():
        last = None
        seen = e.inject_seq   # only demo alerts raised after this client connected
        while True:
            fresh = [a for n, a in e.injected if n > seen]
            if fresh:
                seen = e.inject_seq
                f = e.frame(e.idx, plant)
                f["alerts"] = fresh
                f["demo"] = True
                yield f"data: {json.dumps(f)}\n\n"
            if e.idx != last:
                prev, last = last, e.idx
                yield f"data: {json.dumps(e.frame(last, plant, event_from=prev))}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(min(0.25, 0.5 / e.ticks_per_sec))

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class Control(BaseModel):
    speed: float | None = None      # ticks per real second (1 tick = 15 simulated minutes)
    paused: bool | None = None
    jump_to: str | None = None      # any timestamp/date string pandas can parse


@router.post("/control")
def control(c: Control):
    e = _engine()
    if c.speed is not None:
        e.ticks_per_sec = min(max(c.speed, 0.25), 64.0)
    if c.paused is not None:
        e.paused = c.paused
    if c.jump_to:
        try:
            target = pd.Timestamp(c.jump_to)
        except ValueError:
            raise HTTPException(400, f"unparseable jump_to: {c.jump_to}")
        e.idx = int(min(e.ts.searchsorted(target), e.n - 1))
    return {"idx": e.idx, "ts": str(e.ts.iloc[e.idx]), "speed": e.ticks_per_sec, "paused": e.paused}


@router.get("/fault-windows")
def fault_windows(plant: str = plant_cfg.ALL):
    e = _engine()
    plant = _plant(e, plant)
    ids = e.series[plant]["asset_ids"]
    return [w for w in e.fault_windows if w["asset_id"] in ids]


class SimAlert(BaseModel):
    message: str | None = None
    severity: Literal["low", "medium", "high", "critical"] = "critical"


@router.post("/simulate-alert")
def simulate_alert(a: SimAlert):
    """Demo helper: raise a critical alert right now on every connected dashboard and phone."""
    e = _engine()
    n = e.inject(None, a.message, a.severity)
    return {"sent": n}
