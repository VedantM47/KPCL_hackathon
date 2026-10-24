# KPCL Energy Dashboard — Database & Generator Reference

> All data described here is a **benchmark-calibrated simulation**. Nothing in
> `kpcl_energy.db` / `kpcl_energy_optimized.db` is real KPCL plant data.
> Ratings, tariffs, and emission factors are config placeholders — see
> `config.yaml` and the README's Assumptions section before quoting any number.

Two SQLite files are produced by `build_db.py`:

| File | Scenario | Meaning |
|---|---|---|
| `kpcl_energy.db` | `baseline` | current/unoptimized policy settings |
| `kpcl_energy_optimized.db` | `optimized` | same seed, same faults, different policy (lower pressure setpoint, off-peak test rig, CNC idle shutdown, earlier furnace start, SCR-lead chiller sequencing) |

The only thing that differs between the two files is **policy** (see
`config.yaml` → `policy.baseline` / `policy.optimized`). Same RNG seed, same
weather, same production plan, same fault schedule in both — so any kWh/Rs/tCO2
difference between the two databases is a real, traceable "saving" caused by
the policy change, not noise.

---

## 1. How the data is produced (pipeline order)

```
config.yaml
   │
   ▼
generator/calendar.py    → 1-minute frame, 365 days, shift/holiday/maintenance flags
   │
   ▼
generator/weather.py     → ambient temp, humidity, wet-bulb, irradiance (synthetic, Pune/Saswad)
   │
   ▼
generator/production.py  → daily units per product family, production-driven air demand
   │
   ▼
generator/faults.py      → boolean minute-level masks for each configured fault + grid outage windows
   │
   ▼
generator/simulate.py    → orchestrates every asset physics module below, at 1-minute resolution
   │  ├─ compressor.py   (CMP-CENT-01, CMP-SCR-01, CMP-REC-01, TEST-RIG-CNG-01)
   │  ├─ chiller.py      (CHILLER-SCR-01, CHILLER-VAM-01)
   │  ├─ furnace.py      (FURNACE-HT-01)
   │  ├─ paint_booth.py  (PAINT-BOOTH-01)
   │  ├─ cnc.py          (CNC-GEAR-01)
   │  ├─ solar.py        (SOLAR-SASWAD-01)
   │  ├─ main_meter.py   (sum of all of the above + unmetered losses − solar self-consumption)
   │  └─ noise.py        (measurement realism: noise, missing data, frozen sensors, meter drift)
   │
   ▼
generator/fuel_events.py → Scope-1 fuel events (furnace LPG, VAM gas, refrigerant top-up, DG diesel)
generator/emissions.py   → Scope 1 / Scope 2 / solar-avoided tCO2 per 15-min interval
   │
   ▼
build_db.py              → aggregates 1-min → 15-min, writes SQLite schema + rollups
```

Everything is simulated **internally at 1-minute resolution** and only
aggregated to 15 minutes at the very end, because compressor load/unload
cycling and furnace thermostat cycling happen faster than 15 minutes and
would otherwise be averaged away.

---

## 2. Database schema

### Dimension tables

**`dim_plant`** — `plant_id, name, city, division`
The three sites: HADAPSAR (compressors/CNC/furnace/paint), SASWAD
(chillers/solar), NASHIK (CMP-REC-01, TEST-RIG-CNG-01).

**`dim_asset`** — `asset_id, type, plant_id, rated_kw, rated_m3_per_min, rated_tr, rated_kwp, extra_json`
One row per of the 10 simulated assets. Only the rating columns relevant to
that asset's type are populated; everything else (idle fractions, fuel type,
role, default start times) is packed into `extra_json`.

**`dim_tariff`** — `period_name, start_hhmm, end_hhmm, rate_rs_per_kwh, contract_demand_kva, demand_charge_rs_per_kva, source_note`
5 ToD periods (off-peak/normal/peak/normal2/peak2). `source_note` plainly
states this is an illustrative tariff, not an official MSEDCL/KPCL tariff order.

**`dim_emission_factor`** — `factor_name, value, unit, source, version, year`
grid, diesel, lpg, natural_gas, refrigerant_r410a_gwp — each with a `source`
string ending in "VERIFY before use".

### Fact tables (all at 15-minute resolution unless noted)

**`fact_meter`** — `ts, asset_id, kW, kWh, state, dq_flag`
The unified per-asset meter reading used for rollups and the dashboard's
asset-level views. 35,040 rows per asset (365 days × 96 intervals/day) × 9
non-solar assets = 315,360 rows, **plus** SOLAR-SASWAD-01's generation also
recorded here (10 assets × 35,040 = 350,400 total). `dq_flag` is one of
`ok | missing | frozen | drift`. ~1-3% of rows per asset have `kW`/`kWh` = NULL
(`dq_flag='missing'`) — this is intentional measurement realism, not a bug;
`validate.py` check #1 corrects for it before checking the energy balance.

**`fact_compressor`** — `ts, asset_id, kW, pressure_bar, pressure_bar_min, pressure_bar_max, flow_m3min, leak_flow_m3min, specific_power_kwh_m3, load_fraction, cycle_count, sequencing_state`
One row per 15-min interval for each of CMP-CENT-01, CMP-SCR-01, CMP-REC-01,
TEST-RIG-CNG-01. `cycle_count` is the number of load-start events inside that
15-min window (captured because the underlying control loop runs at 1-minute
resolution). `sequencing_state` is `lead`, `lag`, or `standalone` (test rig).

**`fact_chiller`** — `ts, asset_id, TR, kW, kw_per_tr, COP, chw_supply_c, chw_return_c, condenser_approach_c, refrigerant_charge_kg, kW_electrical, kWh_thermal, thermal_cop, fuel_kg, fuel_type`
CHILLER-SCR-01 populates the electric-chiller columns (`TR, kW, kw_per_tr,
COP, chw_*, condenser_approach_c, refrigerant_charge_kg`); CHILLER-VAM-01
populates the heat-driven columns (`kW_electrical, kWh_thermal, thermal_cop,
fuel_kg, fuel_type`). `COP` is recomputed from the aggregated `TR`/`kW` (not
averaged per-minute) so `COP = TR*3.517/kW` holds exactly at 15-min resolution.

**`fact_furnace`** — `ts, batch_id, batch_mass_kg, setpoint_temp_c, state, kW, fuel_kg`
`state` ∈ `off | ramp | hold | cooldown`. `batch_id=0` means no batch running
in that interval.

**`fact_paint_booth`** — `ts, kW, air_draw_m3min, fan_running, oven_on`
`air_draw_m3min` is also fed into the Hadapsar compressor header's demand —
the two always agree by construction.

**`fact_solar`** — `ts, kW_generated, kW_self_consumed, kW_exported`

**`fact_weather`** — `ts, ambient_temp_c, ambient_temp_c_min/max, humidity_pct, wet_bulb_c, wet_bulb_c_min/max, irradiance_kw_m2`

**`fact_production`** — `date, shift, family, plant_id, units, is_surge`
Daily/shift granularity (not 15-min) — one row per (date, shift, product
family). `is_surge=1` flags the ~3%/day hard-negative production-surge days.

**`fact_fuel_event`** — `asset_id, ts, fuel_type, amount_kg, note`
Furnace LPG per batch, VAM gas daily totals, one refrigerant top-up event
(`fuel_type='r410a_topup'`) after the refrigerant-leak fault window, and DG
diesel litres (`fuel_type='diesel_litre'`) during injected grid outages.

**`fact_fault_label`** — `asset_id, fault_type, start_ts, end_ts, magnitude, label_class`
11 rows: 8 real faults (`label_class='fault'`) + 3 hard negatives
(`label_class='normal'`, `asset_id=NULL`) — production surge, heat wave,
planned maintenance day. These are what `ml/anomaly.py` is scored against.

**`fact_emissions`** — `ts, scope1_tco2, scope2_tco2, solar_avoided_tco2`

**`fact_main_meter`** — `ts, kW, kVA, pf, peak_flag, cost_rs`
`peak_flag=1` when `kVA` exceeds `dim_tariff.contract_demand_kva`.

### Rollup tables (pre-computed so the dashboard loads fast)

**`rollup_hourly_asset`** — `ts_hour, asset_id, kWh, max_kW`
**`rollup_daily_asset`** — `date, asset_id, kWh, max_kW`
**`rollup_daily_plant`** — `date, plant_id, kWh, scope1_tco2, scope2_tco2, cost_rs`
(`scope1_tco2`/`scope2_tco2`/`cost_rs` are whole-plant daily totals joined
onto each plant's row — not yet split per-plant; a known simplification.)

### Indexes
`(asset_id, ts)` on `fact_meter`, `fact_compressor`, `fact_chiller`;
`(ts)` on `fact_main_meter`, `fact_emissions`; `(asset_id, date)` on
`rollup_daily_asset`.

---

## 3. Generator folder — module by module

| Module | Produces | Key relation(s) enforced |
|---|---|---|
| `calendar.py` | 1-min frame: `ts, shift, is_holiday, is_maintenance_day, is_sunday, is_saturday, is_production` | Shift A 06:00-14:00, B 14:00-22:00; Sunday off; Saturday half-day (shift A only); 6 holidays; 3 maintenance days |
| `weather.py` | `ambient_temp_c, humidity_pct, wet_bulb_c, irradiance_kw_m2` | Seasonal + diurnal sinusoids, monsoon (Jun-Sep) humidity/irradiance dip, Stull wet-bulb approximation |
| `production.py` | daily units per family; air demand (m³/min) per (date, shift) | `units ~ Normal(mean, std)`, surge days multiply units 1.4-1.8× |
| `faults.py` | boolean masks per `(asset_id, fault_type)`; grid-outage mask; `fact_fault_label` rows | Window = `[start, end]` inclusive, built from `config.yaml → faults` / `hard_negatives` / `grid_outages` |
| `compressor.py` | per-asset `kW, pressure_bar, flow_m3min, leak_flow_m3min, specific_power_kwh_m3, load_fraction, cycle_count` | Bang-bang pressure hysteresis control loop (1-min step); `kW = idle_kW + load_frac×(full−idle)`, scaled by `1+(pressure−7)×0.065` overpressure penalty; leak = slow background drift (lead asset) + fault-accelerated ramp (faulted asset); auto-stop timer drops idling leads to standby after 5 min unloaded |
| `chiller.py` | SCR: `TR, kW, kw_per_tr, COP, chw_*, condenser_approach_c, refrigerant_charge_kg`; VAM: `TR, kW_electrical, kWh_thermal, thermal_cop, fuel_kg` | `TR = 0.3307×flow_m3h×ΔT`; `COP = TR×3.517/kW`; VAM thermal COP ∈ [0.7, 1.2] |
| `furnace.py` | `batch_id, batch_mass_kg, setpoint_temp_c, state, kW, fuel_kg` | ramp(75min)/hold(180min)/cooldown(90min) per batch; fuel ∝ `mass × ΔT / efficiency` |
| `paint_booth.py` | `kW, air_draw_m3min, fan_running, oven_on` | Fan kW while shift active (+overrun fault); 1-4 oven batches/day |
| `cnc.py` | `kW, state, units_produced` | states `off/idle/cutting`; idle kW drifts 3→8 kW under fault |
| `solar.py` | `kW_generated, kW_self_consumed, kW_exported` | irradiance × panel efficiency × temp derate, capped by inverter rating |
| `main_meter.py` | `kW, kVA, pf, unmetered_kw`; tariff cost + peak flag | `main = Σassets × (1+unmetered%) − solar_self_consumed`; `kVA = kW/pf` |
| `noise.py` | `dq_flag`, degraded value columns | 1-3% missing, meter drift on one designated asset |
| `fuel_events.py` | `fact_fuel_event` rows | furnace batches, VAM daily gas, refrigerant top-up, DG diesel during outages |
| `emissions.py` | `scope1_tco2, scope2_tco2, solar_avoided_tco2` | Scope2 = grid kWh × grid factor; Scope1 = Σfuel×factor + refrigerant×GWP |
| `simulate.py` | orchestrates all of the above into one `simulate(config, policy_name)` call | same RNG seed for baseline/optimized so only *policy* differs between the two output DBs |

### Known simplifications (documented, not hidden)
- Noise/missing-data/drift are applied **after** aggregating to 15-min, not at
  1-min resolution — a reasonable approximation for a sensor/telemetry layer,
  but means a "frozen" stretch is a frozen 15-min reading, not a frozen
  1-min one.
- `rollup_daily_plant`'s emissions/cost columns are whole-plant totals
  broadcast onto each plant's row rather than split per-plant.
- `weekend_baseload_waste` (one of the 8 faults) has no distinct physical
  effect implemented beyond the pre-existing leak-driven weekend cycling —
  it passes `validate.py` check #7 trivially rather than from a dedicated
  mechanism. Worth a real implementation before this claim is used in a demo.
- Night/day base-load ratio (`validate.py` check #2) currently reads ~0.43
  against a 0.15-0.25 target; the gap traces to the compressed-air system's
  background leak being present around the clock. Flagged, not silently
  passed.
