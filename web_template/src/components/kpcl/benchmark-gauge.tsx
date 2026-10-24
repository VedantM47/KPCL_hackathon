import { cn } from '@/lib/utils'

type BenchmarkGaugeProps = {
  value: number
  unit: string
  min: number
  max: number
  goodMax: number // <= this is "good" (lower is better for kW/TR, specific power)
  warnMax: number // <= this is "warning"; above is critical
  label: string
  precision?: number
}

// Bullet-style gauge: a single horizontal track, zoned good/warn/critical,
// with a marker for the current reading and a tick for the benchmark
// threshold. Reads at a glance, unlike a decorative radial dial.
export function BenchmarkGauge({ value, unit, min, max, goodMax, warnMax, label, precision = 3 }: BenchmarkGaugeProps) {
  const pct = (v: number) => Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100))
  const valuePct = pct(value)
  const goodPct = pct(goodMax)
  const warnPct = pct(warnMax)

  const status = value <= goodMax ? 'good' : value <= warnMax ? 'warn' : 'critical'
  const statusColor =
    status === 'good' ? 'text-emerald-600 dark:text-emerald-400' : status === 'warn' ? 'text-amber-600 dark:text-amber-400' : 'text-destructive'

  return (
    <div>
      <div className='flex items-baseline justify-between'>
        <span className='text-muted-foreground text-[11px] font-medium tracking-wide uppercase'>{label}</span>
        <span className={cn('font-mono text-sm font-semibold tabular-nums', statusColor)}>
          {value.toFixed(precision)} {unit}
        </span>
      </div>
      <div className='relative mt-2 h-2 w-full overflow-hidden rounded-full bg-muted'>
        <div
          className='absolute inset-y-0 left-0 bg-emerald-500/30'
          style={{ width: `${goodPct}%` }}
        />
        <div
          className='absolute inset-y-0 bg-amber-500/30'
          style={{ left: `${goodPct}%`, width: `${Math.max(0, warnPct - goodPct)}%` }}
        />
        <div
          className='absolute inset-y-0 bg-destructive/25'
          style={{ left: `${warnPct}%`, width: `${Math.max(0, 100 - warnPct)}%` }}
        />
        <div
          className='absolute top-1/2 h-3.5 w-1 -translate-y-1/2 rounded-full bg-foreground shadow-sm'
          style={{ left: `calc(${valuePct}% - 2px)` }}
        />
      </div>
      <div className='mt-1 flex justify-between text-[10px] text-muted-foreground tabular-nums'>
        <span>{min.toFixed(precision)}</span>
        <span>benchmark ≤ {goodMax.toFixed(precision)} {unit}</span>
        <span>{max.toFixed(precision)}</span>
      </div>
    </div>
  )
}
