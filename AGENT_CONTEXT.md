# Agent Context — KPCL Energy Dashboard Project

> **Read this first if you're a fresh agent picking up this project.** It's a
> handoff document, not user-facing documentation. For humans see
> [README.md](README.md) (assumptions), [HOW_TO_RUN.md](HOW_TO_RUN.md) (start the web
> app + phone app), [DATABASE_AND_GENERATOR.md](DATABASE_AND_GENERATOR.md) (schema +
> physics) and [android/README.md](android/README.md) (phone app). This file says
> where things stand, why they're built the way they are, and what to watch for.

## What this project is

A hackathon prototype for Kirloskar Pneumatic Company Limited (KPCL), answering
"AI-driven carbon accounting and intelligent energy management": a synthetic
(not real) 365-day, 15-minute energy dataset for a 10-asset, three-plant
(Hadapsar / Saswad / Nashik) industrial company, with Scope 1/2 carbon
accounting, anomaly detection, day-ahead load forecasting, ranked savings
recommendations, a FastAPI backend, a React dashboard, per-plant PDF reports and
an Android alert app. Every number is labeled "benchmark-calibrated simulation" —
a hard, explicit user requirement. Never let a number from this project get
quoted as if it were real KPCL data.

All originally planned stages are complete, and the following were added later:
live replay monitor, peak-shaving planner, loss tracker, what-if simulator,
per-plant dashboards/reports, Android app, one-command demo launcher. It is a
"understand what exists, then do what the user asks next" handoff.

## How to run it (details in HOW_TO_RUN.md)

One command, from an **Administrator** PowerShell (admin = firewall rule for the phone):

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\imved\OneDrive\Desktop\KPCL\run-demo.ps1"   # add -Breach to jump the replay to the peak day
```

`run-demo.ps1` frees ports 8000/5173, starts the API (`--host 0.0.0.0`) and the
dashboard (via `cmd`, because a fresh PowerShell window blocks `npm.ps1`), waits
for both, and prints the addresses. Dashboard: http://localhost:5173 ; phone
server address on the user's laptop hotspot: `http://192.168.137.1:8000`.

- Startup trains 7 Isolation Forests + the walk-forward forecasters (~30 s). They are **cached** in
  `.cache/startup_models.pkl` (keyed on DB/config/model-code fingerprints); first start ~1-2 min,
  later starts seconds. Delete `.cache/` to retrain.
- **The user prefers to run commands themselves** ("give me the command, I'll run it"). Don't
  launch the demo script, servers, or git pushes on their behalf unless they ask; implement, then give the command.
- Shell tooling gotcha: Python snippets with apostrophes/`'''` inside a Bash heredoc break the
  tool's quoting — write patch scripts to a file with the Write tool and run them instead.

## Directory map

```
config.yaml                 single source of truth: ratings, setpoints, calendar, faults, tariff,
                             emission factors, plants (incl. per-plant contract_demand_kva) — every
                             assumed value is tagged `# assumed` / `VERIFY`
generator/                  the simulation (1-minute internal resolution)
  calendar weather production compressor chiller furnace paint_booth cnc solar
  main_meter noise faults fuel_events emissions simulate
  plants.py                  splits the company meter into per-plant meters (allocation, see below)
build_db.py                 aggregates 1-min -> 15-min, writes SQLite incl. fact_plant_meter
validate.py                 8 PASS/FAIL checks (currently 8/9 — see Known issues)
ml/
  anomaly.py                 IsolationForest + rules, evaluated vs fact_fault_label
  forecast.py                walk-forward day-ahead forecast: mean + conformal P10-P90 band per 15 min,
                             daily-peak quantile model -> breach risk (company + per plant)
  recommendations.py         ranked actions from real counterfactual re-simulations (parallel, per plant)
  whatif.py                  one-lever-at-a-time simulation grid -> whatif_grid.csv / whatif_baseline.csv
  peak_shaving.py            day-level peak-shaving schedule planner
  losses.py                  leak + anomaly-excess costing (kWh / Rs / kgCO2)
  plant_cfg.py               shared plant helpers (ALL, assets_of, contract_kva)
api/
  main.py                    FastAPI backend; almost every endpoint takes ?plant=<id>|ALL
  live.py                    simulated live replay (SSE) + control + demo alert injection
  reports.py                 detailed per-plant management PDF
web_template/                React 19 + Vite + TanStack Router + Tailwind v4 dashboard (plain tracked files now)
android/                     native Kotlin phone app (see below); APK in android/dist/
.github/workflows/build-apk.yml   builds the APK on GitHub; tag v* publishes a Release
run-demo.ps1 / HOW_TO_RUN.md      launcher + run guide
kpcl_energy[_optimized].db   generated, ~100 MB each, NOT in git (rebuild with build_db.py)
recommendations.csv whatif_grid.csv whatif_baseline.csv   generated; carry a plant_id column
.cache/                      pickled trained models (git-ignored)
```

## How the pieces connect

```
config.yaml -> generator/simulate.py -> build_db.py (15-min, + generator/plants.py per-plant split)
   -> kpcl_energy[_optimized].db -> ml/* (anomaly, forecast, peak_shaving, losses; recs/whatif via re-simulation)
   -> api/main.py (+ live.py SSE, reports.py PDF) -> web_template (port 5173) and android app (SSE)
```

Two databases exist because the "savings" story is a diff between them: same seed, same
faults, only the **policy** differs (`config.yaml` `policy:` block).

## Key decisions made along the way (read before changing physics or config)

1. **Timezone bug**: tz-aware timestamps written to SQLite are silently converted to UTC,
   shifting hour-of-day by +5:30. Fixed by stripping the tz label right after generating the
   minute frame (`calendar.py`). If day/night looks shifted ~5.5 h, check this first.
2. **Compressor control loop**: turn-off originally needed an unrealistic demand drop, so the
   lead compressor pinned at the pressure ceiling. Fixed to bang-bang hysteresis.
3. **Leak growth was too aggressive** (45% of rated flow by year-end). Two constants now (slow
   background drift, faster fault-specific rate) plus retuned flow ratings.
4. **Chiller sequencing** in the shipped "optimized" policy flipped to `SCR_lead` and made it
   use 46% *more* energy, contradicting the savings story. Kept identical between baseline and
   optimized; the tradeoff is surfaced honestly as its own recommendation. Don't re-enable it.
5. **Contract demand 1500 kVA vs ~430 kVA peak** made breach flagging dead. Company contract
   is 400 kVA; per-plant contracts (Hadapsar 280, Saswad 80, Nashik 70) are assumed.
6. **float64 columns can't hold None**: `df.where(notnull, None)` coerces back to NaN and
   Starlette's strict JSON then 500s. Use `_records()` in `api/main.py`; in `api/live.py` use `_r()`.
7. **Tremor rejected** (React 18 peer dep, pre-Tailwind-v4); Recharts it is.
8. **Per-plant meters are an allocation, not a simulation** (`generator/plants.py`): plant
   kW/kVA/cost = main meter x the plant's share of metered asset load per interval; Scope 2 and
   solar credit/avoided follow the same share (virtual net-metering assumption); Scope 1 follows
   asset ownership. Plants sum exactly to the company meter. Because of this, **a plant only
   gets recommendations/what-if levers on assets it owns** (`ACTION_ASSETS`, `LEVER_ASSETS`) —
   otherwise allocation noise leaks tiny spurious savings into plants that can't act.
9. **Leak costing**: leak flow x specific power x 60, "avoidable" = above each compressor's
   5th-percentile floor. CMP-SCR-01 is a standby unit (kW=1, flow 0) so its leak is costed at the
   fleet median specific power. Leak cost and anomaly excess **overlap — never add them**.
10. **Anomaly excess** uses "normal for that (weekday, hour)" computed over *all* intervals, not
    non-flagged ones — the CNC rule flags most working intervals, so a non-flagged baseline would
    be the idle level and inflate the excess ~10x.
11. **Peak-shaving** shifts an asset's whole daily profile in time (energy unchanged), so savings
    are demand-charge exposure + ToD rate only; CO2 is unchanged. On non-risk days it optimises
    ToD cost, on risk days (>85% of contract) it minimises peak kVA first.
12. **Live alerts fire once per anomaly run** (not every flagged interval) or the ticker spams.
    Anomaly severity is the score's percentile *within its own asset* (`live.score_severity`: top 5%
    critical) — fixed score bins put all 40k flagged rows in "critical" and paged the phone every few
    seconds. An anomaly START is never critical; it escalates to critical only at 24 h of persistence.

## Known open issues

- **`validate.py` is 8/9**: night base load ~43% of day load vs 15–25% target (compressed-air
  leak runs around the clock). Documented, not silently passed. Start in `generator/compressor.py`.
- **Forecasting (rebuilt 2026-10-25)**: walk-forward, retrained monthly from March on past data only
  (Jan-Feb = "no forecast", never back-filled). Target is load / trailing-7-day mean (follows drift).
  Mean model for the line (a median under-counts bursty CNC energy), quantile models + conformal
  calibration from *earlier* folds for an ~80% band, and a separate daily-peak quantile model whose
  quantiles give `breach_risk`. 15-min shape stays hard (generator randomises CNC/paint timing), so
  judge it on peaks: bias ~0 (old: -80 kVA), Hadapsar near-contract days 131/139 warned (old 2/35 in
  its window). Breaches remain hard except Saswad. Nashik daily-energy error ~43% is the plants.py
  allocation (CV 0.62 vs metered 0.18), not the model. `/schedule/days` ranks by metered peak by
  default ON PURPOSE: the phone's "Jump to peak day" needs a day that really breached (tested).
  `tests/test_forecast.py` includes a no-leakage test (perturb day D onward, D's forecast unchanged).
- **Solar generation chart** on the overview is a flat step with no day-to-day weather variation —
  looks like a generator limitation, not changed.
- Saswad's only schedulable loads are chillers, so its peak-shaving plan has no actions; Nashik has
  no production records so kWh/unit is blank.
- `config.yaml` strings that contain "—" were mojibake when read without `encoding="utf-8"`;
  `api/main.py` now reads it as UTF-8 (other `open("config.yaml")` calls in ml/*.py may not).
- `ml/forecast.py` etc. use `from ml import plant_cfg`, so run them as `python -m ml.forecast`
  (not `python ml/forecast.py`).
- Not production-ready: no auth, SQLite files in the working dir, open CORS, no rate limiting.
- web_template's original nested `.git` (shadcn-admin upstream) was moved to
  `.web_template_git_backup/` (git-ignored) so the dashboard source is tracked normally.

## Phone app (android/)

Native Kotlin, no libraries. `WelcomeActivity` (first-launch setup: server address, notification
permission) -> `MainActivity` (live card, big start/stop, connection settings, demo tools, alert
cards, "Setup guide" link). `MonitorService` is a foreground service holding
`GET /live/stream?plant=` (SSE) with reconnect/backoff; `Notifier` posts heads-up notifications on the
`critical_v2` channel. **Hard user requirement (2026-10-25): ONLY critical conditions notify and vibrate.**
Critical = contract breach, a machine anomaly that has persisted 24 h (`anomaly_sustained`), or a dashboard
demo alert. `AlertGate` (pure Kotlin, `Model.kt`) pages a breach once per episode (re-arms after >4 ticks
clear or a replay jump) and each event key once. Everything else (>85% contract, PF, anomaly start, leaks,
server lost) is shown silently. `AlarmPlayer` = ALARM-usage vibration pulses + optional looping alarm sound
until ACKNOWLEDGE / 2 min. Frames carry `status` and alerts carry `kind` + stable `key` (api/live.py).
`DevConsoleActivity` = developer console (live fields / dataset / glossary from `api/devconsole.py`;
`tests/` checks every DB column has an explanation, so new columns must be added to `TABLES`).
v2.0 tested on the Pixel_6 AVD with a scripted adb/uiautomator run tapping every button (55/55 checks).
Icon: bolt-in-ring adaptive vector (+ monochrome layer), no PNGs.
- Build: `cd android && gradle assembleDebug` (JDK 17+/21, Android SDK, AGP 8.7.2, Kotlin 2.0.21,
  Gradle 8.9; `local.properties` needs forward slashes: `sdk.dir=C:/Users/...`). Local build uses
  Android Studio's JBR as JAVA_HOME. CI builds on GitHub; tag `v1.x` -> Release with
  `KPCL-Plant-Alert.apk`. Released so far: `v1.0` (an older build); the nicer-UI/vibration-fix/
  welcome-screen build exists only in `android/dist/` until pushed + tagged.
- Tested on the Pixel_6 AVD (API 33, `-no-window`, WHPX): live status, breach alert, ack, server-down
  alert + reconnect, welcome/main/launcher-icon visuals. **Not tested on a physical phone**; alarm
  loudness untested (emulator has no audio). Emulator reaches the host at `10.0.2.2`.

## Demo tools

- Dashboard Live Monitor: pause/play, 1x/4x/16x, "Jump to fault…", and a red **Simulate critical
  alert** button → `POST /live/simulate-alert` → every connected SSE client (web + phone) gets a
  `demo: true` frame with a unique `DEMO-n` asset id (unique so the app's per-key cooldown never swallows it).
- App: Test alert (local) and Jump to peak day (`/schedule/days` + `/live/control`).
- `run-demo.ps1 -Breach` jumps the replay to the highest-demand day.

## Reports

`/reports/plant?plant=` → ~4-page PDF (`api/reports.py`, reportlab only): auto-written summary, KPIs,
monthly energy/cost + ToD split, weekday load profile vs contract, top-5 peak days, peak-shaving plan,
Scope 1/2, equipment breakdown, leaks/anomalies, recommendations, data quality, assumptions, sign-off.
`/carbon/report?format=csv|pdf&plant=` is the shorter BRSR-style export. Rendering check: `pypdfium2`
(`pdftoppm` is not installed).

## Running the full pipeline from scratch

```bash
pip install numpy pandas pyyaml scikit-learn lightgbm fastapi uvicorn reportlab
python build_db.py --scenario baseline
python build_db.py --scenario optimized
python validate.py                  # expect 8/9
python -m ml.recommendations        # parallel, several minutes, writes recommendations.csv (per plant)
python -m ml.whatif                 # parallel, several minutes, writes whatif_grid.csv / whatif_baseline.csv
# then run-demo.ps1, or: python -m uvicorn api.main:app --host 0.0.0.0 --port 8000  +  cd web_template && npm install && npm run dev
```

If you change the data/config, delete `.cache/` so the models retrain.

## If the user asks you to...

- **"fix the night/day validate check"** — `generator/compressor.py` auto-stop/leak logic; read decision #3.
- **"add a new page/view"** — follow `web_template/src/features/*`, wire a route in
  `web_template/src/routes/_authenticated/`, add a sidebar entry in `components/layout/data/sidebar-data.ts`,
  add the API need to `api/main.py` (take `plant`, use `_records()`), and the client type/function to
  `lib/kpcl-api.ts` + a hook in `hooks/use-kpcl.ts` (hooks read the selected plant from `usePlant()`).
- **"the numbers look wrong"** — README.md section 6 first; probably a documented assumption.
- **"change the phone app"** — Kotlin sources in `android/app/src/main/java/com/kpcl/plantalert/`; rebuild,
  copy to `android/dist/`, then give the user the commit/push/tag commands.
- **"deploy / production-ready"** — it isn't; flag the issues above plainly.
- **Browser QA** — headless Playwright (python) + Chromium works here; screenshots under the session scratchpad.
