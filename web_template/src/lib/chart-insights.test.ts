import { describe, expect, it } from 'vitest'
import { explainFaultTimeline, explainKwPerTr, explainLiveDemand, explainUnitsVsEnergy, explainWhatIf } from './chart-explanations'
import { correlation, shareAbove, summarize, trendDirection, trendPhrase } from './chart-insights'

const rows = (vals: number[]) => vals.map((v, i) => ({ x: `t${i}`, v }))

describe('summarize', () => {
  it('finds mean, extremes and where they happened', () => {
    const s = summarize(rows([3, 1, 4, 1, 5, 9]), 'x', 'v')!
    expect(s.mean).toBeCloseTo(23 / 6)
    expect([s.min, s.minX, s.max, s.maxX]).toEqual([1, 't1', 9, 't5'])
    expect([s.first, s.last, s.n]).toEqual([3, 9, 6])
  })
  it('skips nulls and non-numbers, and returns null with no data', () => {
    const s = summarize([{ x: 'a', v: null }, { x: 'b', v: 2 }, { x: 'c', v: 'oops' }], 'x', 'v')!
    expect(s.n).toBe(1)
    expect(summarize([], 'x', 'v')).toBeNull()
    expect(summarize(undefined, 'x', 'v')).toBeNull()
  })
  it('measures the trend as last third vs first third', () => {
    expect(summarize(rows([10, 10, 10, 10, 12, 12]), 'x', 'v')!.trend).toBeCloseTo(0.2)
    expect(summarize(rows([1, 2, 3]), 'x', 'v')!.trend).toBeNull()   // too short
  })
})

describe('trend wording', () => {
  it('says level within the steady band, rose/fell outside it', () => {
    expect(trendPhrase(summarize(rows([10, 10, 10, 10, 10.2, 10.2]), 'x', 'v'))).toMatch(/roughly level/)
    expect(trendPhrase(summarize(rows([10, 10, 10, 10, 15, 15]), 'x', 'v'))).toMatch(/^rose 50%/)
    expect(trendDirection(summarize(rows([10, 10, 10, 10, 5, 5]), 'x', 'v'))).toBe('down')
    expect(trendPhrase(null)).toMatch(/too few/)
  })
})

describe('shareAbove and correlation', () => {
  it('counts strictly-above points', () => {
    expect(shareAbove(rows([1, 5, 10, 10]), 'v', 5)).toEqual({ n: 4, above: 2, share: 0.5 })
  })
  it('is +1 for a perfect line and null when undefined', () => {
    const data = [1, 2, 3, 4].map((u) => ({ u, k: 10 * u + 3 }))
    expect(correlation(data, 'u', 'k')).toBeCloseTo(1)
    expect(correlation([{ u: 1, k: 1 }, { u: 1, k: 2 }, { u: 1, k: 3 }], 'u', 'k')).toBeNull()
  })
})

describe('chart explanations', () => {
  it('live demand: reports a breach when kVA crosses the contract', () => {
    const data = [300, 380, 410, 395].map((kVA, i) => ({ ts: `2025-05-20 0${i}:00:00`, kVA, contract: 400 }))
    const e = explainLiveDemand(data, 'All plants')
    expect(e.says[0]).toMatch(/395 kVA — 99% of the 400 kVA contract/)
    expect(e.says.join(' ')).toMatch(/1 tick went above the contract/)
  })
  it('live demand: reports headroom when far below contract', () => {
    const data = [100, 120, 110].map((kVA, i) => ({ ts: `t${i}`, kVA, contract: 400 }))
    expect(explainLiveDemand(data, 'X').says.join(' ')).toMatch(/never went above 85%.*280 kVA of headroom/)
  })
  it('kW/TR gauge: states the zone and the excess over benchmark', () => {
    expect(explainKwPerTr(0.97, 0.88, 1.05).says.join(' ')).toMatch(/warning zone.*10% more electricity/)
    expect(explainKwPerTr(0.8, 0.88, 1.05).says[0]).toMatch(/within the benchmark/)
  })
  it('units vs energy: handles plants with no production', () => {
    expect(explainUnitsVsEnergy([]).says[0]).toMatch(/no production records/)
  })
  it('fault timeline: finds the busiest asset and its longest run', () => {
    const daily = [
      { asset_id: 'A', date: '2025-01-01', rank: 4 },
      { asset_id: 'A', date: '2025-01-02', rank: 2 },
      { asset_id: 'A', date: '2025-01-03', rank: 2 },
      { asset_id: 'B', date: '2025-01-05', rank: 1 },
    ]
    const s = explainFaultTimeline(daily, ['A', 'B']).says.join(' ')
    expect(s).toMatch(/A was flagged on the most days \(3\); its longest unbroken run was 3 days/)
    expect(s).toMatch(/A 3 d \(1 critical\)/)
  })

  it('what-if: suggests the best levers when nothing is chosen, explains the combination when something is', () => {
    const opt = (option_label: string, rs_saved: number, kWh_saved: number) => ({
      option_label, option_value: option_label, rs_saved, kWh_saved, tco2_saved: kWh_saved / 1000, scope1_saved: 0, scope2_saved: kWh_saved / 1000, peak_kva_reduction: 2,
    })
    const grid = {
      baseline: { kWh: 1_000_000, cost_rs: 8_000_000, scope1: 10, scope2: 700, peak_kva: 430 },
      levers: [
        { lever: 'pressure', label: 'Pressure setpoint', options: [opt('6.5 bar', 120000, 15000), opt('7.5 bar', -60000, -8000)] },
        { lever: 'rig', label: 'Test rig timing', options: [opt('Off-peak', 40000, 0)] },
      ],
      note: '',
    }
    const none = explainWhatIf(grid, {}, { kWh: 0, rs: 0, tco2: 0, peak: 0, n: 0 }).says.join(' ')
    expect(none).toMatch(/No lever is changed yet/)
    expect(none).toMatch(/Pressure setpoint → 6\.5 bar/)
    const some = explainWhatIf(grid, { pressure: '7.5 bar', rig: 'Off-peak' }, { kWh: -8000, rs: -20000, tco2: -8, peak: 4, n: 2 }).says.join(' ')
    expect(some).toMatch(/With 2 changes/)
    expect(some).toMatch(/Pressure setpoint → 7\.5 bar costs money/)
    expect(some).toMatch(/approximation/)
  })
})
