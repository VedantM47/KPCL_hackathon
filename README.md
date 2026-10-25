# KPCL AI-Driven Carbon Accounting & Intelligent Energy Management Dashboard

> **Every number in this project is a benchmark-calibrated simulation.** No file
> here contains real KPCL plant data. Ratings, tariffs, and emission factors
> are config placeholders — see **"Every value I assumed"** below before
> quoting any figure outside this prototype.

A hackathon prototype: a synthetic 365-day, 15-minute-resolution dataset for a
10-asset industrial plant (compressors, chillers, a furnace, a paint booth, a
CNC cell, solar), plus anomaly detection, a load forecaster, auto-generated
savings recommendations, a FastAPI backend, and a React dashboard.

---

## 1. Stack

| Layer | Technology |
|---|---|
| Simulation | Python 3.13, numpy, pandas, PyYAML |
| Database | SQLite |
| ML | scikit-learn (IsolationForest), LightGBM |
| API | FastAPI, uvicorn, reportlab (PDF export) |
| Frontend | React 19, Vite 8, TanStack Router, Tailwind CSS v4, Recharts, shadcn/ui (Radix) |

---

## 2. Project layout

```
config.yaml                 every rating, setpoint, fault, tariff, emission factor
generator/                  the simulation (see DATABASE_AND_GENERATOR.md)
build_db.py                 runs the simulation, writes kpcl_energy[_optimized].db
validate.py                 8 PASS/FAIL checks against both scenario DBs
ml/
  anomaly.py                 IsolationForest + rule checks, evaluated against fact_fault_label
  forecast.py                LightGBM day-ahead 15-min load forecast
  recommendations.py         ranked actions from real counterfactual simulations
api/
  main.py                    FastAPI backend (endpoints below)
web_template/                React + Vite dashboard (see note on the folder name below)
kpcl_energy.db                baseline scenario database (generated, ~85MB)
kpcl_energy_optimized.db      optimized scenario database (generated, ~85MB)
recommendations.csv           output of ml/recommendations.py (generated)
DATABASE_AND_GENERATOR.md     full schema + generator module reference
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

### 3.1 Generate the data (from the project root)

```bash
pip install numpy pandas pyyaml scikit-learn lightgbm fastapi uvicorn reportlab

python build_db.py --scenario baseline      # -> kpcl_energy.db
python build_db.py --scenario optimized     # -> kpcl_energy_optimized.db
python validate.py                          # prints the 8-check PASS/FAIL table
```

Each `build_db.py` run takes roughly 30–60 seconds (365 days × 1-minute
internal resolution, aggregated to 15 minutes).

### 3.2 Run the ML stage

```bash
python ml/anomaly.py            # prints recall/precision/FPR vs fact_fault_label
python -m ml.forecast          # walk-forward evaluation per plant vs last-week/climatology baselines
python -m ml.recommendations    # writes recommendations.csv (~8 counterfactual sims, a few minutes)
```

`ml/recommendations.py` must be run as `python -m ml.recommendations` (not
`python ml/recommendations.py`) so that `import build_db` resolves — it needs
the project root on `sys.path`.

### 3.3 Start the API

```bash
python -m uvicorn api.main:app --reload --port 8000
```

Startup trains the forecast model and runs anomaly detection once (a few
seconds) and caches both in memory. `recommendations.csv` must already exist
(step 3.2) or `/recommendations` returns 503.

### 3.4 Start the dashboard

```bash
cd web_template
npm install
npm run dev          # http://localhost:5173
```

The dashboard talks to the API at `http://127.0.0.1:8000` by default; override
with a `VITE_API_BASE_URL` env var if you run the API elsewhere.

---

## 4. Database schema & generator internals

Full table-by-table schema, row counts, and a module-by-module walkthrough of
the generator (including every physics formula and every known simplification)
is in **[DATABASE_AND_GENERATOR.md](DATABASE_AND_GENERATOR.md)**. Read that
before writing new queries against either `.db` file.

---

## 5. API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /kpis?plant=&from=&to=` | energy, cost, peak demand, Scope 1/2, intensity, solar share |
| `GET /assets` | asset master (ratings, plant mapping) |
| `GET /assets/{id}/series?from=&to=&res=15m\|1h\|1d` | any asset's time series |
| `GET /plants/compare` | per-plant annual kWh (the only column genuinely split by site) |
| `GET /production/daily` | daily units, shift split, energy-per-unit |
| `GET /forecast/demand?plant=&date=` | day-ahead forecast for one day (default: the live replay's tomorrow): P10–P90 band, peak + breach risk, walk-forward metrics |
| `GET /schedule/days?plant=&top_n=&rank_by=actual\|risk` | days by metered peak (default) or forecast breach risk, each with both |
| `GET /anomalies?from=&to=&asset_id=` | flagged 15-min rows |
| `GET /anomalies/daily` | day × asset worst-severity grid (powers the fault timeline) |
| `GET /recommendations` | ranked actions with real kWh/₹/tCO2 impact |
| `GET /carbon/monthly` | monthly Scope 1/2/solar-avoided + fuel mix, as JSON |
| `GET /carbon/report?format=csv\|pdf` | downloadable BRSR-style report |
| `GET /scenario/compare` | baseline vs optimized totals |

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
- Browser QA is partial: the plant overview forecast card is checked headless (Playwright) per plant;
  other pages were verified via TypeScript compilation, a production build and API tests
  only. Worth a manual look before treating the UI as final

---

## 8. What I'd verify first before any external use of this data

In priority order: the tariff rates and demand charge (section 6, very
unlikely to match a real KPCL contract), the grid emission factor's vintage/
source, the VAM fuel type (gas vs steam), and every asset rating in
`config.yaml`'s `assets:` block.
