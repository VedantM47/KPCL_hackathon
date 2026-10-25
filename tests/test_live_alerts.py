"""Backend tests for what the phone app depends on: alert severities in the live replay, the SSE
stream, replay control, demo alerts and the developer-console endpoints.

Run from the project root:  python -m pytest tests -q
Needs kpcl_energy.db; uses the .cache model pickle when present (otherwise startup trains, ~1-2 min).
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from api import live as live_mod
from api import main


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:   # runs the lifespan: models + live engine
        yield c


@pytest.fixture(scope="module")
def engine(client):
    return live_mod.ENGINE["e"]


def _all_alerts(engine, plant):
    prev = None
    for i in range(engine.n):
        yield i, engine.frame(i, plant, event_from=prev)["alerts"]
        prev = i


# ---------------------------------------------------------------- severity / alert rules

def test_anomaly_severity_is_not_all_critical(engine):
    flagged = main.CACHE["anomalies"]
    flagged = flagged[flagged["final_flag"]]
    sev = live_mod.score_severity(flagged).value_counts(normalize=True)
    assert set(sev.index) == {"low", "medium", "high", "critical"}
    assert sev["critical"] < 0.07          # top 5% per asset (ties allowed a little slack)


@pytest.mark.parametrize("plant", ["ALL", "HADAPSAR", "SASWAD", "NASHIK"])
def test_critical_alerts_are_rare_and_only_known_kinds(engine, plant):
    kinds = {}
    for _, alerts in _all_alerts(engine, plant):
        for a in alerts:
            assert {"severity", "kind", "key", "message", "asset_id"} <= a.keys()
            if a["severity"] == "critical":
                kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
    assert set(kinds) <= {"breach", "anomaly_sustained"}
    # a breach is one alert per breached tick; episodes are far fewer. Either way: rare, not every few ticks
    total = sum(kinds.values())
    assert total < engine.n * 0.01, (plant, kinds)


def test_anomaly_start_is_never_critical(engine):
    for evs in engine.events_by_idx.values():
        for a in evs:
            if a["kind"] == "anomaly":
                assert a["severity"] != "critical"
            else:
                assert a["kind"] == "anomaly_sustained" and a["severity"] == "critical"


def test_breach_frame_is_critical_and_keyed(engine):
    s = engine.series["SASWAD"]
    i = int((s["kva"] > s["contract"]).nonzero()[0][0])
    f = engine.frame(i, "SASWAD")
    assert f["status"] == "critical"
    breach = [a for a in f["alerts"] if a["kind"] == "breach"]
    assert breach and breach[0]["severity"] == "critical" and breach[0]["key"] == "breach:SASWAD"


def test_normal_frame_status(engine):
    s = engine.series["ALL"]
    i = int((s["kva"] < 0.5 * s["contract"]).nonzero()[0][0])
    f = engine.frame(i, "ALL")
    assert f["status"] == "normal"
    assert not [a for a in f["alerts"] if a["kind"] in ("breach", "near_contract")]


def test_skipped_ticks_keep_events(engine):
    i = next(k for k in sorted(engine.events_by_idx) if k > 5)
    asset = engine.events_by_idx[i][0]["asset_id"]
    f = engine.frame(i + 3, "ALL", event_from=i - 1)       # client jumped over tick i
    assert any(a["asset_id"] == asset for a in f["alerts"])
    f = engine.frame(i + 3, "ALL", event_from=i + 2)       # already past it: not repeated
    assert not any(a.get("key") == engine.events_by_idx[i][0]["key"] for a in f["alerts"])


def test_frames_are_strict_json(engine):
    for i in range(0, engine.n, 997):
        for plant in engine.series:
            json.dumps(engine.frame(i, plant), allow_nan=False)


# ---------------------------------------------------------------- HTTP endpoints the app calls

def test_plants(client):
    r = client.get("/plants")
    assert r.status_code == 200
    ids = [p["plant_id"] for p in r.json()]
    assert ids[0] == "ALL" and {"HADAPSAR", "SASWAD", "NASHIK"} <= set(ids)


@pytest.mark.parametrize("plant", ["ALL", "HADAPSAR", "SASWAD", "NASHIK"])
def test_worst_day(client, plant):
    r = client.get(f"/schedule/days?top_n=1&plant={plant}")
    assert r.status_code == 200 and len(r.json()) == 1 and len(r.json()[0]["date"]) == 10


def test_control_and_snapshot(client, engine):
    r = client.post("/live/control", json={"jump_to": "2025-06-01 05:30", "speed": 8, "paused": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ts"].startswith("2025-06-01 05:30") and body["paused"] is True and body["speed"] == 8
    assert client.post("/live/control", json={"jump_to": "not a date"}).status_code == 400
    snap = client.get("/live/snapshot?n=4&plant=HADAPSAR").json()
    assert len(snap) == 4 and snap[-1]["ts"].startswith("2025-06-01 05:30")
    assert client.get("/live/snapshot?plant=NOPE").status_code == 404
    client.post("/live/control", json={"speed": 1, "paused": False})


def test_simulate_alert_validates_severity(client):
    assert client.post("/live/simulate-alert", json={"severity": "bogus"}).status_code == 422
    r = client.post("/live/simulate-alert", json={})
    assert r.status_code == 200 and r.json()["sent"] >= 1


def test_stream_delivers_frames_and_demo_alert(client, engine):
    """Read the SSE stream like the app does and check a demo alert raised mid-stream arrives as critical.
    (TestClient buffers whole responses, so the endless SSE body is iterated directly.)"""
    resp = asyncio.run(live_mod.stream("HADAPSAR"))
    assert resp.media_type == "text/event-stream"

    async def read():
        got, sent = [], False
        async for chunk in resp.body_iterator:
            if not chunk.startswith("data:"):
                continue
            f = json.loads(chunk[5:])
            got.append(f)
            assert f["plant_id"] == "HADAPSAR" and f["status"] in ("normal", "watch", "critical")
            if not sent:
                sent = True
                engine.inject(None, None, "critical")
                continue
            demo = [a for a in f["alerts"] if a.get("kind") == "demo"]
            if demo:
                assert demo[0]["severity"] == "critical" and demo[0]["key"].startswith("demo:")
                return got
            assert len(got) < 50, "demo alert never arrived"

    got = asyncio.run(asyncio.wait_for(read(), 30))
    assert len(got) >= 2


# ---------------------------------------------------------------- developer console

def test_dev_dataset_lists_every_table_with_explanations(client):
    r = client.get("/dev/dataset")
    assert r.status_code == 200
    tables = {t["table"]: t for t in r.json()["tables"]}
    assert "fact_main_meter" in tables and "fact_compressor" in tables and len(tables) >= 19
    for t in tables.values():
        assert t["rows"] > 0 and t["about"]
        assert t["columns"], t["table"]
        for c in t["columns"]:
            assert c["meaning"] and c["type"], (t["table"], c)


def test_dev_dataset_covers_every_db_column(client):
    """Every column in the database has an explanation (catches schema changes)."""
    import sqlite3
    conn = sqlite3.connect(main.BASELINE_DB)
    explained = {t["table"]: {c["name"] for c in t["columns"]} for t in client.get("/dev/dataset").json()["tables"]}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({name})")}
        assert name in explained, name
        assert cols == explained[name], (name, cols ^ explained[name])


def test_dev_rows_paging_and_safety(client):
    r = client.get("/dev/dataset/fact_main_meter?limit=5&offset=10")
    assert r.status_code == 200
    b = r.json()
    assert b["columns"][:3] == ["ts", "kW", "kVA"] and len(b["rows"]) == 5 and b["total"] == 35040
    assert client.get("/dev/dataset/fact_main_meter?limit=100000").json()["limit"] == 100
    assert client.get("/dev/dataset/sqlite_master").status_code == 404
    assert client.get("/dev/dataset/fact_meter;DROP TABLE x").status_code == 404


def test_dev_glossary_matches_frame(client, engine):
    g = client.get("/dev/glossary").json()
    assert g["terms"] and all(t["meaning"] for t in g["terms"])
    fields = {x["field"] for x in g["live_fields"]}
    f = engine.frame(100, "HADAPSAR")
    for k, v in f.items():
        if k in ("idx", "data_label", "demo"):
            continue
        if isinstance(v, dict):
            for sub in v:
                assert f"{k}.{sub}" in fields, f"{k}.{sub} unexplained"
        elif isinstance(v, list):
            assert f"{k}[]" in fields, k
        else:
            assert k in fields, k


def test_anomaly_endpoints_have_spread_of_severity(client):
    r = client.get("/anomalies?plant=HADAPSAR&from=2025-03-01&to=2025-03-07")
    assert r.status_code == 200
    sev = {a["severity"] for a in r.json()}
    assert len(sev) >= 2
    daily = client.get("/anomalies/daily").json()
    assert {d["rank"] for d in daily} <= {1, 2, 3, 4}
