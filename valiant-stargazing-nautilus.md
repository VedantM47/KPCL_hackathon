# KPCL: Live demo + industry feature roadmap

## Context
The dashboard shows a static 365-day dataset (`kpcl_energy.db`, 15-min rows). For the hackathon demo it should feel like a plant being monitored right now. The data is simulated, so the honest way to do this is a **replay-as-live** mode. A server-side "simulated now" cursor walks through the existing data at accelerated speed and pushes each new reading to the UI. This must stay labelled "simulated live replay (benchmark-calibrated)", per the project's hard rule in AGENT_CONTEXT.md. No new physics and no regeneration of the DBs are needed.

## Part 1 — Live demo (implement first)

### Backend (`api/main.py`, new `api/live.py` imported by it)
- **Replay clock** held in `CACHE["live"]`. It has `cursor_idx` into the main-meter timestamps and `speed` (a multiplier, 1 tick = 15 sim-min; default about 1 tick/sec, so about 1 sim-day per 96 s). A background asyncio task started in `lifespan` advances the cursor. Loop at year end. A server-wide cursor keeps all browser tabs in sync.
- Preload at startup into in-memory DataFrames indexed by position: `fact_main_meter`, `fact_solar`, `fact_weather`, `fact_compressor`, `fact_chiller`, `fact_furnace`, `fact_paint_booth`, `fact_emissions`. The existing startup already loads the DB, so the extra cost is small.
- Endpoints, all routed through `_records()` (decision #6):
  - `GET /live/stream` — Server-Sent Events. Each tick emits one JSON frame: sim `ts`, plant kW/kVA/pf, cost-so-far for the day, per-asset kW and state, compressor pressure and specific power, chiller kW/TR, solar kW, ambient temperature, running Scope 1/2 for the day, `contract_pct = kVA/400`, and any anomalies whose `ts` equals this tick (looked up in `CACHE["anomalies"]`). SSE is simpler than WebSockets and `EventSource` reconnects on its own.
  - `GET /live/snapshot` — the last N frames (default 96 = 1 sim-day) to backfill charts on page load.
  - `POST /live/control` — `{speed, paused, jump_to}`, so the presenter can fast-forward to a fault window. Use `fact_fault_label` to list "jump to fault" shortcuts: `GET /live/fault-windows`.
  - **Fix needed:** the anomaly cache is stored with `ts` as datetime and `final_flag`. Pre-index it by `ts` for O(1) per-tick lookup.
- Rule-based live alerts computed per frame, reusing config values: contract-demand >85% / breach, compressor pressure out of band, chiller kW/TR above threshold, low power factor.

### Frontend (`web_template/src/`)
- New route `routes/_authenticated/live.tsx` and feature `features/live/index.tsx`. Follow the existing pattern (`features/plant/index.tsx`, `PageShell`, `KpiCard`, `TrendChart`). Add a nav entry next to the other pages.
- New hook `useLiveStream()` in `hooks/use-kpcl.ts`. It uses `EventSource` plus a ring buffer (about 288 points) in React state, hydrated from `/live/snapshot`. The type and URL go in `lib/kpcl-api.ts`.
- UI:
  - Header badge "● LIVE REPLAY · simulated" showing the sim clock and speed.
  - Pause/play and speed (1×/4×/16×) controls, and a "jump to fault" dropdown.
  - Rolling plant-load chart with the 400 kVA contract line.
  - Animated gauges/KPIs: kW, kVA %, pf, solar kW, ₹ today, tCO₂ today.
  - Asset tile grid with state colour (running/idle/fault).
  - Live alert ticker. New anomalies slide in with severity colour. This is the main "wow" element.
- Keep `<TrendChart>` animation off for streaming updates to avoid flicker.
- Fallback: if SSE fails, `refetchInterval: 1000` on `/live/snapshot`.

### Verification
1. `python -m uvicorn api.main:app --port 8000`, then `curl -N localhost:8000/live/stream` and confirm one frame per second with advancing `ts`.
2. `POST /live/control {"jump_to":"<fault start>"}` and confirm an anomaly appears in frames.
3. `npm run build`, then `npm run dev`. Open `/live` in two tabs and confirm they stay in sync.
4. Confirm the "simulated" label appears on the page.
5. Browser visual QA is still outstanding from earlier sessions. Do it here if a browser tool is available.

## Part 2 — Feature roadmap (industry value: cost and environment efficiency)

Ranked by (value to plant engineers / EHS / finance) ÷ effort. Everything here builds on tables that already exist.

**Tier 1 — high value, low effort (days)**
1. **Peak-demand shaving & ToD cost optimiser.** Uses the forecast (`ml/forecast.py`) plus `dim_tariff` to suggest shifting furnace/paint-booth/test-rig starts out of peak slots and to alert before a kVA breach. Payoff: demand charge ₹/kVA and ToD savings.
2. **Energy-per-unit (SEC) benchmarking.** kWh per unit by shift, product family and plant, with a deviation alert. Data is already in `/production/daily`.
3. **Compressed-air leak cost tracker.** Show `leak_flow_m3min` converted to ₹ and kg CO₂ per day, with a "fix leak, save X" card. Leaks usually cost 20–30% of compressor energy.
4. **Carbon cost & CBAM / BRSR readiness.** Extend `/carbon/report`: a carbon-price shadow cost (₹/tCO₂ slider), Scope 3 placeholder, and an intensity target tracker (tCO₂/unit).
5. **Alert rules + notification.** Configurable thresholds with email/WhatsApp/Slack webhook (stubbed for the demo).

**Tier 2 — medium effort (about 1–2 weeks)**
6. **Predictive maintenance.** Convert anomalies into remaining-useful-life and time-to-failure estimates for compressors and chillers (degrading specific power, kW/TR drift). Add maintenance-ticket export.
7. **Savings verification (M&V).** IPMVP-style baseline regression versus actual, to prove realised savings after an action. This builds credibility with finance.
8. **What-if simulator.** Sliders for compressor setpoint, chiller sequencing, furnace start time. They call the existing counterfactual machinery in `ml/recommendations.py` and return kWh, ₹ and CO₂ deltas. Note the Scope 1→2 tradeoff from decision #4.
9. **Solar & battery sizing.** Use `fact_solar` and load to compute self-consumption, export loss, and payback for added kWp or a BESS.
10. **Per-plant Scope 1/2/cost split.** Fixes the known limitation. Required before any multi-plant carbon chart.

**Tier 3 — larger bets**
11. **Real data ingestion.** Modbus/OPC-UA or MQTT adapters writing to the same schema, so the replay clock gives way to true live data. This is the path to a pilot.
12. **Auto-control loop (closed-loop setpoints).** Recommendations pushed to the BMS/PLC with human approval.
13. **Water & waste-heat recovery.** Chiller condenser or furnace waste-heat reuse modelling.
14. **Roles, auth, audit log, multi-tenant.** Prerequisite for production (see AGENT_CONTEXT "deploy this").
15. **Mobile / shift-handover view** with an AI-summarised "what happened this shift."

**Suggested demo narrative:** Live view → fault appears → alert → Action Center recommendation → what-if shows ₹ and CO₂ saved → carbon report export. Items 3 and 8 slot in with the least new work.

## Open questions for the user
- Replay speed default and whether to loop the year or stop at the end.
- Whether to fix the 8/9 night-load validation check first (generator/compressor.py), since "night base load" will be visible in a live view.
