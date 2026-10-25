"""Tests for the walk-forward day-ahead forecaster and the endpoints built on it.

Run from the project root:  python -m pytest tests -q
"""
import sqlite3

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from api import live as live_mod
from api import main
from ml import forecast as fc
from ml.peak_shaving import NO_FORECAST


@pytest.fixture(scope="module")
def config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


# ---------------------------------------------------------------- the model itself

def test_no_leakage_from_the_target_day_or_later(config):
    """A forecast for day D must not change when everything from D onwards is replaced by noise."""
    conn = sqlite3.connect(fc.DB_PATH)
    frame = fc.load_frame(conn, "SASWAD")
    conn.close()
    d = pd.Timestamp("2025-06-10")
    noisy = frame.copy()
    later = noisy["ts"] >= d
    rng = np.random.default_rng(1)
    for col in ("kW", "kVA"):
        noisy.loc[later, col] = noisy.loc[later, col] * rng.uniform(0.2, 3.0, later.sum())
    a = fc.run_forecast(config, None, "SASWAD", frame=frame, origins=["2025-06-01"])
    b = fc.run_forecast(config, None, "SASWAD", frame=noisy, origins=["2025-06-01"])
    pick = lambda r: r["intervals"][r["intervals"]["date"] == d][["pred_kw", "p10_kw", "p90_kw", "pred_kva"]].to_numpy()
    assert len(pick(a)) == 96
    np.testing.assert_allclose(pick(a), pick(b))
    cols = ["peak_p10_kva", "peak_p50_kva", "peak_p90_kva", "peak_p95_kva", "breach_risk"]
    np.testing.assert_allclose(a["days"].loc[d, cols].to_numpy(float), b["days"].loc[d, cols].to_numpy(float))


def test_exceed_prob_is_a_monotone_probability():
    q = np.array([[50.0, 60.0, 70.0, 75.0]])
    a = fc.PEAK_QUANTILES
    probs = [fc.exceed_prob(q, a, t)[0] for t in np.linspace(0, 200, 81)]
    assert all(0.0 <= x <= 1.0 for x in probs)
    assert all(x >= y for x, y in zip(probs, probs[1:]))
    assert fc.exceed_prob(q, a, 60.0)[0] == pytest.approx(0.5)
    assert fc.exceed_prob(q, a, 70.0)[0] == pytest.approx(0.1)


@pytest.mark.parametrize("plant", ["ALL", "HADAPSAR", "SASWAD", "NASHIK"])
def test_every_day_from_march_is_forecast_with_ordered_quantiles(client, plant):
    r = main.CACHE["forecast"][plant]
    iv, days = r["intervals"], r["days"]
    assert r["first_forecast_date"] == "2025-03-01"
    per_day = iv.groupby("date").size()
    assert per_day.index.min() == pd.Timestamp("2025-03-01") and per_day.index.max() == pd.Timestamp("2025-12-31")
    assert len(per_day) == 306 and (per_day == 96).all()
    assert (iv["p10_kw"] <= iv["pred_kw"] + 1e-9).all() and (iv["pred_kw"] <= iv["p90_kw"] + 1e-9).all()
    q = days[["peak_p10_kva", "peak_p50_kva", "peak_p90_kva", "peak_p95_kva"]].to_numpy()
    assert (np.diff(q, axis=1) >= -1e-9).all()
    assert days["breach_risk"].between(0, 1).all() and days["near_risk"].between(0, 1).all()
    assert (days["near_risk"] >= days["breach_risk"] - 1e-9).all()   # 85% of contract is easier to reach


@pytest.mark.parametrize("plant", ["ALL", "HADAPSAR", "SASWAD", "NASHIK"])
def test_forecast_quality_bars(client, plant):
    """The properties this forecaster exists for: unbiased peaks, calibrated band, energy adds up."""
    m = main.CACHE["forecast"][plant]["metrics"]
    contract = main.CACHE["forecast"][plant]["contract_kva"]
    assert abs(m["peak_bias_kva"]) < 0.05 * contract          # the old model was ~20% of contract low
    assert 0.70 <= m["band_coverage_p10_p90"] <= 0.90
    assert 0.70 <= m["peak_band_coverage_p10_p90"] <= 0.95
    assert m["interval_wape_pct"] <= m["interval_wape_last_week_pct"] + 2
    assert m["peak_mae_kva"] <= m["peak_mae_last_week_kva"] + 0.5
    nc = m["near_contract"]
    if nc["actual_days"]:
        assert nc["caught"] >= nc["last_week_baseline"]["caught"]


# ---------------------------------------------------------------- API + planner

def test_forecast_endpoint_defaults_to_replay_tomorrow(client):
    client.post("/live/control", json={"jump_to": "2025-07-14 10:00", "paused": True})
    r = client.get("/forecast/demand?plant=HADAPSAR")
    assert r.status_code == 200
    b = r.json()
    assert b["date"] == "2025-07-15" and b["covered"] is True
    assert len(b["last_24h"]) == 96
    row = b["last_24h"][40]
    assert row["p10_kw"] <= row["pred_kw"] <= row["p90_kw"]
    assert 0 <= b["day"]["breach_risk"] <= 1 and b["day"]["peak_p10_kva"] <= b["day"]["peak_p90_kva"]
    for k in ("mape_pct", "wape_pct", "naive_climatology_wape_pct", "contract_kva", "n_breaches_in_test_period"):
        assert k in b["metrics"]
    assert "peak_bias_kva" in b["evaluation"]
    client.post("/live/control", json={"paused": False})


def test_forecast_endpoint_explicit_and_uncovered_dates(client):
    b = client.get("/forecast/demand?plant=SASWAD&date=2025-01-15").json()
    assert b["covered"] is False and b["day"] is None
    assert len(b["last_24h"]) == 96 and b["last_24h"][0]["pred_kw"] is None and b["last_24h"][0]["kW"] is not None
    assert client.get("/forecast/demand?date=garbage").status_code == 400


def test_planner_uses_forecasts_and_labels_uncovered_days(client):
    planner = main.CACHE["planner"]["HADAPSAR"]
    assert planner.plan("2025-07-15")["source"] == "forecast"
    assert planner.plan("2025-01-15")["source"] == NO_FORECAST
    days = client.get("/schedule/days?plant=HADAPSAR&top_n=366").json()
    for d in days:
        if d["date"] >= "2025-03-01":
            assert d["source"] == "forecast" and d["breach_risk"] is not None
        else:
            assert d["source"] == NO_FORECAST and d["breach_risk"] is None


def test_schedule_days_default_rank_still_finds_a_real_breach_for_the_phone_demo(client):
    """The phone's "Jump to peak day" uses top_n=1 and must land on a day that actually breached."""
    for plant in ("ALL", "HADAPSAR", "SASWAD", "NASHIK"):
        top = client.get(f"/schedule/days?plant={plant}&top_n=1").json()[0]
        assert top["contract_pct"] > 1.0, (plant, top)


def test_schedule_days_rank_by_risk(client):
    days = client.get("/schedule/days?plant=SASWAD&top_n=20&rank_by=risk").json()
    risks = [d["breach_risk"] for d in days]
    assert risks == sorted(risks, reverse=True) and risks[0] > 0.5
    assert client.get("/schedule/days?rank_by=bogus").status_code == 400
