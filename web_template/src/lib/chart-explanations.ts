// One builder per dashboard chart: what it shows, how to read it, and what the data currently on
// screen implies. Opened by components/kpcl/chart-explainer.tsx when a chart is clicked.
import {
  correlation,
  type Explanation,
  num,
  pct,
  rangePhrase,
  type Row,
  shareAbove,
  sum,
  summarize,
  trendDirection,
  trendPhrase,
} from '@/lib/chart-insights'
import { fmtDateTime, fmtRupees, fmtShortDate } from '@/lib/format'
import type { ForecastResponse, PeakPlan, ScenarioCompare, WhatIfGrid, WhatIfOption } from '@/lib/kpcl-api'

const monthName = (m: string) => {
  const d = new Date(`${m}-01T00:00:00`)
  return Number.isNaN(d.getTime()) ? m : d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
}
const hours = (ticks: number) => (ticks * 15) / 60
// placeholder emission factors from config.yaml (kg CO2 per kg or litre) — VERIFY before external use
const KG_CO2 = { LPG: 2.98, gas: 2.75, diesel_litre: 2.68 } as const
const COMPRESSOR_PENALTY_PER_BAR = 0.065   // generator/compressor.py: kW x (1 + (p - 7) x 0.065)

function topBy<T>(items: T[], key: (t: T) => number): T | undefined {
  return items.reduce<T | undefined>((best, t) => (best === undefined || key(t) > key(best) ? t : best), undefined)
}

// ---------------------------------------------------------------- live monitor

export function explainLiveDemand(rows: Row[], plantName: string): Explanation {
  const s = summarize(rows, 'ts', 'kVA')
  const contract = Number(rows[rows.length - 1]?.contract ?? 0)
  const says: string[] = []
  if (s && contract > 0) {
    says.push(`Right now ${num(s.last, 0)} kVA — ${pct(s.last / contract)} of the ${num(contract, 0)} kVA contract.`)
    says.push(`Over the last ${s.n} ticks (≈${num(hours(s.n), 0)} simulated hours) demand ${rangePhrase(s, 'kVA', 0, fmtDateTime)}.`)
    const over = shareAbove(rows, 'kVA', contract)
    const near = shareAbove(rows, 'kVA', 0.85 * contract)
    if (over.above > 0) {
      says.push(`${over.above} tick${over.above > 1 ? 's' : ''} went above the contract — each is a breach that attracts a penalty and pages the on-call phone.`)
    } else if (near.above > 0) {
      says.push(`No breach, but ${near.above} tick${near.above > 1 ? 's were' : ' was'} above 85% of contract — the "watch" zone where one more large load could tip it over.`)
    } else {
      says.push(`Demand never went above 85% of contract; even the peak left ${num(contract - s.max, 0)} kVA of headroom.`)
    }
    says.push(`Demand ${trendPhrase(s)}.`)
  }
  return {
    title: 'Plant apparent power vs contract demand',
    shows: `Apparent power (kVA) drawn by ${plantName} on every 15-minute tick of the live replay, against the contract demand limit agreed with the utility.`,
    read: 'Blue is what the plant draws; the red dashed line is the contract. The utility bills demand in kVA, so the blue line crossing the red line is a breach. Staying below ~85% keeps a safety margin.',
    says,
  }
}

export function explainLivePowerSpark(values: number[]): Explanation {
  const rows = values.map((v, i) => ({ i: String(i), kW: v }))
  const s = summarize(rows, 'i', 'kW')
  return {
    title: 'Real power, last 12 simulated hours',
    shows: 'The small line in the "Real power" tile is the plant’s real power (kW) over the last 48 ticks of the replay (48 × 15 min = 12 simulated hours).',
    read: 'Real power is the energy actually being used; it is what the energy bill counts. Steps up and down follow shifts and batch processes starting and stopping.',
    says: s
      ? [
          `Now ${num(s.last, 0)} kW; over the window it ranged ${num(s.min, 0)}–${num(s.max, 0)} kW, averaging ${num(s.mean, 0)} kW.`,
          `Power ${trendPhrase(s, 0.1)}.`,
          s.max > 2.5 * Math.max(s.min, 1)
            ? 'The large gap between low and high points is the shift pattern: production loads switch on and off.'
            : 'Load is fairly steady across the window — mostly base load (compressors, chillers) rather than shift work.',
        ]
      : [],
  }
}

// ---------------------------------------------------------------- peak shaving

export function explainPeakPlan(plan: PeakPlan): Explanation {
  const says = [
    `Peak ${num(plan.peak_before_kva, 0)} kVA at ${plan.peak_time} → ${num(plan.peak_after_kva, 0)} kVA after the plan (${num(plan.kva_reduction, 0)} kVA lower).`,
  ]
  if (plan.breach_before && !plan.breach_after) says.push('The plan avoids a contract breach on this day.')
  else if (plan.breach_after) says.push('Even after shifting, the peak stays above contract — moving loads alone is not enough; something has to be curtailed that day.')
  else if (plan.at_risk) says.push('The day runs close to contract (above 85%), so the plan targets the peak first.')
  else says.push('The day stays within contract, so the plan only moves loads into cheaper time-of-day slots.')
  const shifts = plan.actions.filter((a) => a.type === 'shift')
  if (shifts.length) says.push(`${shifts.length} load shift${shifts.length > 1 ? 's' : ''}: ${shifts.slice(0, 2).map((a) => a.message).join('; ')}.`)
  else says.push('No load is worth moving on this day.')
  if (plan.demand_charge_at_stake_rs > 0 || plan.tod_energy_saving_rs > 0) {
    says.push(`About ${fmtRupees(plan.demand_charge_at_stake_rs)} of demand charge is at stake; the time-of-day energy saving is ${fmtRupees(plan.tod_energy_saving_rs)}.`)
  }
  if (plan.source !== 'forecast') says.push('This day has no day-ahead forecast (too little history), so the metered load is used.')
  return {
    title: `Peak-shaving schedule — ${plan.date}`,
    shows: `The plant’s load for ${plan.date} (${plan.source === 'forecast' ? 'the day-ahead forecast' : 'metered'}) as scheduled, and after moving flexible loads — CNG test rig, heat-treatment furnace, paint booth — to other hours.`,
    read: 'Grey is the load as scheduled, blue is after the plan, red dashed is the contract. Shifting changes when energy is used, not how much, so the saving is demand charge and time-of-day rate, not CO₂.',
    says,
  }
}

// ---------------------------------------------------------------- forecast

export function explainForecast(f: ForecastResponse | undefined, unit: 'kVA' | 'kW'): Explanation {
  const says: string[] = []
  const day = f?.day
  const ev = f?.evaluation
  if (f && f.covered === false) {
    says.push(`There is no forecast for ${f.date}: the model needs about seven weeks of history, so forecasts start ${f.first_forecast_date}. The line shown is what was metered.`)
  } else if (day && f) {
    const contract = f.metrics.contract_kva
    says.push(`Tomorrow’s peak is expected around ${num(day.peak_p50_kva, 0)} kVA, with an 80% chance it lands between ${num(day.peak_p10_kva, 0)} and ${num(day.peak_p90_kva, 0)} kVA (contract ${num(contract, 0)}).`)
    const r = day.breach_risk
    says.push(
      r >= 0.3
        ? `Breach risk ${pct(r)} — high. Plan to move flexible loads off the peak hours (see the peak-shaving schedule).`
        : r >= 0.1
          ? `Breach risk ${pct(r)} — worth watching, not yet worth rescheduling.`
          : `Breach risk ${pct(r)} — a breach is unlikely.`
    )
    says.push(`Chance of going above 85% of contract: ${pct(day.near_contract_risk)}.`)
    if (day.actual_peak_kva != null) {
      const inside = day.actual_peak_kva >= day.peak_p10_kva && day.actual_peak_kva <= day.peak_p90_kva
      says.push(`The metered peak that day was ${num(day.actual_peak_kva, 0)} kVA — ${inside ? 'inside' : 'outside'} the forecast range.`)
    }
  }
  if (ev) {
    says.push(`Track record over ${ev.days} days, each forecast made only from earlier data: daily peaks were off by ±${num(ev.peak_mae_kva, 0)} kVA on average (bias ${ev.peak_bias_kva >= 0 ? '+' : ''}${num(ev.peak_bias_kva, 0)}), versus ±${num(ev.peak_mae_last_week_kva, 0)} for “same as last week”. The 80% range contained ${pct(ev.band_coverage_p10_p90)} of readings.`)
    says.push('The exact 15-minute shape is hard to predict because machine run times vary day to day; the size of the daily peak is what the forecast is built for.')
  }
  return {
    title: `Day-ahead forecast${f?.date ? ` — ${f.date}` : ''}`,
    shows: `The forecast ${unit === 'kVA' ? 'apparent power (kVA)' : 'real power (kW)'} for the replay’s “tomorrow”, made only from data up to today, with an 80% range, and the metered load for comparison.`,
    read: `The dark line is the forecast; the shaded band is where the load should fall 8 times out of 10; the grey line is what was actually metered.${unit === 'kVA' ? ' The red dashed line is the contract demand.' : ''}`,
    says,
  }
}

// ---------------------------------------------------------------- plant overview

type PlantRow = { plant_name: string; kwh_total: number; cost_rs: number; scope1_tco2: number; scope2_tco2: number; peak_kva: number; contract_kva: number; kwh_per_unit: number | null }

export function explainPlantComparison(plants: PlantRow[]): Explanation {
  const total = plants.reduce((s, p) => s + p.kwh_total, 0)
  const biggest = topBy(plants, (p) => p.kwh_total)
  const over = plants.filter((p) => p.peak_kva > p.contract_kva)
  const intense = topBy(plants.filter((p) => p.kwh_per_unit), (p) => p.kwh_per_unit ?? 0)
  const says: string[] = []
  if (biggest && total > 0) says.push(`${biggest.plant_name} uses ${pct(biggest.kwh_total / total)} of all energy (${fmtRupees(biggest.cost_rs)} a year).`)
  says.push(
    over.length
      ? `${over.map((p) => `${p.plant_name} (${num(p.peak_kva, 0)} vs ${num(p.contract_kva, 0)} kVA)`).join(', ')} went above contract at least once this year.`
      : 'No plant went above its contract demand this year.'
  )
  if (intense) says.push(`Highest grid energy per unit produced: ${intense.plant_name} at ${num(intense.kwh_per_unit ?? 0, 0)} kWh/unit.`)
  const co2 = topBy(plants, (p) => p.scope1_tco2 + p.scope2_tco2)
  if (co2) says.push(`Largest emitter: ${co2.plant_name}, ${num(co2.scope1_tco2 + co2.scope2_tco2, 0)} tCO₂e.`)
  return {
    title: 'Plant comparison',
    shows: 'Each plant’s energy, cost, emissions, peak demand against its contract, and grid energy per unit produced, for the full year.',
    read: 'The blue bar compares energy between plants. Peak / contract turns red when a plant’s highest 15-minute demand exceeded its contract. Click a row to switch the dashboard to that plant.',
    says,
  }
}

export function explainSolarGeneration(rows: Row[]): Explanation {
  const gen = summarize(rows, 'ts', 'kW_generated')
  const totalGen = sum(rows, 'kW_generated')
  const self = sum(rows, 'kW_self_consumed')
  const says: string[] = []
  if (gen && totalGen > 0) {
    says.push(`${pct(self / totalGen)} of the solar output is used on site; the rest is exported to the grid.`)
    says.push(`Daily average generation ${rangePhrase(gen, 'kW', 1, fmtShortDate)}.`)
    if (gen.max - gen.min < 0.05 * Math.max(gen.mean, 1e-9)) {
      says.push('Generation hardly changes from day to day — a known limitation of the simulation’s solar model, not real weather.')
    } else {
      says.push(`Generation ${trendPhrase(gen)}.`)
    }
  }
  return {
    title: 'Solar generation vs self-consumption',
    shows: 'Daily average power from the rooftop solar plant at Saswad, and how much of it the plants used themselves.',
    read: 'Blue is generated, grey is self-consumed. The gap between them is exported. Self-consumed solar directly cuts grid purchases and Scope 2 emissions.',
    says,
  }
}

// ---------------------------------------------------------------- carbon

export function explainCarbonMonthly(rows: Row[]): Explanation {
  const s1 = sum(rows, 'scope1_tco2')
  const s2 = sum(rows, 'scope2_tco2')
  const totals = rows.map((r) => ({ m: String(r.month), t: Number(r.scope1_tco2 ?? 0) + Number(r.scope2_tco2 ?? 0) }))
  const hi = topBy(totals, (t) => t.t)
  const lo = topBy(totals, (t) => -t.t)
  const says: string[] = []
  if (s1 + s2 > 0) {
    says.push(
      s2 >= s1
        ? `Scope 2 (grid electricity) is ${pct(s2 / (s1 + s2))} of the ${num(s1 + s2, 1)} tCO₂e total — using less electricity is the biggest lever.`
        : `Scope 1 (fuel burnt on site) is ${pct(s1 / (s1 + s2))} of the ${num(s1 + s2, 1)} tCO₂e total — furnace and generator fuel matter most.`
    )
    if (hi && lo) says.push(`Highest month ${monthName(hi.m)} (${num(hi.t, 1)} tCO₂e), lowest ${monthName(lo.m)} (${num(lo.t, 1)}).`)
    says.push(`Scope 2 ${trendPhrase(summarize(rows, 'month', 'scope2_tco2'))}; Scope 1 ${trendPhrase(summarize(rows, 'month', 'scope1_tco2'))}.`)
  }
  return {
    title: 'Monthly Scope 1 vs Scope 2',
    shows: 'Carbon emissions per month, split into Scope 1 (fuel burnt on site and refrigerant leaks) and Scope 2 (electricity bought from the grid), in tonnes of CO₂ equivalent.',
    read: 'Scope 2 moves with electricity use; Scope 1 moves with furnace LPG, chiller gas, generator diesel and refrigerant top-ups. Emission factors are placeholders from config — verify before external reporting.',
    says,
  }
}

export function explainFuelMix(rows: Row[]): Explanation {
  const fuels = (['LPG', 'gas', 'diesel_litre'] as const).map((k) => ({ k, amount: sum(rows, k), t: (sum(rows, k) * KG_CO2[k]) / 1000 }))
  const total = fuels.reduce((s, f) => s + f.t, 0)
  const name = { LPG: 'LPG (furnace)', gas: 'Gas (VAM chiller)', diesel_litre: 'Diesel (generator)' }
  const says: string[] = []
  if (total > 0) {
    const top = topBy(fuels, (f) => f.t)!
    says.push(`${name[top.k]} is the largest Scope 1 source: about ${num(top.t, 1)} tCO₂ (${pct(top.t / total)}) of ${num(total, 1)} t from fuel.`)
    says.push(fuels.map((f) => `${name[f.k]} ${num(f.amount, 0)} ${f.k === 'diesel_litre' ? 'L' : 'kg'}`).join(' · ') + '.')
    const dieselMonths = rows.filter((r) => Number(r.diesel_litre ?? 0) > 0).map((r) => monthName(String(r.month)))
    says.push(
      dieselMonths.length
        ? `Diesel appears in ${dieselMonths.join(', ')} — the backup generator ran during grid outages.`
        : 'No diesel was burnt: there were no grid outages needing the generator.'
    )
  }
  return {
    title: 'Scope 1 fuel mix',
    shows: 'Fuel burnt on site each month: LPG in the heat-treatment furnace (kg), gas in the VAM absorption chiller (kg), and diesel in the backup generator (litres).',
    read: 'Each fuel is in its own unit, so compare lines by shape, not height. CO₂ estimates use the placeholder factors in config (LPG 2.98, gas 2.75 kg/kg, diesel 2.68 kg/L).',
    says,
  }
}

export function explainSolarAvoided(rows: Row[]): Explanation {
  const s = summarize(rows, 'month', 'solar_avoided_tco2')
  const says: string[] = []
  if (s) {
    says.push(`Solar avoided ${num(sum(rows, 'solar_avoided_tco2'), 1)} tCO₂e over the year.`)
    says.push(`Best month ${monthName(s.maxX)} (${num(s.max, 2)} t), weakest ${monthName(s.minX)} (${num(s.min, 2)} t).`)
    const monsoon = rows.filter((r) => ['06', '07', '08', '09'].includes(String(r.month).slice(5, 7)))
    const dry = rows.filter((r) => !monsoon.includes(r))
    if (monsoon.length && dry.length) {
      const m = sum(monsoon, 'solar_avoided_tco2') / monsoon.length
      const d = sum(dry, 'solar_avoided_tco2') / dry.length
      says.push(`Monsoon months (Jun–Sep) average ${pct(Math.abs(1 - m / d))} ${m < d ? 'less' : 'more'} than the rest of the year.`)
    }
  }
  return {
    title: 'Avoided emissions from solar',
    shows: 'CO₂ the grid would have emitted for the electricity that solar supplied instead, per month.',
    read: 'Avoided emissions are not subtracted from Scope 2 here; they are reported alongside it, which is how most frameworks expect them.',
    says,
  }
}

// ---------------------------------------------------------------- compressors

export function explainPressure(rows: Row[], assetId: string, lower: number, upper: number): Explanation {
  const s = summarize(rows, 'ts', 'pressure_bar')
  const says: string[] = []
  if (s) {
    says.push(`Header pressure ${rangePhrase(s, 'bar', 2, fmtDateTime)}.`)
    const high = shareAbove(rows, 'pressure_bar', upper)
    says.push(
      high.above
        ? `Average pressure was above the ${upper} bar top of the band in ${pct(high.share)} of intervals.`
        : `Average pressure stayed inside the ${lower}–${upper} bar band.`
    )
    const swings = rows
      .map((r) => Number(r.pressure_bar_max) - Number(r.pressure_bar_min))
      .filter((v) => Number.isFinite(v))
    if (swings.length) {
      const avg = swings.reduce((a, b) => a + b, 0) / swings.length
      says.push(
        avg > upper - lower
          ? `Pressure swings ${num(avg, 2)} bar within a typical 15 minutes — wider than the band, a sign of heavy load/unload cycling.`
          : `Pressure swings ${num(avg, 2)} bar within a typical 15 minutes — normal load/unload cycling inside the band.`
      )
    }
    if (s.mean > 7) {
      says.push(`Each bar above 7 costs about ${pct(COMPRESSOR_PENALTY_PER_BAR, 1)} more compressor power, so running at ${num(s.mean, 2)} bar costs roughly ${pct((s.mean - 7) * COMPRESSOR_PENALTY_PER_BAR, 1)} extra versus 7 bar.`)
    }
  }
  return {
    title: `Header pressure — ${assetId}`,
    shows: 'Compressed-air header pressure for the selected compressor, every 15 minutes. The shaded envelope is the lowest-to-highest pressure inside each interval; the line is its average.',
    read: `The compressor loads when pressure falls to ${lower} bar and unloads at ${upper} bar, producing a sawtooth faster than 15 minutes. The envelope shows how far it swung. Higher pressure than needed wastes energy.`,
    says,
  }
}

export function explainLeakFlow(rows: Row[], assetId: string): Explanation {
  const s = summarize(rows, 'ts', 'leak_flow_m3min')
  const flow = sum(rows, 'flow_m3min')
  const says: string[] = []
  if (s) {
    says.push(`Leak flow ${rangePhrase(s, 'm³/min', 2, fmtDateTime)}.`)
    if (flow > 0) says.push(`Leaks are about ${pct(sum(rows, 'leak_flow_m3min') / flow)} of all air this compressor delivered — paid for, never used.`)
    const dir = trendDirection(s, 0.05)
    says.push(
      dir === 'up'
        ? `Leak flow ${trendPhrase(s)} — a leak that keeps growing; find and fix it before it gets worse.`
        : dir === 'down'
          ? `Leak flow ${trendPhrase(s)} — consistent with a repair or less header pressure.`
          : `Leak flow ${trendPhrase(s)} — a steady background leak rather than a developing one.`
    )
  }
  return {
    title: `Leak flow — ${assetId}`,
    shows: 'Compressed air lost through leaks in the system (m³/min), estimated every 15 minutes.',
    read: 'Leaks run around the clock, including nights and Sundays, so they set a floor under compressor load. A line that climbs week on week means a leak is getting bigger.',
    says,
  }
}

export function explainLeakCost(rows: Row[], assets: string[]): Explanation {
  const per = assets.map((a) => ({ a, rs: sum(rows, a) })).filter((x) => x.rs > 0)
  const total = per.reduce((s, x) => s + x.rs, 0)
  const daily = rows.map((r) => ({ date: String(r.date), rs: assets.reduce((s, a) => s + Number(r[a] ?? 0), 0) }))
  const worstDay = topBy(daily, (d) => d.rs)
  const says: string[] = []
  if (total > 0) {
    const top = topBy(per, (x) => x.rs)!
    says.push(`Avoidable leaks cost ${fmtRupees(total)} over the period; ${top.a} accounts for ${pct(top.rs / total)} of it — fix that one first.`)
    if (worstDay) says.push(`Costliest day: ${fmtShortDate(worstDay.date)} at ${fmtRupees(worstDay.rs)}.`)
    says.push(`Daily leak cost ${trendPhrase(summarize(daily, 'date', 'rs'))}.`)
  }
  return {
    title: 'Avoidable leak cost per day',
    shows: 'What compressed-air leaks cost each day for each compressor, counting only leakage above the normal background floor — the part a repair could save.',
    read: 'Higher lines are costlier compressors. A standby unit can show a cost because the running compressors make the air its leak loses.',
    says,
  }
}

// ---------------------------------------------------------------- production

export function explainShifts(rows: Row[]): Explanation {
  const a = sum(rows, 'A')
  const b = sum(rows, 'B')
  const bMonths = rows.filter((r) => Number(r.B) > Number(r.A)).map((r) => monthName(String(r.month)))
  const says: string[] = []
  if (a + b > 0) {
    says.push(`Shift A (06:00–14:00) made ${pct(a / (a + b))} of all units (${num(a, 0)} vs ${num(b, 0)}).`)
    says.push(bMonths.length ? `Shift B out-produced A in ${bMonths.join(', ')}.` : 'Shift A out-produced shift B every month — partly because Saturdays run shift A only.')
    says.push(`Total output ${trendPhrase(summarize(rows.map((r) => ({ m: r.month, u: Number(r.A) + Number(r.B) })), 'm', 'u'))}.`)
  }
  return {
    title: 'Shift A vs B — units per month',
    shows: 'Units produced each month by the morning shift (A, 06:00–14:00) and the afternoon shift (B, 14:00–22:00).',
    read: 'Saturday is a half day with shift A only, so A naturally runs a little higher.',
    says,
  }
}

export function explainUnitsVsEnergy(rows: Row[]): Explanation {
  const u = summarize(rows, 'month', 'units')
  const perUnit = rows.filter((r) => Number(r.units) > 0).map((r) => ({ month: String(r.month), v: Number(r.kWh) / Number(r.units) }))
  const r = correlation(rows, 'units', 'kWh')
  const says: string[] = []
  if (u) {
    says.push(`Output ${rangePhrase(u, 'units', 0, monthName)} per month.`)
    if (perUnit.length) {
      const best = topBy(perUnit, (p) => -p.v)!
      const worst = topBy(perUnit, (p) => p.v)!
      says.push(`Energy per unit was lowest in ${monthName(best.month)} (${num(best.v, 0)} kWh/unit) and highest in ${monthName(worst.month)} (${num(worst.v, 0)} kWh/unit).`)
    }
    if (r !== null) {
      says.push(
        r > 0.7
          ? `Plant energy closely tracks output (correlation ${num(r, 2)}): most load is production-driven.`
          : r > 0.3
            ? `Plant energy only partly tracks output (correlation ${num(r, 2)}): a large share of load runs regardless of production.`
            : `Plant energy barely follows output (correlation ${num(r, 2)}): most load — compressors, leaks, chillers — runs whether or not units are made.`
      )
    }
  } else {
    says.push('This plant has no production records, so there is nothing to plot.')
  }
  return {
    title: 'Monthly units vs plant energy',
    shows: 'Units produced per month (the line). Plant energy is on a far larger scale, so it is summarised below as energy per unit rather than drawn on the same axis.',
    read: 'Falling energy per unit means the plant is producing more efficiently; rising energy per unit with flat output points to waste.',
    says,
  }
}

export function explainFurnaceFuel(rows: Row[]): Explanation {
  const s = summarize(rows, 'ts', 'fuel_kg')
  let batches = 0
  let on = false
  for (const r of rows) {
    const burning = Number(r.fuel_kg ?? 0) > 0
    if (burning && !on) batches += 1
    on = burning
  }
  const total = sum(rows, 'fuel_kg')
  const says: string[] = []
  if (s) {
    says.push(`${num(total, 0)} kg of LPG across ${batches} firing period${batches === 1 ? '' : 's'} (≈${num((total * KG_CO2.LPG) / 1000, 2)} tCO₂ Scope 1).`)
    says.push(`The highest burn was ${num(s.max, 1)} kg in 15 minutes at ${fmtDateTime(s.maxX)} — heating a batch up to temperature uses the most fuel.`)
    says.push(`Fuel is burnt ${pct(shareAbove(rows, 'fuel_kg', 0).share)} of the time; the rest the furnace is holding, cooling or idle.`)
  }
  return {
    title: 'Heat-treatment furnace — fuel',
    shows: 'LPG burnt by the heat-treatment furnace every 15 minutes over the selected week.',
    read: 'Each block of burning is one batch: a ramp-up (highest burn), a hold at temperature, then cooldown. Bigger or more frequent blocks mean more batches or heavier loads.',
    says,
  }
}

export function explainPaintAir(rows: Row[]): Explanation {
  const s = summarize(rows, 'ts', 'air_draw_m3min')
  const says: string[] = []
  if (s) {
    const running = rows.filter((r) => Number(r.air_draw_m3min ?? 0) > 0.1)
    says.push(`The booth drew air ${pct(rows.length ? running.length / rows.length : 0)} of the time, ${num(running.length ? sum(running, 'air_draw_m3min') / running.length : 0, 2)} m³/min on average while running.`)
    const offShift = running.filter((r) => {
      const h = new Date(String(r.ts)).getHours()
      return h < 6 || h >= 22
    })
    says.push(
      offShift.length
        ? `${offShift.length} interval${offShift.length > 1 ? 's' : ''} drew air outside shift hours (22:00–06:00) — air made for nobody; check the fan schedule.`
        : 'No air was drawn outside shift hours (22:00–06:00).'
    )
    says.push(`Peak draw ${num(s.max, 2)} m³/min at ${fmtDateTime(s.maxX)}.`)
  }
  return {
    title: 'Paint booth air draw',
    shows: 'Compressed air used by the paint booth every 15 minutes over the selected week. This air comes from the Hadapsar compressors, so it shows up in their load and energy.',
    read: 'Draw should follow the shift pattern. Draw at night or on Sundays means the booth or its fans were left running.',
    says,
  }
}

// ---------------------------------------------------------------- refrigeration

export function explainKwPerTr(value: number, goodMax: number, warnMax: number): Explanation {
  const over = value - goodMax
  const status = value <= goodMax ? 'good' : value <= warnMax ? 'warn' : 'critical'
  return {
    title: 'Chiller kW per TR vs benchmark',
    shows: 'Electricity the screw chiller needs per ton of cooling (kW/TR), averaged over the selected week, placed on a good / warning / poor scale.',
    read: `Lower is better. Green is at or below the ${goodMax} kW/TR benchmark, amber up to ${warnMax}, red above. The benchmark is an assumed rule of thumb for screw chillers.`,
    says: [
      `Average ${num(value, 3)} kW/TR — ${status === 'good' ? 'within the benchmark' : status === 'warn' ? 'in the warning zone' : 'poor'}.`,
      over > 0
        ? `That is ${pct(over / goodMax)} more electricity per ton of cooling than the benchmark — typical causes are condenser fouling, low refrigerant charge or high condenser water temperature.`
        : `That is ${pct(-over / goodMax)} better than the benchmark.`,
    ],
  }
}

export function explainCondenserApproach(rows: Row[]): Explanation {
  const s = summarize(rows, 'ts', 'condenser_approach_c')
  const dir = trendDirection(s, 0.03)
  return {
    title: 'Condenser approach temperature',
    shows: 'The difference between the condenser temperature and the cooling-water temperature (°C), every 15 minutes.',
    read: 'A small approach means heat leaves the condenser easily. As tubes foul, the approach rises and the chiller burns more power for the same cooling.',
    says: s
      ? [
          `Approach ${rangePhrase(s, '°C', 2, fmtDateTime)}.`,
          dir === 'up'
            ? `It ${trendPhrase(s, 0.03)} — consistent with condenser fouling; schedule tube cleaning.`
            : `It ${trendPhrase(s, 0.03)} — no sign of fouling building up in this window.`,
        ]
      : [],
  }
}

export function explainCop(rows: Row[], key: 'COP' | 'thermal_cop'): Explanation {
  const s = summarize(rows, 'ts', key)
  const thermal = key === 'thermal_cop'
  const dir = trendDirection(s, 0.03)
  return {
    title: thermal ? 'VAM thermal COP' : 'Chiller COP',
    shows: thermal
      ? 'Cooling delivered by the vapour-absorption chiller per unit of heat fed to it (thermal COP), every 15 minutes.'
      : 'Coefficient of performance of the screw chiller — cooling delivered per unit of electricity — every 15 minutes.',
    read: thermal
      ? 'Higher is better; absorption chillers typically run between about 0.7 and 1.2.'
      : 'Higher is better. COP = cooling kW ÷ electrical kW, so a falling COP means more electricity for the same cooling.',
    says: s
      ? [
          `COP ${rangePhrase(s, '', 2, fmtDateTime)}.`,
          dir === 'down'
            ? `It ${trendPhrase(s, 0.03)} — efficiency is degrading; check condenser cleanliness and refrigerant charge.`
            : dir === 'up'
              ? `It ${trendPhrase(s, 0.03)} — efficiency improved over the window.`
              : `It ${trendPhrase(s, 0.03)}.`,
        ]
      : [],
  }
}

// ---------------------------------------------------------------- anomalies

export function explainFaultTimeline(daily: { asset_id: string; date: string; rank: number }[], assetIds: string[]): Explanation {
  const per = assetIds.map((a) => {
    const rows = daily.filter((d) => d.asset_id === a)
    let longest = 0
    let run = 0
    let prev = ''
    for (const d of [...rows].sort((x, y) => x.date.localeCompare(y.date))) {
      const next = prev && new Date(d.date).getTime() - new Date(prev).getTime() === 86_400_000
      run = next ? run + 1 : 1
      longest = Math.max(longest, run)
      prev = d.date
    }
    return { a, days: rows.length, critical: rows.filter((d) => d.rank === 4).length, longest }
  })
  const says: string[] = []
  const busiest = topBy(per, (p) => p.days)
  if (busiest && busiest.days > 0) {
    says.push(`${busiest.a} was flagged on the most days (${busiest.days}); its longest unbroken run was ${busiest.longest} days.`)
    const streak = topBy(per, (p) => p.longest)!
    if (streak.a !== busiest.a) says.push(`Longest unbroken run: ${streak.a}, ${streak.longest} days — sustained runs like this usually mean a real fault rather than noise.`)
    says.push(per.filter((p) => p.days > 0).map((p) => `${p.a} ${p.days} d (${p.critical} critical)`).join(' · ') + '.')
    says.push('Short scattered marks are often normal variation the model found unusual; long solid bars are the ones to investigate.')
  } else {
    says.push('No anomalies were flagged for these assets.')
  }
  return {
    title: 'Fault timeline — flagged anomalies',
    shows: 'One strip per machine and one cell per day of 2025, coloured by the most severe anomaly the detector flagged that day.',
    read: 'Severity is ranked within each machine (critical = its top 5% most unusual readings), so colours compare days for the same machine, not machines with each other. Hover a cell for the date.',
    says,
  }
}

// ---------------------------------------------------------------- what-if

type WhatIfTotals = { kWh: number; rs: number; tco2: number; peak: number; n: number }

export function explainWhatIf(grid: WhatIfGrid, choice: Record<string, string>, totals: WhatIfTotals): Explanation {
  const says: string[] = []
  const all = grid.levers.flatMap((l) => l.options.map((o) => ({ lever: l.label, ...o })))
  const chosen = grid.levers
    .map((l) => ({ lever: l.label, opt: l.options.find((o) => o.option_label === choice[l.lever]) }))
    .filter((c): c is { lever: string; opt: WhatIfOption } => !!c.opt)
  if (chosen.length === 0) {
    const best = [...all].sort((a, b) => b.rs_saved - a.rs_saved).slice(0, 3).filter((o) => o.rs_saved > 0)
    says.push('No lever is changed yet, so everything is at the baseline policy. Pick a setting in any box to see its effect.')
    if (best.length) {
      says.push(`Biggest single savings available: ${best.map((o) => `${o.lever} → ${o.option_label} (${fmtRupees(o.rs_saved)}/yr)`).join('; ')}.`)
    }
  } else {
    says.push(`With ${chosen.length} change${chosen.length > 1 ? 's' : ''}, the plant would save about ${fmtRupees(totals.rs)} a year, ${num(totals.kWh / 1000, 1)} MWh of energy and ${num(totals.tco2, 1)} tCO₂e, and the peak would drop by ${num(totals.peak, 0)} kVA.`)
    const top = topBy(chosen, (c) => c.opt.rs_saved)!
    if (chosen.length > 1 && totals.rs > 0) says.push(`${top.lever} (${top.opt.option_label}) contributes the most: ${pct(top.opt.rs_saved / totals.rs)} of the saving.`)
    const worse = chosen.filter((c) => c.opt.rs_saved < 0)
    if (worse.length) says.push(`${worse.map((c) => `${c.lever} → ${c.opt.option_label}`).join(', ')} costs money (shown in red): that setting uses more energy than the baseline.`)
    says.push('Levers are simulated one at a time and added up, so the combined number is an approximation: changes that interact (e.g. two that cut the same compressor’s load) can overlap.')
  }
  says.push(`Baseline year: ${num(grid.baseline.kWh / 1000, 0)} MWh, ${fmtRupees(grid.baseline.cost_rs)}, peak ${num(grid.baseline.peak_kva, 0)} kVA.`)
  return {
    title: 'What-if simulator',
    shows: 'What would change over a full year if you changed one or more operating settings (levers) — such as air-pressure setpoint, when the test rig runs, or CNC idle shutdown.',
    read: 'Each option is not a formula: the whole year was re-simulated with only that setting changed, and the difference from the baseline is shown. Green/neutral numbers are savings; red means that option costs more.',
    says,
  }
}

export function explainScenarioCompare(c: ScenarioCompare, scenario: 'baseline' | 'optimized'): Explanation {
  const s = c.savings
  return {
    title: 'Baseline vs optimized',
    shows: `Full-year energy, cost and emissions under two operating policies. You are viewing the ${scenario} one.`,
    read: 'Baseline is today’s way of running the plant. Optimized applies the recommended policy changes together (lower pressure setpoint, off-peak test rig, CNC idle shutdown, earlier furnace start). Both use the same weather, production and faults, so the difference is purely the policy.',
    says: [
      `Optimized saves ${num(s.kWh / 1000, 1)} MWh (${pct(s.kWh / c.baseline.kWh, 1)} of energy), ${fmtRupees(s.cost_rs)} (${pct(s.cost_rs / c.baseline.cost_rs, 1)} of cost) and ${num(s.tco2, 1)} tCO₂e a year.`,
      `Baseline: ${num(c.baseline.kWh / 1000, 1)} MWh, ${fmtRupees(c.baseline.cost_rs)}, ${num(c.baseline.tco2, 1)} tCO₂e → optimized: ${num(c.optimized.kWh / 1000, 1)} MWh, ${fmtRupees(c.optimized.cost_rs)}, ${num(c.optimized.tco2, 1)} tCO₂e.`,
      s.cost_rs > 0 ? 'Use the toggle to switch between the two and see each total.' : 'The optimized policy does not save money for this selection — check the individual levers in the What-if simulator.',
    ],
  }
}
