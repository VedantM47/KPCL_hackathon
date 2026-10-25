# KPCL AI-Driven Carbon Accounting & Intelligent Energy Management Dashboard

> **Every number in this project is a benchmark-calibrated simulation.** No file
> here contains real KPCL plant data. Ratings, tariffs, and emission factors
> are config placeholders — see **"Every value I assumed"** below before
> quoting any figure outside this prototype.

A hackathon prototype for Kirloskar Pneumatic (KPCL): a synthetic 365-day,
15-minute-resolution dataset for a 10-asset, three-plant company (Hadapsar,
Saswad, Nashik — compressors, chillers, a furnace, a paint booth, a CNC cell,
solar), with Scope 1/2 carbon accounting, anomaly detection, a walk-forward
day-ahead forecaster, simulated savings recommendations and what-if levers, a
FastAPI backend with a simulated live replay, a React dashboard, PDF reports,
and an Android on-call alert app.

**Quick start:** see **[HOW_TO_RUN.md](HOW_TO_RUN.md)** — one command
(`run-demo.ps1`) starts the API and the dashboard. Latest release (phone APK +
notes): https://github.com/VedantM47/KPCL_hackathon/releases/latest

---

## 1. Stack

| Layer | Technology |
|---|---|
| Simulation | Python 3.13, numpy, pandas, PyYAML |
| Database | SQLite |
| ML | scikit-learn (IsolationForest), LightGBM (quantile + mean models) |
| API | FastAPI, uvicorn, Server-Sent Events, reportlab (PDF export) |
| Dashboard | React 19, Vite 8, TanStack Router/Query, Tailwind CSS v4, Recharts, shadcn/ui (Radix), react-three-fiber + drei (3D) |
| Phone app | Native Kotlin, no third-party libraries (Android 8+) |
| CI / release | GitHub Actions builds the APK; a `v*` tag publishes a Release |

---

## 2. Project layout

```
config.yaml                  every rating, setpoint, fault, tariff, emission factor, plant
generator/                   the simulation (see DATABASE_AND_GENERATOR.md); plants.py splits the company meter per plant
build_db.py                  runs the simulation, writes kpcl_energy[_optimized].db
validate.py                  PASS/FAIL checks against both scenario DBs
ml/
  anomaly.py                  IsolationForest + rule checks, evaluated against fact_fault_label
  forecast.py                 walk-forward day-ahead forecast: interval band + daily-peak breach risk
  recommendations.py          ranked actions from real counterfactual simulations
  whatif.py                   one-lever-at-a-time simulation grid (what-if simulator)
  peak_shaving.py             day-level peak-shaving schedule planner
  losses.py                   compressed-air leak and anomaly-excess costing
  plant_cfg.py                shared plant helpers
api/
  main.py                     FastAPI backend (endpoints below)
  live.py                     simulated live replay (SSE), replay control, demo alerts
  devconsole.py               dataset browser + glossary for the phone's developer console
  reports.py                  per-plant management PDF
web_template/                 React dashboard (see note on the folder name below)
android/                      Kotlin phone app; android/dist/ holds a pre-built APK
tests/                        backend tests (alerts, stream, forecast, developer console)
run-demo.ps1                  one-command launcher (API + dashboard + firewall rule)
HOW_TO_RUN.md                 run guide for the dashboard and the phone
RELEASE_NOTES.md              notes published with the next GitHub Release
DATABASE_AND_GENERATOR.md     full schema + generator module reference
AGENT_CONTEXT.md              hand-off notes for developers / coding agents
kpcl_energy.db                baseline scenario database (generated, ~100 MB, not in git)
kpcl_energy_optimized.db      optimized scenario database (generated, ~100 MB, not in git)
recommendations.csv, whatif_grid.csv, whatif_baseline.csv   generated ML outputs (in git)
```

**On the `web_template/` folder name:** it should be `web/` per the original
layout, but OneDrive held a file lock on the directory throughout this build
(it reclones/syncs the moment any file inside changes) and two rename attempts
both failed with `Device or resource busy` / `Permission denied`. The app
inside is complete and correct — only the folder's name is off. Rename it
yourself once OneDrive settles (`mv web_template web`), or just leave it; no
code references the literal folder name.

---

## 3. How to run everything

The fastest path is **[HOW_TO_RUN.md](HOW_TO_RUN.md)** (`run-demo.ps1`). By hand:

### 3.1 Generate the data (from the project root)

```bash
pip install numpy pandas pyyaml scikit-learn lightgbm fastapi uvicorn reportlab

python build_db.py --scenario baseline      # -> kpcl_energy.db
python build_db.py --scenario optimized     # -> kpcl_energy_optimized.db
python validate.py                          # prints the PASS/FAIL table
```

Each `build_db.py` run takes roughly 30–60 seconds (365 days × 1-minute
internal resolution, aggregated to 15 minutes).

### 3.2 Run the ML stage

```bash
python ml/anomaly.py            # prints recall/precision/FPR vs fact_fault_label
python -m ml.forecast           # walk-forward evaluation per plant vs last-week/climatology baselines
python -m ml.recommendations    # writes recommendations.csv (counterfactual sims, a few minutes)
python -m ml.whatif             # writes whatif_grid.csv / whatif_baseline.csv (a few minutes)
```

Modules that import `build_db` or `ml.*` must be run with `python -m` from the
project root so the imports resolve.

### 3.3 Start the API

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The first start runs anomaly detection and the walk-forward forecasts (~1–2
minutes) and caches the models in `.cache/`; later starts take ~10 seconds.
Delete `.cache/` after changing the data or config. The running API needs
about 0.5 GB of RAM.

### 3.4 Start the dashboard

```bash
cd web_template
npm install
npm run dev          # http://localhost:5173
```

The dashboard talks to the API at `http://127.0.0.1:8000` by default; set
`VITE_API_BASE_URL` if the API runs elsewhere.

### 3.5 Tests

```bash
python -m pytest tests -q                       # backend (38 tests, ~3 min)
cd android && gradle testDebugUnitTest          # phone app logic (16 tests)
cd web_template && npx tsc -b --noEmit && npm run lint
cd web_template && npx vitest run --browser.enabled=false --environment node src/lib/chart-insights.test.ts src/components/kpcl/facility
```

`npm test` runs the whole web suite in a real browser and needs
`npm run test:browser:install` once.

---

## 4. Database schema & generator internals

Full table-by-table schema, row counts, and a module-by-module walkthrough of
the generator (including every physics formula and every known simplification)
is in **[DATABASE_AND_GENERATOR.md](DATABASE_AND_GENERATOR.md)**. Read that
before writing new queries against either `.db` file.

---

## 5. API endpoints

Almost every endpoint takes `?plant=ALL|HADAPSAR|SASWAD|NASHIK` (default: the whole company).

| Endpoint | Purpose |
|---|---|
| `GET /plants` | plants with contract demand (the switcher's options) |
| `GET /kpis?plant=&from=&to=` | energy, cost, peak demand, Scope 1/2, intensity, solar share |
| `GET /plants/compare` | per-plant energy, cost, emissions, peak vs contract, kWh/unit |
| `GET /assets` | asset master (ratings, plant mapping) |
| `GET /assets/{id}/series?from=&to=&res=15m\|1h\|1d` | any asset's time series |
| `GET /production/daily` | daily units, shift split, energy-per-unit |
| `GET /forecast/demand?plant=&date=` | day-ahead forecast for one day (default: the live replay's tomorrow): P10–P90 band, peak + breach risk, walk-forward metrics |
| `GET /schedule/days?plant=&top_n=&rank_by=actual\|risk` | days by metered peak (default) or forecast breach risk |
| `GET /schedule/plan?date=` | peak-shaving plan for one day |
| `GET /anomalies?from=&to=&asset_id=` | flagged 15-min rows with per-asset severity |
| `GET /anomalies/daily` | day × asset worst-severity grid (powers the fault timeline) |
| `GET /losses/summary`, `GET /losses/leaks/daily` | leak and anomaly-excess costs |
| `GET /recommendations` | ranked actions with real kWh/₹/tCO2 impact |
| `GET /whatif/grid` | what-if simulator levers and their simulated impact |
| `GET /scenario/compare` | baseline vs optimized totals |
| `GET /carbon/monthly` | monthly Scope 1/2/solar-avoided + fuel mix |
| `GET /carbon/report?format=csv\|pdf` | downloadable BRSR-style report |
| `GET /reports/plant` | ~4-page management PDF for a plant |
| `GET /live/stream` | Server-Sent Events: one frame per replay tick, with alerts (`severity`, `kind`, stable `key`) |
| `GET /live/snapshot?n=` | the last n frames, to backfill charts |
| `POST /live/control` | pause / speed / jump the replay |
| `GET /live/fault-windows` | labelled fault windows (for "Jump to fault" and the 3D view) |
| `POST /live/simulate-alert` | raise a demo critical alert on every dashboard and phone |
| `GET /dev/dataset`, `/dev/dataset/{table}`, `/dev/glossary` | every table and column explained, raw rows, glossary |

---

## 5a. Dashboard

Pages: **Live Monitor, Plant Overview, Compressor Room, Refrigeration,
Production, Carbon & ESG, Loss Tracker, Action Center**. The plant switcher in
the top bar changes every page.

- **Every chart explains itself.** Click any chart or diagram (or its ⓘ) for a
  card with what it shows, how to read it, and what the data on screen right now
  implies (computed from that data). Includes the What-if simulator and the
  baseline vs optimized toggle.
- **3D Facility View** (Live Monitor): rooms and machines per plant, coloured
  by live state (running / idle / off / fault), click a machine for its details;
  fault windows are drawn (furnace door open, CNC idle drift, weekend base-load
  waste lights the room amber). Scroll-zoom only after clicking into it.
  three.js loads on demand, outside the main bundle.
- **Day-ahead forecast** card (Plant Overview): the replay's tomorrow with an
  80% range, peak and breach risk.

## 5b. Phone app

`android/` — see [android/README.md](android/README.md). It notifies and
vibrates **only for critical conditions**: a contract demand breach (once per
episode), a machine abnormal for 24 hours straight, or the dashboard's
"Simulate critical alert". Everything else is shown silently. Includes a
developer console (live fields, every dataset table explained, glossary).

## 5c. Releases and deployment

- Releases: tag a commit `v*` and push the tag; `.github/workflows/build-apk.yml`
  builds the APK and publishes a GitHub Release using `RELEASE_NOTES.md`.
- Deployment: the API must run as **one always-on process** (the replay clock
  and the phone's live connection live in memory), with the two databases on
  disk and ~0.5–1 GB RAM — a small VPS (Mumbai/Bangalore region) with Caddy for
  https fits; serverless hosts do not. The dashboard is static files
  (`npm run build`) and can be served from the same machine.
  **The API has no authentication** — protect `/live/control` and
  `/live/simulate-alert` before exposing it publicly.

---

## 6. Every value I assumed

You asked for every value I didn't specify to be listed plainly. Here is the
complete list, grouped by where it lives. Everything below is tagged
`# assumed` in `config.yaml` or in the relevant `.py` file's source comments —
this table is a convenience index, not a separate source of truth.

### Location & calendar
- Plant coordinates: Saswad/Pune, lat 18.5, lon 73.9, elevation 650m
- Plant-to-site mapping: HADAPSAR (compressors/CNC/furnace/paint), SASWAD
  (chillers/solar), NASHIK (CMP-REC-01, test rig) — a reasonable split, not
  confirmed against real KPCL facility assignments
- Saturday rule: half-day, shift A only
- 2025 Indian holiday dates (Republic Day, Holi, Maharashtra Day,
  Independence Day, Ganesh Chaturthi, Diwali) and 3 planned-maintenance dates

### Weather
- Annual mean ambient temp, diurnal/seasonal amplitude, monsoon humidity dip,
  solar irradiance — all synthetic sinusoidal approximations, not sourced from
  a real Pune/Saswad weather record (the generator can optionally load a NASA
  POWER CSV instead; this wasn't wired up for the prototype)

### Production
- Units/shift mean and std per product family (gearbox, compressor package,
  refrigeration package); air-demand and CNC-minutes-per-unit coefficients

### Asset ratings (all "typical machine of this class," not measured specs)
- CMP-CENT-01: 160 kW, 26.0 m³/min, 28% idle fraction
- CMP-SCR-01: 90 kW, 14.6 m³/min, 27% idle fraction
- CMP-REC-01: 55 kW, 9.0 m³/min, 30% idle fraction
- TEST-RIG-CNG-01: 75 kW, 12.2 m³/min, 25% idle fraction
- The three compressor flow ratings were specifically *tuned* (not just
  guessed) so specific power lands in the 0.10–0.13 kWh/m³ target band across
  a full year of leak drift — see `config.yaml` comments at each rating
- CHILLER-VAM-01: 150 TR, fuel type **assumed as gas, not confirmed** — could
  equally be steam; flagged explicitly because this choice drives Scope 1
- CHILLER-SCR-01: 120 TR, 0.85 kW/TR base
- CNC-GEAR-01: 18 kW rated, 3 kW idle
- FURNACE-HT-01: 120 kW electric-assist, LPG primary fuel, 860°C hardening
  setpoint, 450±80 kg batch mass, 55% efficiency, 8 kW standby loss
- PAINT-BOOTH-01: 22 kW fan, 2.5 m³/min air draw, 35 kW oven, ~3 batches/day
- SOLAR-SASWAD-01: 500 kWp, 19.5% panel efficiency, 450 kW inverter

### Compressor physics constants
- Pressure band 6.8–7.4 bar (baseline) / 6.3–6.9 bar (optimized)
- Overpressure penalty: 6.5% extra power per bar above 7 bar
- Background system leak: starts at 8% of rated flow, grows ~0.015%/day
- Fault-driven leak growth rate: 0.15%/day × fault magnitude (distinct
  constant from the background drift, see `compressor.py`)
- Auto-stop: a load/unload compressor left unloaded for 5 minutes drops to a
  2.0 kW standby draw instead of idling indefinitely; a never-loaded lag
  compressor sits at 1.0 kW instead of full idle_kW
- Pressure-loop gain constant tuned so load/unload cycles complete in minutes,
  not seconds or hours

### Chiller physics constants
- Chilled-water ΔT: 5.5°C
- Natural-gas heating value: 13.1 kWh/kg — **VERIFY**
- Nominal refrigerant charge: 150 kg
- VAM pump/fan auxiliary load: 18 kW
- Condenser fouling and refrigerant-leak fault magnitudes (ramp shapes/sizes)

### Furnace physics constants
- Steel specific heat: 0.49 kJ/kg·K (typical alloy steel)
- LPG heating value: 12.8 kWh/kg — **VERIFY**
- Batch timing: 75 min ramp / 180 min hold / 90 min cooldown
- Hold-phase thermostat duty cycle: ~45% on-time

### Solar physics constants
- Cell-temperature heating model: ambient + irradiance × 25°C (NOCT-style
  approximation, not a vendor thermal model)
- Temperature derate coefficient: -0.4%/°C above 25°C

### Grid outages & diesel genset
- 3 injected outage windows (dates/times in `config.yaml`) — **not real DISCOM
  outage records**
- DG specific fuel consumption: 0.32 L/kWh — **VERIFY**

### Tariff (illustrative only — explicitly labeled in the data and the UI)
- 5 ToD periods and their ₹/kWh rates — loosely modeled on a typical
  Maharashtra HT industrial structure, **not an official MSEDCL/KPCL tariff
  order**
- Contract demand: 400 kVA — originally 1500 kVA in early drafts; I lowered
  it because at 1500 kVA the breach-risk flagging feature could never
  trigger against this plant's simulated scale (~430 kVA actual peak).
  400 kVA sits just above the real peak so the feature has something genuine
  to catch
- Demand charge: ₹480/kVA, PF penalty: ₹0.25/kVAh below 0.90 PF — **VERIFY**

### Emission factors (ALL explicitly marked "VERIFY before use" in the data)
- Grid: 0.716 tCO2/MWh (illustrative all-India average, not a specific DISCOM
  or year-stamped CEA figure)
- Diesel: 2.68 kgCO2/litre
- LPG: 2.98 kgCO2/kg
- Natural gas: 2.75 kgCO2/kg
- Refrigerant GWP: R134a 1430, R410a 2088 (IPCC AR5 GWP100 — these specific
  numbers are correct per IPCC, but their applicability to KPCL's actual
  refrigerant charge is unverified)

### Measurement realism
- 1–3% missing-data rate, 4 frozen-sensor stretches/asset, one asset
  (CMP-REC-01) with meter drift — all synthetic choices modeling "what sensor
  noise typically looks like," not measured from real telemetry

### ML / forecast
- Walk-forward evaluation: retrained on the 1st of each month from March on all
  earlier data, forecasting each day 24 h ahead; Jan–Feb have no forecast (too
  little history) and are labelled so rather than back-filled with actuals
- Actual weather stands in for a weather forecast (`weather_noise_c` in
  `run_forecast` simulates forecast error; default 0)
- LightGBM hyperparameters (120 trees, 31 leaves, 0.06 learning rate for
  intervals; 7 leaves for the daily-peak model) — reasonable defaults, not tuned
- "Warned" = forecast probability of the condition ≥ 30%
- IsolationForest contamination rate: 8% per asset — picked to roughly match
  known fault-window coverage, not derived from a labeled validation set

---

## 7. Known limitations (also called out in-context where relevant)

- `rollup_daily_plant`'s Scope 1/2/cost columns are whole-plant totals
  broadcast onto every plant's row, not a genuine per-site split — only kWh
  is truly per-plant in the current rollups, and the API/UI only ever expose
  that column per-plant
- The `weekend_baseload_waste` fault has no distinct physical mechanism
  implemented beyond pre-existing leak-driven weekend cycling — it passes
  `validate.py` check #7 trivially, not from dedicated modeling
- `validate.py` check #2 (night base load should be 15–25% of day load)
  currently reads ~43%. Traced to the compressed-air system's background
  leak running around the clock; not silently passed, flagged in the
  validator's own output
- The exact 15-minute load shape is largely unpredictable a day ahead: the
  generator randomises each day's CNC cutting minutes and paint-booth batch
  timing, so interval WAPE stays high (company ~65%, Hadapsar ~90%). The
  forecaster therefore predicts the daily peak with its own quantile model:
  peak bias is ~0 (the old single-split model was ~80 kVA low) and Hadapsar's
  near-contract days are warned 131/139 vs 80 for "same as last week".
  Actual contract breaches are rare spikes and remain hard (company 1/3,
  Hadapsar 1/6; Saswad 38/44)
- Nashik's per-plant energy is an allocation of the company's net-of-solar grid
  import (`generator/plants.py`), which swings far more day to day (CV 0.62)
  than Nashik's own metered load (CV 0.18). Its daily-energy forecast error
  (~43%) reflects that allocation, not the plant
- The Production page's "Monthly units vs plant energy" chart draws units only;
  energy is summarised in its click-to-explain card (kWh per unit), not plotted
- The Overview's solar chart is a flat step with little day-to-day variation — a
  limitation of the solar model, said so in its explanation card
- Not production-ready: no authentication, open CORS, no rate limiting, SQLite
  files in the working directory
- Web lint has one pre-existing error in the live-stream hook
  (`use-kpcl.ts`, setState in an effect), so `npm run lint` exits non-zero
- Browser QA: every chart explanation, the forecast card, the what-if popups and
  the 3D facility view are checked headless (Playwright, 66 checks) on desktop
  and at phone width; the template's top bar is still ~11 px too wide at 390 px.
  The phone app is tested on an emulator, not yet on a physical phone

---

## 8. What I'd verify first before any external use of this data

In priority order: the tariff rates and demand charge (section 6, very
unlikely to match a real KPCL contract), the grid emission factor's vintage/
source, the VAM fuel type (gas vs steam), and every asset rating in
`config.yaml`'s `assets:` block.
