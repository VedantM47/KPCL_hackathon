# Agent Context — KPCL Energy Dashboard Project

> **Read this first if you're a fresh agent picking up this project.** It's a
> handoff document, not user-facing documentation — for that, see
> [README.md](README.md) (run instructions, assumptions) and
> [DATABASE_AND_GENERATOR.md](DATABASE_AND_GENERATOR.md) (schema + physics
> detail). This file tells you where things stand, why they're built the way
> they are, and what to watch out for before you touch anything.

## What this project is

A hackathon prototype for Kirloskar Pneumatic Company Limited (KPCL): a
synthetic (not real) 365-day, 15-minute-resolution energy dataset for a
10-asset industrial plant, plus anomaly detection, a load forecaster,
auto-generated savings recommendations, a FastAPI backend, and a React
dashboard. Every number is labeled "benchmark-calibrated simulation" — this
was a hard, explicit requirement from the user throughout. Never let a number
from this project get quoted as if it were real KPCL data.

**All 10 planned build stages are complete** (data generator → validated
SQLite database → ML → FastAPI → React dashboard → README). This is not a
"continue building" handoff — it's a "understand what exists, then do
whatever the user asks next" handoff.

## Current runtime state (as of last session)

- **API server**: `uvicorn api.main:app` on port 8000, started from the
  project root. Loads both DBs, trains the forecast model, and runs anomaly
  detection once at startup (a few seconds) — caches both in memory.
- **Dashboard dev server**: `npm run dev` (Vite) on port 5173, run from
  inside the frontend folder.
- Both were last left **running in the background**. If a fresh session
  finds port 8000 or 5173 unresponsive, restart with:
  ```bash
  python -m uvicorn api.main:app --port 8000          # from project root
  cd web_template && npm run dev                       # separate terminal
  ```
- On Windows, killing a stale listener before restart:
  ```powershell
  Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
  ```

## Directory map

```
config.yaml                 single source of truth: ratings, setpoints, calendar,
                             faults, tariff, emission factors — every assumed
                             value is tagged `# assumed` / `VERIFY` in comments
generator/                  the simulation itself, 1-minute internal resolution
  calendar.py weather.py production.py   Stage 1: frame + weather + production plan
  compressor.py chiller.py furnace.py    Stage 2: asset physics
  paint_booth.py cnc.py solar.py
  main_meter.py noise.py                 Stage 2: whole-plant meter + measurement realism
  faults.py fuel_events.py emissions.py  Stage 3/4: fault injection, Scope 1/2
  simulate.py                            orchestrates all of the above
build_db.py                 Stage 5: aggregates 1-min -> 15-min, writes SQLite
validate.py                 Stage 6: 8 PASS/FAIL checks (currently 8/9 — see below)
ml/
  anomaly.py                 IsolationForest + rules, evaluated vs fact_fault_label
  forecast.py                LightGBM day-ahead 15-min load forecast
  recommendations.py         ranked actions from real counterfactual re-simulations
api/
  main.py                    FastAPI backend, all endpoints, in-memory caching
web_template/                React 19 + Vite 8 + TanStack Router + Tailwind v4 dashboard
                             (should be named `web/` — see "Known oddities" below)
kpcl_energy.db                 baseline scenario, ~86MB, generated — not in git normally
kpcl_energy_optimized.db       optimized scenario, ~86MB, generated
recommendations.csv            output of `python -m ml.recommendations`, generated
README.md                      user-facing docs: run instructions + full assumptions list
DATABASE_AND_GENERATOR.md      full schema reference + generator module walkthrough
```

## How the pieces connect

```
config.yaml
   -> generator/simulate.py (runs calendar/weather/production/all asset physics/faults)
   -> build_db.py (aggregates to 15-min, writes kpcl_energy[_optimized].db)
   -> validate.py (sanity-checks both DBs)
   -> ml/anomaly.py, ml/forecast.py, ml/recommendations.py (read the DB(s), produce
      cached-in-memory results + recommendations.csv)
   -> api/main.py (reads DB + recommendations.csv, serves JSON/CSV/PDF)
   -> web_template/ (React dashboard, fetches from the API at :8000)
```

Two databases exist because the project's core "savings" story is a diff
between them: same RNG seed, same faults, only the **policy** differs
(compressor setpoint, test-rig timing, CNC idle shutdown, furnace start time,
chiller sequencing — see `config.yaml`'s `policy:` block).

## Key decisions made along the way (read before changing physics or config)

These aren't arbitrary — each fixed a real bug or resolved a real tension.
Don't revert them without understanding why they're there.

1. **Timezone bug**: `pd.date_range(..., tz='Asia/Kolkata')` was tz-aware,
   but writing tz-aware timestamps to SQLite silently converts them to UTC,
   shifting every hour-of-day computation by +5:30. Fixed by stripping the tz
   label right after generating the minute frame (`calendar.py`) so
   everything downstream stores naive local wall-clock time. **If you ever
   see day/night behavior that looks shifted by ~5.5 hours, check this
   first.**

2. **Compressor control-loop bug**: the lead compressor's turn-off condition
   originally required demand to drop below an unrealistic threshold, so once
   loaded it almost never unloaded — it just pinned against the pressure
   ceiling. Fixed to standard bang-bang hysteresis in `compressor.py`.

3. **Leak growth was way too aggressive**: an early version let background
   leak balloon to 45% of rated flow by year-end, dragging specific power
   outside the 0.10–0.13 kWh/m³ target for half the year. Fixed with two
   separate constants — a slow background drift and a much faster
   fault-specific rate — plus retuned compressor flow ratings in
   `config.yaml` (see each asset's comment there).

4. **Chiller sequencing was silently destroying the project's core claim**:
   `config.yaml`'s optimized policy originally flipped chiller sequencing to
   `SCR_lead`, which moves most cooling load from gas-fired VAM to electric
   SCR — a real Scope 1→Scope 2 tradeoff, but one that made the *shipped*
   "optimized" scenario use **46% more energy** than baseline, directly
   contradicting "the difference between baseline and optimized IS your
   simulated saving." Fixed by keeping chiller sequencing identical between
   the two policies; the tradeoff itself is still surfaced honestly as its
   own flagged recommendation in `ml/recommendations.py` (don't re-enable it
   in the bundled optimized policy without re-reading that reasoning).

5. **Contract demand was 1500 kVA against a ~430 kVA actual peak** — the
   breach-risk flagging feature could never trigger. Lowered to 400 kVA
   (`config.yaml` → `tariff.contract_demand_kva`) so it has something real to
   catch.

6. **A float64 pandas column can't hold Python `None`** — `df.where(pd.notnull(df), None)`
   silently coerces right back to `NaN`, which Starlette's `JSONResponse`
   (strict `allow_nan=False`) then rejects with a 500. Fixed in `api/main.py`'s
   `_records()` helper, which does the NaN→None substitution on the
   plain-dict records *after* `.to_dict()`, not on the DataFrame. If you add a
   new endpoint returning a DataFrame with any nullable numeric column, route
   it through `_records()`.

7. **Tremor was evaluated and rejected for the frontend**: its peer dependency
   is React `^18.0.0` and it predates Tailwind v4's CSS-first config; this
   template runs React 19 + Tailwind v4. Installing it needs
   `--legacy-peer-deps` and pulls in 117 packages while removing a few the
   template's own tooling uses. The user explicitly chose Recharts (already
   in the template) instead when asked. Don't re-introduce Tremor without
   re-checking this.

## Known open issues (not hidden, flagged in README/validator output too)

- **`validate.py` is 8/9**, not 9/9. The failing check: night base load reads
  ~43% of day load against a 15–25% target. Root cause: the compressed-air
  system's background leak runs around the clock. Documented, not silently
  passed.
- **No browser-based visual QA has ever been done on the dashboard.** All
  frontend verification was `tsc --noEmit`, a full production build
  (`npm run build`), and direct API curl testing. No screenshot tool was
  available in any session so far. If you get browser tooling, that's the
  single highest-value next check.
- **`web_template/` should be named `web/`**. OneDrive held a file lock on
  the directory across multiple sessions (re-syncs on every file change
  inside it); two rename attempts both failed (`Device or resource busy` /
  `Permission denied`) even after stopping the dev server. No code depends on
  the literal folder name — purely cosmetic, fix opportunistically if OneDrive
  ever releases the lock.
- **`rollup_daily_plant`'s Scope 1/2/cost columns are whole-plant totals
  broadcast onto every plant row** — not a genuine per-site split. Only kWh
  is truly per-plant in the current rollups. The API (`/plants/compare`) and
  the frontend both only expose kWh per-plant for exactly this reason — don't
  add a per-plant Scope 1/2 chart without first implementing a real per-plant
  split in the generator.
- **The day-ahead forecaster's WAPE (~68%) is mostly irreducible noise**, not
  a bug: the generator randomizes CNC cutting minutes and paint-booth batch
  timing independently per day, which no calendar/weather feature can predict
  24h ahead. Confirmed against a naive climatology baseline (72% WAPE) — the
  model's edge over it is small but real.

## Running the full pipeline from scratch

```bash
pip install numpy pandas pyyaml scikit-learn lightgbm fastapi uvicorn reportlab

python build_db.py --scenario baseline
python build_db.py --scenario optimized
python validate.py                          # expect 8/9

python ml/anomaly.py
python ml/forecast.py
python -m ml.recommendations                # NOTE: -m flag required, writes recommendations.csv

python -m uvicorn api.main:app --port 8000  # keep running

cd web_template && npm install && npm run dev   # keep running, separate terminal
```

Full regen of both DBs + all ML takes several minutes (recommendations.py
alone runs ~8 full counterfactual simulations).

## If the user asks you to...

- **"fix the night/day validate check"** — start in `generator/compressor.py`,
  the auto-stop/leak logic. Read decision #3 above first.
- **"add a new page/view"** — follow the pattern in `web_template/src/features/*`,
  wire a route in `web_template/src/routes/_authenticated/`, add any new API
  need to `api/main.py` (route through `_records()` if it returns a
  DataFrame), and add the client type+hook to `lib/kpcl-api.ts` /
  `hooks/use-kpcl.ts`.
- **"the numbers look wrong"** — check README.md section 6 first; it's very
  likely a documented assumption, not a bug.
- **"deploy this" / "make it production-ready"** — it isn't, and wasn't
  designed to be. No auth, no real data pipeline, SQLite files checked into
  the working directory, API has no rate limiting. Flag this plainly if asked.

## Added after the original handoff (live demo + decision-support features)

- `api/live.py` — simulated live replay: a global server clock walks the 15-min data; SSE `/live/stream`, `/live/snapshot`, `/live/control`, `/live/fault-windows`. UI: `/live` (Live Monitor).
- `ml/peak_shaving.py` — day-level peak-shaving planner (`/schedule/days`, `/schedule/plan`). Uses the forecast where it covers the day, else actuals. Shifts keep daily energy constant, so savings are demand-charge exposure + ToD rate only.
- `ml/losses.py` — leak and anomaly-excess costing (`/losses/*`, UI `/losses`). CMP-SCR-01 is a standby unit, so its leak is costed at fleet median specific power. Leak cost and anomaly excess overlap — never add them.
- `ml/whatif.py` — `python -m ml.whatif` writes `whatif_grid.csv` / `whatif_baseline.csv` (14 full-year sims, parallel, a few minutes). `/whatif/grid` 503s until it has been run.
- First browser QA done (headless Playwright/Chromium). Known data oddity, not fixed: overview solar generation is a flat step with no day-to-day weather variation.

## Per-plant dashboards and reports

- `generator/plants.py` splits the company main meter into `fact_plant_meter` (written by `build_db.py`; both DBs were rebuilt). Plant kW/kVA/cost = main meter x the plant's share of metered asset load; Scope 2 and the solar credit follow that share; Scope 1 follows asset ownership. Plants sum exactly to the main meter. It is an allocation, not a separate simulation.
- Per-plant contract demand lives in `config.yaml` -> `plants[].contract_demand_kva` (assumed; `tariff.contract_demand_kva` stays the company aggregate). `ml/plant_cfg.py` holds the shared helpers.
- API: nearly every endpoint takes `?plant=<id>|ALL`; new `/plants` and `/reports/plant` (PDF). Startup trains 4 forecasters (company + each plant) and builds 4 peak planners. Per-plant day-ahead forecasts are weak (small, noisy loads).
- `recommendations.csv` / `whatif_grid.csv` / `whatif_baseline.csv` have a `plant_id` column; a plant only gets actions on assets it owns (`ACTION_ASSETS`, `LEVER_ASSETS`) — otherwise allocation noise leaks tiny spurious savings into plants that can't act. Regenerate with `python -m ml.recommendations` and `python -m ml.whatif` (both parallel).
- Frontend: `PlantProvider` (`context/plant-context.tsx`) + header `PlantSwitcher`; hooks in `hooks/use-kpcl.ts` read the plant themselves. Pages show `NoEquipment` when the plant has none of the asset type.
- Known limits: Saswad's only schedulable loads are chillers, so its peak-shaving plan has no actions; Nashik has no production records so kWh/unit is blank.

## Android alert app + detailed plant report

- `android/` — native Kotlin app (no libraries): foreground service holds `/live/stream?plant=` (SSE), posts heads-up notifications on an alarm-sound channel + a loud beep. Build: `cd android && gradle assembleDebug` (needs JDK 17+/21 and the Android SDK; AGP 8.7.2, Kotlin 2.0.21, Gradle 8.9). CI: `.github/workflows/build-apk.yml`. Pre-built APK: `android/dist/KPCL-Plant-Alert-debug.apk`. Tested on the Pixel_6 emulator (API 33): live status, breach alert, server-down alert, auto-reconnect. Not yet tested on a physical phone. The API must be started with `--host 0.0.0.0` for a phone on the LAN.
- `api/reports.py` — `/reports/plant?plant=` now returns a ~4-page management report (summary, ToD cost, demand vs contract + peak-shaving plan, emissions, equipment, losses, recommendations, data quality, assumptions, sign-off block).
