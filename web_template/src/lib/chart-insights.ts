// Plain-language facts computed from whatever a chart is currently showing, for the
// "what does this chart say" popup (components/kpcl/chart-explainer.tsx).

export type Explanation = {
  title: string
  /** What is plotted, in one or two sentences. */
  shows: string
  /** How to read it: axes, colours, what "good" looks like. */
  read?: string
  /** What the data on screen right now implies. Computed from the data. */
  says: string[]
}

export type Row = Record<string, unknown>

export type Summary = {
  n: number
  mean: number
  min: number
  max: number
  minX: string
  maxX: string
  first: number
  last: number
  /** Mean of the last third vs the first third, as a fraction (0.1 = +10%). null if too short. */
  trend: number | null
}

/** Indian digit grouping, fixed decimals. */
export function num(v: number, digits = 1): string {
  return v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function pct(fraction: number, digits = 0): string {
  return `${(fraction * 100).toFixed(digits)}%`
}

export function summarize(data: Row[] | undefined | null, xKey: string, key: string): Summary | null {
  const pts: { x: string; v: number }[] = []
  for (const r of data ?? []) {
    const v = r[key]
    if (typeof v === 'number' && Number.isFinite(v)) pts.push({ x: String(r[xKey] ?? ''), v })
  }
  if (pts.length === 0) return null
  let min = pts[0]
  let max = pts[0]
  let sum = 0
  for (const p of pts) {
    sum += p.v
    if (p.v < min.v) min = p
    if (p.v > max.v) max = p
  }
  let trend: number | null = null
  if (pts.length >= 6) {
    const third = Math.floor(pts.length / 3)
    const avg = (a: typeof pts) => a.reduce((s, p) => s + p.v, 0) / a.length
    const head = avg(pts.slice(0, third))
    const tail = avg(pts.slice(-third))
    if (Math.abs(head) > 1e-9) trend = (tail - head) / Math.abs(head)
  }
  return {
    n: pts.length,
    mean: sum / pts.length,
    min: min.v,
    max: max.v,
    minX: min.x,
    maxX: max.x,
    first: pts[0].v,
    last: pts[pts.length - 1].v,
    trend,
  }
}

/** "rose 18% across the window" / "fell 7% …" / "stayed roughly level (within ±5%)". */
export function trendPhrase(s: Summary | null, steady = 0.05): string {
  if (!s || s.trend === null) return 'too few points to judge a trend'
  if (Math.abs(s.trend) <= steady) return `stayed roughly level (within ±${pct(steady)})`
  return `${s.trend > 0 ? 'rose' : 'fell'} ${pct(Math.abs(s.trend))} from the start to the end of the window`
}

export function trendDirection(s: Summary | null, steady = 0.05): 'up' | 'down' | 'flat' | 'unknown' {
  if (!s || s.trend === null) return 'unknown'
  if (Math.abs(s.trend) <= steady) return 'flat'
  return s.trend > 0 ? 'up' : 'down'
}

/** "averaged 2.1 bar, from 1.8 (10 Mar 04:00) to 2.6 (14 Mar 11:15)". */
export function rangePhrase(s: Summary, unit: string, digits = 1, fmtX: (x: string) => string = (x) => x): string {
  const u = unit ? ` ${unit}` : ''
  return `averaged ${num(s.mean, digits)}${u}, from ${num(s.min, digits)} (${fmtX(s.minX)}) to ${num(s.max, digits)} (${fmtX(s.maxX)})`
}

/** Count and share of points strictly above a threshold. */
export function shareAbove(data: Row[] | undefined | null, key: string, threshold: number) {
  let n = 0
  let above = 0
  for (const r of data ?? []) {
    const v = r[key]
    if (typeof v !== 'number' || !Number.isFinite(v)) continue
    n += 1
    if (v > threshold) above += 1
  }
  return { n, above, share: n ? above / n : 0 }
}

export function sum(data: Row[] | undefined | null, key: string): number {
  let t = 0
  for (const r of data ?? []) {
    const v = r[key]
    if (typeof v === 'number' && Number.isFinite(v)) t += v
  }
  return t
}

/** Pearson correlation of two columns over rows where both are numbers; null if undefined. */
export function correlation(data: Row[] | undefined | null, a: string, b: string): number | null {
  const xs: number[] = []
  const ys: number[] = []
  for (const r of data ?? []) {
    const x = r[a]
    const y = r[b]
    if (typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y)) {
      xs.push(x)
      ys.push(y)
    }
  }
  if (xs.length < 3) return null
  const mx = xs.reduce((s, v) => s + v, 0) / xs.length
  const my = ys.reduce((s, v) => s + v, 0) / ys.length
  let sxy = 0
  let sxx = 0
  let syy = 0
  for (let i = 0; i < xs.length; i++) {
    sxy += (xs[i] - mx) * (ys[i] - my)
    sxx += (xs[i] - mx) ** 2
    syy += (ys[i] - my) ** 2
  }
  return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : null
}

export const SIMULATED = 'All figures come from the benchmark-calibrated simulation, not real KPCL meters.'
