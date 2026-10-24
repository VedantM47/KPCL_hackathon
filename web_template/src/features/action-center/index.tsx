import { useState } from 'react'
import { FileText } from 'lucide-react'
import { usePlant } from '@/context/plant-context'
import { useAnomaliesDaily, useRecommendations, useScenarioCompare } from '@/hooks/use-kpcl'
import { kpclApi } from '@/lib/kpcl-api'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { fmtRupees, fmtTco2 } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { FaultTimeline } from '@/components/kpcl/fault-timeline'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { PageShell } from '@/components/kpcl/page-header'
import { PeakPlanCard } from '@/components/kpcl/peak-plan-card'
import { WhatIfCard } from '@/components/kpcl/whatif-card'

const TIMELINE_ASSETS = [
  'CMP-CENT-01', 'CMP-SCR-01', 'CMP-REC-01', 'CHILLER-SCR-01', 'CNC-GEAR-01', 'FURNACE-HT-01', 'PAINT-BOOTH-01',
]

export function ActionCenter() {
  const { plant, info, hasAsset } = usePlant()
  const { data: recs, isLoading: recsLoading } = useRecommendations()
  const { data: compare, isLoading: compareLoading } = useScenarioCompare()
  const { data: daily, isLoading: dailyLoading } = useAnomaliesDaily()
  const [scenario, setScenario] = useState<'baseline' | 'optimized'>('baseline')

  const active = compare?.[scenario]

  return (
    <PageShell
      title={plant === 'ALL' ? 'Action Center' : `${info?.name ?? plant} — Action Center`}
      actions={
        <Button variant='outline' size='sm' asChild>
          <a href={kpclApi.plantReportUrl(plant)} download>
            <FileText className='mr-1 size-3.5' /> Plant report PDF
          </a>
        </Button>
      }
      description='Each saving below is a real baseline-vs-counterfactual simulation diff, never estimated inline'
    >
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
        <KpiCard
          label='Annual Savings (optimized vs baseline)'
          value={compareLoading || !compare ? '—' : fmtRupees(compare.savings.cost_rs)}
          sub={compare ? `${compare.savings.kWh.toFixed(0)} kWh · ${fmtTco2(compare.savings.tco2)}` : undefined}
        />
        <KpiCard
          label='Top Single Action'
          value={recsLoading || !recs?.length ? '—' : fmtRupees(recs[0].rs_saved)}
          sub={recs?.length ? recs[0].action : undefined}
        />
        <KpiCard
          label='Faults Flagged (annual)'
          value={dailyLoading || !daily ? '—' : `${daily.length}`}
          sub='asset-days with a flagged anomaly'
        />
      </div>

      <div className='mt-4'>
        <PeakPlanCard />
      </div>

      <div className='mt-3'>
        <WhatIfCard />
      </div>

      <Card className='mt-4'>
        <CardHeader className='flex-row items-center justify-between pb-2'>
          <CardTitle className='text-sm font-medium'>Baseline vs optimized — what-if toggle</CardTitle>
          <div className='flex gap-1 rounded-md border border-border p-0.5 text-xs'>
            {(['baseline', 'optimized'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setScenario(s)}
                className={cn(
                  'rounded-sm px-2.5 py-1 font-medium capitalize transition-colors',
                  scenario === s ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {s}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          {compareLoading || !active ? (
            <Skeleton className='h-16 w-full' />
          ) : (
            <div className='grid grid-cols-3 gap-4 font-mono text-sm tabular-nums'>
              <div>
                <p className='text-[11px] text-muted-foreground uppercase'>Energy</p>
                <p className='text-lg font-semibold'>{(active.kWh / 1000).toFixed(1)} MWh</p>
              </div>
              <div>
                <p className='text-[11px] text-muted-foreground uppercase'>Cost</p>
                <p className='text-lg font-semibold'>{fmtRupees(active.cost_rs)}</p>
              </div>
              <div>
                <p className='text-[11px] text-muted-foreground uppercase'>Emissions</p>
                <p className='text-lg font-semibold'>{fmtTco2(active.tco2)}</p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className='mt-3'>
        <CardHeader className='pb-2'>
          <CardTitle className='text-sm font-medium'>Ranked recommendations</CardTitle>
        </CardHeader>
        <CardContent className='px-0'>
          {recsLoading || !recs ? (
            <Skeleton className='mx-4 h-64 w-full' />
          ) : (
            <div className='overflow-x-auto'>
              <table className='w-full text-sm'>
                <thead>
                  <tr className='border-b border-border text-left text-[11px] text-muted-foreground uppercase'>
                    <th className='px-4 py-2'>#</th>
                    <th className='px-2 py-2'>Action</th>
                    <th className='px-2 py-2'>Type</th>
                    <th className='px-2 py-2 text-right'>kWh/yr</th>
                    <th className='px-2 py-2 text-right'>₹/yr</th>
                    <th className='px-4 py-2 text-right'>tCO₂e/yr</th>
                  </tr>
                </thead>
                <tbody>
                  {recs.map((r) => (
                    <tr key={r.action} className='border-b border-border/50 last:border-0'>
                      <td className='px-4 py-2 font-mono text-muted-foreground'>{r.rank}</td>
                      <td className='px-2 py-2'>{r.action}</td>
                      <td className='px-2 py-2'>
                        <Badge variant='outline' className='text-[10px] capitalize'>
                          {r.type.replace('_', ' ')}
                        </Badge>
                      </td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right font-mono tabular-nums',
                          r.kWh_saved < 0 && 'text-destructive'
                        )}
                      >
                        {r.kWh_saved.toFixed(0)}
                      </td>
                      <td
                        className={cn(
                          'px-2 py-2 text-right font-mono tabular-nums',
                          r.rs_saved < 0 && 'text-destructive'
                        )}
                      >
                        {fmtRupees(r.rs_saved)}
                      </td>
                      <td
                        className={cn(
                          'px-4 py-2 text-right font-mono tabular-nums',
                          r.tco2_saved < 0 && 'text-destructive'
                        )}
                      >
                        {fmtTco2(r.tco2_saved)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className='mt-2 px-4 text-[11px] text-muted-foreground'>
            Negative rows aren't errors — "Switch chiller sequencing" trades Scope 1 gas for a much larger Scope 2
            grid draw, and "Start furnace earlier" is sensitive to ToD boundaries. See ml/recommendations.py.
          </p>
        </CardContent>
      </Card>

      <Card className='mt-3'>
        <CardHeader className='pb-2'>
          <CardTitle className='text-sm font-medium'>Fault timeline — flagged anomalies, 2025</CardTitle>
        </CardHeader>
        <CardContent>
          {dailyLoading || !daily ? (
            <Skeleton className='h-48 w-full' />
          ) : (
            <FaultTimeline daily={daily} assetIds={TIMELINE_ASSETS.filter((a) => hasAsset(a))} startDate='2025-01-01' endDate='2025-12-31' />
          )}
        </CardContent>
      </Card>
    </PageShell>
  )
}
