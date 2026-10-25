"""Developer console: browse the simulated dataset table by table, with a
plain-English explanation of every table, column and term. Used by the phone
app's "Developer console" screen.

Everything here describes the benchmark-calibrated SIMULATION — none of it is
real KPCL telemetry. Table names are checked against TABLES before they reach
SQL, so the browse endpoint cannot be used to run arbitrary queries.
"""
import sqlite3

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/dev", tags=["developer console"])

DB = "kpcl_energy.db"
DATA_LABEL = "benchmark-calibrated simulation (not real KPCL data)"

# table -> (group, what one row is, {column: (unit, meaning)})
TABLES = {
    "dim_plant": ("Dimension", "One row per plant site.", {
        "plant_id": ("", "Short plant code used everywhere else (HADAPSAR, SASWAD, NASHIK)."),
        "name": ("", "Display name of the plant."),
        "city": ("", "City the plant is in."),
        "division": ("", "Business division the plant belongs to."),
    }),
    "dim_asset": ("Dimension", "One row per simulated machine (10 in total).", {
        "asset_id": ("", "Machine code, e.g. CMP-CENT-01 = centrifugal compressor no. 1."),
        "type": ("", "Kind of machine (compressor, chiller, CNC, furnace, paint booth, solar)."),
        "plant_id": ("", "Plant that owns the machine."),
        "rated_kw": ("kW", "Nameplate electrical power. Blank for machines rated another way."),
        "rated_m3_per_min": ("m³/min", "Nameplate air delivery of a compressor."),
        "rated_tr": ("TR", "Nameplate cooling capacity of a chiller (tons of refrigeration)."),
        "rated_kwp": ("kWp", "Peak DC capacity of the solar plant."),
        "extra_json": ("", "Other settings packed as JSON: idle fraction, fuel type, role, start times."),
    }),
    "dim_tariff": ("Dimension", "One row per time-of-day (ToD) tariff period. Illustrative, not an official tariff.", {
        "period_name": ("", "off_peak, normal, peak, normal2 or peak2."),
        "start_hhmm": ("HH:MM", "Period start time."),
        "end_hhmm": ("HH:MM", "Period end time."),
        "rate_rs_per_kwh": ("₹/kWh", "Energy charge during this period."),
        "contract_demand_kva": ("kVA", "Company demand limit agreed with the utility; exceeding it is penalised."),
        "demand_charge_rs_per_kva": ("₹/kVA", "Monthly charge per kVA of demand."),
        "source_note": ("", "Where the number comes from (marked VERIFY before use)."),
    }),
    "dim_emission_factor": ("Dimension", "One row per emission factor used for carbon accounting.", {
        "factor_name": ("", "grid, diesel, lpg, natural_gas or refrigerant GWP."),
        "value": ("", "The factor itself; see the unit column."),
        "unit": ("", "e.g. tCO2/MWh for grid power, kgCO2/kg for fuels."),
        "source": ("", "Reference the factor is based on (VERIFY before use)."),
        "version": ("", "Version of the source."),
        "year": ("", "Year the factor applies to."),
    }),
    "fact_main_meter": ("Fact · 15 min", "Company incoming meter, one row per 15-minute interval.", {
        "ts": ("", "Start of the 15-minute interval (local time, IST)."),
        "kW": ("kW", "Average real power drawn from the grid."),
        "kVA": ("kVA", "Average apparent power — what contract demand is measured in."),
        "pf": ("", "Power factor = kW ÷ kVA. Below 0.90 attracts a penalty."),
        "peak_flag": ("0/1", "1 when kVA is above the contract demand (a breach)."),
        "cost_rs": ("₹", "Energy cost of the interval at the ToD rate."),
    }),
    "fact_plant_meter": ("Fact · 15 min", "Per-plant meter, one row per plant per interval. An allocation of the company meter.", {
        "ts": ("", "Start of the 15-minute interval."),
        "plant_id": ("", "Plant the row belongs to."),
        "kW": ("kW", "Plant's share of grid real power."),
        "kVA": ("kVA", "Plant's share of apparent power (compared against the plant contract)."),
        "pf": ("", "Power factor of the plant."),
        "metered_load_kw": ("kW", "Sum of the plant's own machine meters (basis of the allocation)."),
        "cost_rs": ("₹", "Plant's share of energy cost."),
        "scope1_tco2": ("tCO2", "Direct emissions from fuel burnt at the plant."),
        "scope2_tco2": ("tCO2", "Indirect emissions from grid electricity."),
        "solar_avoided_tco2": ("tCO2", "Emissions avoided by solar power, shared by load."),
    }),
    "fact_meter": ("Fact · 15 min", "Per-machine meter, one row per machine per interval.", {
        "ts": ("", "Start of the 15-minute interval."),
        "asset_id": ("", "Machine the reading belongs to."),
        "kW": ("kW", "Average power. Blank when the reading is missing (data-quality realism)."),
        "kWh": ("kWh", "Energy in the interval = kW × 0.25 h."),
        "state": ("", "Operating state where the machine reports one (off, idle, cutting, ramp, hold, cooldown)."),
        "dq_flag": ("", "Data quality: ok, missing (no reading) or drift (meter slowly reading wrong)."),
    }),
    "fact_compressor": ("Fact · 15 min", "Air-compressor readings, one row per compressor per interval.", {
        "ts": ("", "Start of the 15-minute interval."),
        "asset_id": ("", "Compressor code."),
        "kW": ("kW", "Electrical power."),
        "pressure_bar": ("bar", "Average header air pressure. Every extra bar costs ~6.5% more power."),
        "pressure_bar_min": ("bar", "Lowest pressure inside the interval."),
        "pressure_bar_max": ("bar", "Highest pressure inside the interval."),
        "flow_m3min": ("m³/min", "Compressed air delivered."),
        "leak_flow_m3min": ("m³/min", "Part of that air lost through leaks — paid for but never used."),
        "specific_power_kwh_m3": ("kWh/m³", "Energy per cubic metre of air. Lower is more efficient."),
        "load_fraction": ("0–1", "Share of time the compressor was loaded (making air)."),
        "cycle_count": ("", "Number of load/unload starts in the interval."),
        "sequencing_state": ("", "lead (runs first), lag (backup) or standalone."),
    }),
    "fact_chiller": ("Fact · 15 min", "Chiller readings. The screw chiller fills the electric columns, the VAM chiller the heat-driven ones.", {
        "ts": ("", "Start of the 15-minute interval."),
        "asset_id": ("", "Chiller code."),
        "TR": ("TR", "Cooling delivered, tons of refrigeration (1 TR = 3.517 kW of cooling)."),
        "kW": ("kW", "Electrical power of the screw chiller."),
        "kw_per_tr": ("kW/TR", "Electricity per ton of cooling. Lower is better; rises with fouling."),
        "COP": ("", "Coefficient of performance = cooling kW ÷ electrical kW. Higher is better."),
        "chw_supply_c": ("°C", "Chilled-water temperature leaving the chiller."),
        "chw_return_c": ("°C", "Chilled-water temperature coming back."),
        "condenser_approach_c": ("°C", "Condenser temperature minus cooling-water temperature; grows with fouling."),
        "refrigerant_charge_kg": ("kg", "Refrigerant in the circuit; drops during a refrigerant leak."),
        "kW_electrical": ("kW", "Pumps/controls power of the VAM (heat-driven) chiller."),
        "kWh_thermal": ("kWh", "Heat energy fed to the VAM chiller."),
        "thermal_cop": ("", "VAM cooling output ÷ heat input."),
        "fuel_kg": ("kg", "Gas burnt to produce that heat."),
        "fuel_type": ("", "Fuel used by the VAM chiller."),
    }),
    "fact_furnace": ("Fact · 15 min", "Heat-treatment furnace readings.", {
        "ts": ("", "Start of the 15-minute interval."),
        "batch_id": ("", "Batch being treated; 0 = no batch."),
        "batch_mass_kg": ("kg", "Mass of parts in the batch."),
        "setpoint_temp_c": ("°C", "Target temperature."),
        "state": ("", "off, ramp (heating up), hold (at temperature) or cooldown."),
        "kW": ("kW", "Electrical power."),
        "fuel_kg": ("kg", "LPG burnt in the interval."),
    }),
    "fact_paint_booth": ("Fact · 15 min", "Paint booth readings.", {
        "ts": ("", "Start of the 15-minute interval."),
        "kW": ("kW", "Electrical power (fans + oven)."),
        "air_draw_m3min": ("m³/min", "Compressed air used by the booth."),
        "fan_running": ("0–1", "Share of the interval the exhaust fan ran."),
        "oven_on": ("0–1", "Share of the interval the curing oven was on."),
    }),
    "fact_solar": ("Fact · 15 min", "Rooftop solar at Saswad.", {
        "ts": ("", "Start of the 15-minute interval."),
        "kW_generated": ("kW", "Solar power produced."),
        "kW_self_consumed": ("kW", "Solar power used on site (reduces grid draw)."),
        "kW_exported": ("kW", "Surplus sent to the grid."),
    }),
    "fact_weather": ("Fact · 15 min", "Site weather.", {
        "ts": ("", "Start of the 15-minute interval."),
        "ambient_temp_c": ("°C", "Average outdoor air temperature."),
        "ambient_temp_c_min": ("°C", "Lowest temperature in the interval."),
        "ambient_temp_c_max": ("°C", "Highest temperature in the interval."),
        "humidity_pct": ("%", "Relative humidity."),
        "wet_bulb_c": ("°C", "Wet-bulb temperature; drives cooling-tower and chiller efficiency."),
        "wet_bulb_c_min": ("°C", "Lowest wet-bulb temperature in the interval."),
        "wet_bulb_c_max": ("°C", "Highest wet-bulb temperature in the interval."),
        "irradiance_kw_m2": ("kW/m²", "Sunlight power falling on the panels."),
    }),
    "fact_emissions": ("Fact · 15 min", "Company carbon emissions per interval.", {
        "ts": ("", "Start of the 15-minute interval."),
        "scope1_tco2": ("tCO2", "Scope 1: direct emissions from fuel burnt on site (LPG, gas, diesel, refrigerant)."),
        "scope2_tco2": ("tCO2", "Scope 2: emissions from grid electricity = grid kWh × grid factor."),
        "solar_avoided_tco2": ("tCO2", "Emissions avoided because solar replaced grid power."),
    }),
    "fact_production": ("Fact · per shift", "Units produced, one row per date × shift × product family.", {
        "date": ("", "Production date."),
        "shift": ("", "A = 06:00–14:00, B = 14:00–22:00."),
        "family": ("", "Product family (gearbox, compressor package, refrigeration package)."),
        "plant_id": ("", "Plant that produced it."),
        "units": ("units", "Units produced."),
        "is_surge": ("0/1", "1 on a production-surge day (high load that is NOT a fault)."),
    }),
    "fact_fuel_event": ("Fact · event", "Fuel and refrigerant events.", {
        "asset_id": ("", "Machine that used the fuel."),
        "ts": ("", "When it happened."),
        "fuel_type": ("", "LPG, gas, diesel_litre (generator during outages) or r410a_topup (refrigerant refill)."),
        "amount_kg": ("kg / litre", "Quantity (litres for diesel)."),
        "note": ("", "Free-text note."),
    }),
    "fact_fault_label": ("Fact · label", "Ground truth: injected faults and look-alike normal events the anomaly model is scored against.", {
        "asset_id": ("", "Faulty machine (blank for site-wide normal events)."),
        "fault_type": ("", "e.g. leak_growth, condenser_fouling, cnc_idle_drift, furnace_door_open."),
        "start_ts": ("", "Fault start."),
        "end_ts": ("", "Fault end."),
        "magnitude": ("", "Strength of the injected fault (meaning depends on the type)."),
        "label_class": ("", "fault = a real problem; normal = a hard negative that only looks unusual."),
    }),
    "rollup_hourly_asset": ("Rollup", "Pre-computed hourly energy per machine (for fast charts).", {
        "ts_hour": ("", "Start of the hour."),
        "asset_id": ("", "Machine code."),
        "kWh": ("kWh", "Energy in the hour."),
        "max_kW": ("kW", "Highest 15-minute power in the hour."),
    }),
    "rollup_daily_asset": ("Rollup", "Pre-computed daily energy per machine.", {
        "date": ("", "Day."),
        "asset_id": ("", "Machine code."),
        "kWh": ("kWh", "Energy in the day."),
        "max_kW": ("kW", "Highest 15-minute power in the day."),
    }),
    "rollup_daily_plant": ("Rollup", "Pre-computed daily totals per plant.", {
        "date": ("", "Day."),
        "plant_id": ("", "Plant code."),
        "kWh": ("kWh", "Energy in the day."),
        "scope1_tco2": ("tCO2", "Scope 1 emissions (company-wide figure; not yet split per plant)."),
        "scope2_tco2": ("tCO2", "Scope 2 emissions (company-wide figure; not yet split per plant)."),
        "cost_rs": ("₹", "Energy cost (company-wide figure; not yet split per plant)."),
    }),
}

# fields of one /live/stream frame — what the phone app actually receives
LIVE_FIELDS = [
    ("ts", "", "Simulated time of this reading (the replay walks through the year 15 minutes per tick)."),
    ("plant_id", "", "Plant this frame is for; ALL = the whole company."),
    ("plant.kW", "kW", "Real power drawn right now."),
    ("plant.kVA", "kVA", "Apparent power right now — compared against the contract."),
    ("plant.pf", "", "Power factor (kW ÷ kVA); below 0.90 is the penalty band."),
    ("plant.contract_kva", "kVA", "Contract demand limit for this plant."),
    ("plant.contract_pct", "%", "kVA as a share of contract. Above 100% = breach (critical)."),
    ("status", "", "normal, watch (above 85% of contract) or critical (contract breached)."),
    ("today.cost_rs", "₹", "Energy cost so far today."),
    ("today.scope1_tco2", "tCO2", "Scope 1 emissions so far today."),
    ("today.scope2_tco2", "tCO2", "Scope 2 emissions so far today."),
    ("solar_kw", "kW", "Solar power being generated (blank for plants without solar)."),
    ("ambient_c", "°C", "Outdoor temperature."),
    ("compressor.pressure_bar", "bar", "Air pressure of the plant's lead compressor."),
    ("compressor.specific_power", "kWh/m³", "Lead compressor energy per m³ of air."),
    ("compressor.leak_m3min", "m³/min", "Air escaping through leaks."),
    ("compressor.leak_kw", "kW", "Power wasted making the leaked air."),
    ("compressor.leak_rs_per_hr", "₹/h", "Money the leak costs per hour."),
    ("compressor.avoidable_leak_rs_per_hr", "₹/h", "Part of that above the normal background leak — what fixing leaks would save."),
    ("chiller_kw_per_tr", "kW/TR", "Screw chiller efficiency (blank for plants without it)."),
    ("assets[]", "", "Each machine in the plant with its power (kW) and state."),
    ("alerts[]", "", "Conditions raised on this tick, each with severity, kind and a message."),
    ("alerts[].severity", "", "low · medium · high · critical. Only critical makes the phone notify and vibrate."),
    ("alerts[].kind", "", "breach, near_contract, low_pf, anomaly, anomaly_sustained or demo."),
    ("alerts[].key", "", "Stable id of the condition; the app uses it so one breach pages once, not every tick."),
    ("speed", "ticks/s", "Replay speed; one tick = 15 simulated minutes."),
    ("paused", "", "true while the replay is paused."),
]

GLOSSARY = [
    ("kW", "Kilowatt — real power, the rate at which energy is used."),
    ("kWh", "Kilowatt-hour — energy. 1 kW for 1 hour. What the energy bill counts."),
    ("kVA", "Kilovolt-ampere — apparent power, the load the supply has to carry. Contract demand is in kVA."),
    ("Power factor (PF)", "kW ÷ kVA. 1.0 is ideal; low PF means the plant draws current that does no work, and is penalised below 0.90."),
    ("Contract demand", "The maximum kVA agreed with the utility. Going above it (a breach) costs penalty charges. Company 400 kVA; Hadapsar 280, Saswad 80, Nashik 70 (assumed)."),
    ("Critical alert", "Contract demand breached, a machine abnormal for 24 hours straight (a confirmed fault), or a demo alert from the dashboard. The only alerts that notify and vibrate."),
    ("ToD tariff", "Time-of-day pricing: energy costs more in peak hours (09–12, 18–22) than off-peak (22–06)."),
    ("Scope 1", "Direct CO2 from fuel burnt on site (furnace LPG, chiller gas, generator diesel, refrigerant leaks)."),
    ("Scope 2", "Indirect CO2 from grid electricity the plant buys."),
    ("tCO2", "Tonnes of carbon dioxide."),
    ("Specific power", "kWh used to make one m³ of compressed air. Lower = more efficient compressor system."),
    ("TR", "Ton of refrigeration — cooling capacity, 3.517 kW of heat removed."),
    ("kW/TR", "Chiller electricity per ton of cooling. Lower is better."),
    ("COP", "Coefficient of performance — cooling produced per unit of energy put in. Higher is better."),
    ("VAM", "Vapour absorption machine — a chiller driven by heat (gas) instead of electricity."),
    ("Anomaly", "A reading the Isolation Forest model and/or an engineering rule flags as unusual for that machine."),
    ("Anomaly score", "How unusual a reading is (higher = stranger). Severity is the score's rank within that machine's own flagged readings."),
    ("Hard negative", "An unusual-looking but normal event (production surge, heat wave, maintenance day) used to check the model does not cry wolf."),
    ("Data quality flag", "ok, missing (no reading) or drift (meter reading slowly wrong) — realism added on purpose."),
    ("Replay", "The app is not reading real meters. The server walks through a simulated year, 15 minutes per tick, as if it were live."),
]


def _conn():
    return sqlite3.connect(DB, check_same_thread=False)


@router.get("/dataset")
def dataset():
    """Every table: what a row is, row count, and each column's unit and meaning."""
    conn = _conn()
    try:
        out = []
        for name, (group, about, cols) in TABLES.items():
            types = {r[1]: r[2] for r in conn.execute(f"PRAGMA table_info({name})")}
            if not types:
                continue
            rows = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            out.append({
                "table": name, "group": group, "about": about, "rows": rows,
                "columns": [{"name": c, "type": types.get(c, ""), "unit": u, "meaning": m}
                            for c, (u, m) in cols.items() if c in types],
            })
        return {"data_label": DATA_LABEL, "tables": out}
    finally:
        conn.close()


@router.get("/dataset/{table}")
def dataset_rows(table: str, limit: int = 20, offset: int = 0):
    """A page of raw rows from one table (in stored order)."""
    if table not in TABLES:
        raise HTTPException(404, f"unknown table {table}")
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    conn = _conn()
    try:
        cur = conn.execute(f"SELECT * FROM {table} LIMIT ? OFFSET ?", (limit, offset))
        cols = [d[0] for d in cur.description]
        rows = [[None if (isinstance(v, float) and v != v) else
                 (round(v, 4) if isinstance(v, float) else v) for v in r] for r in cur.fetchall()]
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return {"table": table, "columns": cols, "rows": rows, "offset": offset, "limit": limit, "total": total}
    finally:
        conn.close()


@router.get("/glossary")
def glossary():
    """Explanations for the live-frame fields and the general energy terms."""
    return {
        "data_label": DATA_LABEL,
        "live_fields": [{"field": f, "unit": u, "meaning": m} for f, u, m in LIVE_FIELDS],
        "terms": [{"term": t, "meaning": m} for t, m in GLOSSARY],
    }
