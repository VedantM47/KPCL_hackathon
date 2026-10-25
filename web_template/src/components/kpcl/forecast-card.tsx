import { useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ForecastResponse } from '@/lib/kpcl-api'
import { fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

// Day-ahead forecast for the replay's "tomorrow": P10-P90 band, central forecast, what was metered,
// and (in kVA) the contract line, plus the day's peak and breach-risk forecast. Same chart idiom as
// TrendChart: brand for the forecast, neutral for actuals, red only for the contract threshold.
export function ForecastCard({ forecast, className }: { forecast?: ForecastResponse; className?: string }) {
  const [unit, setUnit] = useState<'kVA' | 'kW'>('kVA')
  const contract = forecast?.metrics.contract_kva

  const data = useMemo(
    () =>
      forecast?.last_24h.map((r) => {
        const kva = unit === 'kVA'
        const lo = kva ? r.p10_kva : r.p10_kw
        const hi = kva ? r.p90_kva : r.p90_kw
        return {
          ts: r.ts,
          actual: (kva ? r.kVA : r.kW) ?? null,
          forecast: (kva ? r.pred_kva : r.pred_kw) ?? null,
          band: lo != null && hi != null ? [lo, hi] : null,
        }
      }) ?? [],
    [forecast, unit]
  )

  const day = forecast?.day
  const ev = forecast?.evaluation
  const risk = day?.breach_risk ?? 0
  const riskTone = risk >= 0.3 ? 'text-destructive' : risk >= 0.1 ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'

  return (
    <Card className={className}>
      <CardHeader className='flex flex-row items-start justify-between gap-2 pb-2'>
        <div>
          <CardTitle className='text-sm font-medium'>Day-ahead forecast{forecast?.date ? ` · ${forecast.date}` : ''}</CardTitle>
          <p className='text-muted-foreground mt-0.5 text-[11px]'>
            The replay&apos;s tomorrow, forecast from data up to today only
          </p>
        </div>
        <div className='flex gap-1'>
          {(['kVA', 'kW'] as const).map((u) => (
            <Button
              key={u}
              size='sm'
              variant={unit === u ? 'default' : 'outline'}
              className='h-7 px-2 text-xs'
              onClick={() => setUnit(u)}
            >
              {u}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {!forecast ? (
          <Skeleton className='h-56 w-full' />
        ) : (
          <>
            {forecast.covered === false ? (
              <p className='text-muted-foreground mb-2 text-xs'>
                No forecast before {forecast.first_forecast_date}: too little history to train on. Showing metered load.
              </p>
            ) : day ? (
              <div className='mb-2 flex flex-wrap gap-x-5 gap-y-1 text-xs'>
                <span>
                  Peak <span className='font-semibold tabular-nums'>≈ {day.peak_p50_kva.toFixed(0)} kVA</span>{' '}
                  <span className='text-muted-foreground tabular-nums'>
                    (80% range {day.peak_p10_kva.toFixed(0)}–{day.peak_p90_kva.toFixed(0)})
                  </span>
                </span>
                <span className={cn('font-semibold tabular-nums', riskTone)}>
                  Breach risk {(risk * 100).toFixed(0)}%
                </span>
                <span className='text-muted-foreground tabular-nums'>
                  Above 85% of contract: {(day.near_contract_risk * 100).toFixed(0)}%
                </span>
                {day.actual_peak_kva != null && (
                  <span className='text-muted-foreground tabular-nums'>Metered peak {day.actual_peak_kva.toFixed(0)} kVA</span>
                )}
              </div>
            ) : null}

            <ResponsiveContainer width='100%' height={210}>
              <ComposedChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' vertical={false} />
                <XAxis
                  dataKey='ts'
                  tickFormatter={fmtTime}
                  tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
                  tickLine={false}
                  axisLine={{ stroke: 'var(--border)' }}
                  minTickGap={24}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
                  tickLine={false}
                  axisLine={false}
                  width={68}
                  unit={` ${unit}`}
                  domain={[0, 'auto']}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'var(--popover)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: 'var(--muted-foreground)', marginBottom: 2 }}
                  labelFormatter={(v) => fmtTime(String(v))}
                  formatter={(value, name) => {
                    if (Array.isArray(value)) return [`${Number(value[0]).toFixed(0)}–${Number(value[1]).toFixed(0)}`, String(name)]
                    return [typeof value === 'number' ? value.toFixed(1) : '—', String(name)]
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} iconSize={10} />
                <Area
                  dataKey='band'
                  name='80% range'
                  stroke='none'
                  fill='var(--chart-1)'
                  fillOpacity={0.15}
                  isAnimationActive={false}
                />
                <Line
                  dataKey='forecast'
                  name='Forecast'
                  stroke='var(--chart-1)'
                  strokeWidth={1.75}
                  dot={false}
                  isAnimationActive={false}
                />
                <Line
                  dataKey='actual'
                  name='Metered'
                  stroke='var(--chart-2)'
                  strokeWidth={1.25}
                  dot={false}
                  isAnimationActive={false}
                />
                {unit === 'kVA' && contract != null && (
                  <ReferenceLine
                    y={contract}
                    ifOverflow='extendDomain'
                    stroke='var(--chart-4)'
                    strokeDasharray='4 3'
                    label={{ value: `contract ${contract.toFixed(0)}`, fontSize: 10, fill: 'var(--chart-4)', position: 'insideTopRight' }}
                  />
                )}
              </ComposedChart>
            </ResponsiveContainer>

            {ev && (
              <p className='text-muted-foreground mt-1 text-[11px] leading-relaxed'>
                Checked on {ev.days} days, each forecast using only earlier data: daily peak off by ±
                {ev.peak_mae_kva.toFixed(0)} kVA on average (bias {ev.peak_bias_kva >= 0 ? '+' : ''}
                {ev.peak_bias_kva.toFixed(0)}) vs ±{ev.peak_mae_last_week_kva.toFixed(0)} for &quot;same as last week&quot;; the 80%
                range held {(ev.band_coverage_p10_p90 * 100).toFixed(0)}% of readings; days above 85% of contract warned{' '}
                {ev.near_contract.caught}/{ev.near_contract.actual_days} (last week: {ev.near_contract.last_week_baseline.caught}).
                Simulated data.
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
