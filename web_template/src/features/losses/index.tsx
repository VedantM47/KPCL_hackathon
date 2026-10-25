import { useMemo } from 'react'
import { Droplets, Gauge, Leaf, Wallet } from 'lucide-react'
import { usePlant } from '@/context/plant-context'
import { useLeaksDaily, useLossesSummary } from '@/hooks/use-kpcl'
import { fmtRupees, fmtShortDate, fmtTco2 } from '@/lib/format'
import { explainLeakCost } from '@/lib/chart-explanations'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { PageShell } from '@/components/kpcl/page-header'
import { TrendChart } from '@/components/kpcl/trend-chart'

const COMPRESSORS = ['CMP-CENT-01', 'CMP-REC-01', 'CMP-SCR-01']

export function LossTracker() {
  const { plant, info } = usePlant()
  const { data: summary, isLoading } = useLossesSummary()
  const { data: daily } = useLeaksDaily()

  // one row per day, one avoidable-Rs column per compressor
  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string>>()
    for (const r of daily ?? []) {
      const row = byDate.get(r.date) ?? { date: r.date }
      row[r.asset_id] = r.avoidable_rs
      byDate.set(r.date, row)
    }
    return [...byDate.values()]
  }, [daily])

  const t = summary?.totals
  const worst = summary?.leaks_by_asset.slice().sort((a, b) => b.avoidable_rs - a.avoidable_rs)[0]

  return (
    <PageShell
      title={plant === 'ALL' ? 'Loss Tracker' : `${info?.name ?? plant} — Loss Tracker`}
      description='What compressed-air leaks and flagged anomalies cost in rupees and CO₂ — benchmark-calibrated simulation'
    >
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
        <KpiCard
          label='Avoidable Leak Cost'
          value={isLoading ? '—' : fmtRupees(t?.avoidable_leak_rs)}
          sub='per year, above background floor'
          icon={<Droplets className='size-4' />}
        />
        <KpiCard
          label='Leak Energy'
          value={isLoading || !t ? '—' : `${(t.avoidable_leak_kwh / 1000).toFixed(1)} MWh`}
          sub={t ? `${fmtTco2(summary?.totals.avoidable_leak_tco2)} Scope 2` : undefined}
          icon={<Leaf className='size-4' />}
        />
        <KpiCard
          label='Anomaly Excess Draw'
          value={isLoading ? '—' : fmtRupees(t?.anomaly_excess_rs)}
          sub={t ? `${(t.anomaly_excess_kwh / 1000).toFixed(1)} MWh above normal` : undefined}
          icon={<Gauge className='size-4' />}
        />
        <KpiCard
          label='Worst Leak'
          value={isLoading || !worst ? '—' : worst.asset_id}
          sub={worst ? `${fmtRupees(worst.avoidable_rs)}/yr · fix to save` : undefined}
          icon={<Wallet className='size-4' />}
        />
      </div>

      <Card className='mt-4'>
        <CardHeader className='pb-2'>
          <CardTitle className='text-sm font-medium'>Avoidable leak cost per day (₹)</CardTitle>
        </CardHeader>
        <CardContent>
          {!daily ? (
            <Skeleton className='h-52 w-full' />
          ) : (
            <TrendChart
              explain={() => explainLeakCost(chartData as never[], ['CMP-CENT-01', 'CMP-REC-01', 'CMP-SCR-01'])}
              data={chartData}
              xKey='date'
              xTickFormatter={fmtShortDate}
              series={[
                { key: 'CMP-CENT-01', label: 'CMP-CENT-01', color: 'brand' },
                { key: 'CMP-REC-01', label: 'CMP-REC-01', color: 'neutral' },
                { key: 'CMP-SCR-01', label: 'CMP-SCR-01 (standby, served by running units)', color: 'warning' },
              ]}
            />
          )}
        </CardContent>
      </Card>

      <div className='mt-3 grid gap-3 lg:grid-cols-2'>
        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Leaks by compressor (annual)</CardTitle>
          </CardHeader>
          <CardContent className='px-0'>
            <div className='overflow-x-auto'>
              <table className='w-full text-sm'>
                <thead>
                  <tr className='border-b text-left text-[11px] text-muted-foreground uppercase'>
                    <th className='px-4 py-2'>Asset</th>
                    <th className='px-2 py-2 text-right'>Floor m³/min</th>
                    <th className='px-2 py-2 text-right'>kWh</th>
                    <th className='px-2 py-2 text-right'>₹</th>
                    <th className='px-4 py-2 text-right'>tCO₂e</th>
                  </tr>
                </thead>
                <tbody>
                  {summary?.leaks_by_asset
                    .filter((a) => COMPRESSORS.includes(a.asset_id))
                    .map((a) => (
                      <tr key={a.asset_id} className='border-b border-border/50 last:border-0'>
                        <td className='px-4 py-2 font-mono text-xs'>{a.asset_id}</td>
                        <td className='px-2 py-2 text-right font-mono tabular-nums'>{a.leak_floor_m3min.toFixed(1)}</td>
                        <td className='px-2 py-2 text-right font-mono tabular-nums'>{a.avoidable_kwh.toFixed(0)}</td>
                        <td className='px-2 py-2 text-right font-mono tabular-nums'>{fmtRupees(a.avoidable_rs)}</td>
                        <td className='px-4 py-2 text-right font-mono tabular-nums'>{a.avoidable_tco2.toFixed(1)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Flagged-anomaly excess draw by asset (annual)</CardTitle>
          </CardHeader>
          <CardContent className='px-0'>
            <div className='overflow-x-auto'>
              <table className='w-full text-sm'>
                <thead>
                  <tr className='border-b text-left text-[11px] text-muted-foreground uppercase'>
                    <th className='px-4 py-2'>Asset</th>
                    <th className='px-2 py-2 text-right'>Intervals</th>
                    <th className='px-2 py-2 text-right'>kWh</th>
                    <th className='px-4 py-2 text-right'>₹</th>
                  </tr>
                </thead>
                <tbody>
                  {summary?.anomaly_excess_by_asset.map((a) => (
                    <tr key={a.asset_id} className='border-b border-border/50 last:border-0'>
                      <td className='px-4 py-2 font-mono text-xs'>{a.asset_id}</td>
                      <td className='px-2 py-2 text-right font-mono tabular-nums'>{a.flagged_intervals}</td>
                      <td className='px-2 py-2 text-right font-mono tabular-nums'>{a.excess_kwh.toFixed(0)}</td>
                      <td className='px-4 py-2 text-right font-mono tabular-nums'>{fmtRupees(a.excess_rs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      {summary && <p className='text-muted-foreground mt-4 text-[11px]'>{summary.method}</p>}
    </PageShell>
  )
}
