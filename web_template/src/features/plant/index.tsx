import { FileText, Factory, Leaf, Sun, Zap } from 'lucide-react'
import { usePlant } from '@/context/plant-context'
import { useAssetSeries, useForecastDemand, useKpis, usePlantsCompare } from '@/hooks/use-kpcl'
import { kpclApi } from '@/lib/kpcl-api'
import { fmtKwh, fmtPct, fmtRupees, fmtTco2 } from '@/lib/format'
import { cn } from '@/lib/utils'
import { explainPlantComparison, explainSolarGeneration } from '@/lib/chart-explanations'
import { Button } from '@/components/ui/button'
import { ChartExplainer } from '@/components/kpcl/chart-explainer'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { PageShell } from '@/components/kpcl/page-header'
import { ForecastCard } from '@/components/kpcl/forecast-card'
import { TrendChart } from '@/components/kpcl/trend-chart'

export function PlantOverview() {
  const { plant, setPlant, info, hasAsset } = usePlant()
  const { data: kpis, isLoading: kpisLoading } = useKpis()
  const { data: plants, isLoading: plantsLoading } = usePlantsCompare()
  const { data: forecast } = useForecastDemand()
  const ownsSolar = hasAsset('SOLAR-SASWAD-01')
  const { data: solarSeries, isLoading: solarLoading } = useAssetSeries(
    'SOLAR-SASWAD-01',
    { res: '1d' },
    plant === 'ALL' || ownsSolar
  )

  const contractKva = kpis?.contract_kva
  const peakRisk = kpis && contractKva ? kpis.peak_demand_kva / contractKva : undefined
  const maxKwh = plants ? Math.max(...plants.map((p) => p.kwh_total)) : 1

  return (
    <PageShell
      title={plant === 'ALL' ? 'Plant Overview' : `${info?.name ?? plant} — Overview`}
      description={
        plant === 'ALL'
          ? 'Hadapsar · Saswad · Nashik — full year, benchmark-calibrated simulation'
          : `${info?.division ?? ''} · full year, benchmark-calibrated simulation`
      }
      actions={
        <Button variant='outline' size='sm' asChild>
          <a href={kpclApi.plantReportUrl(plant)} download>
            <FileText className='mr-1 size-3.5' /> Plant report PDF
          </a>
        </Button>
      }
    >
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-5'>
        <KpiCard
          label='Total Energy'
          value={kpisLoading ? '—' : fmtKwh(kpis?.total_energy_kwh)}
          sub='grid + solar self-use'
          icon={<Zap className='size-4' />}
        />
        <KpiCard
          label='Energy Cost'
          value={kpisLoading ? '—' : fmtRupees(kpis?.cost_rs)}
          sub='ToD-weighted, illustrative tariff'
          icon={<Factory className='size-4' />}
        />
        <KpiCard
          label='Peak Demand'
          value={kpisLoading ? '—' : `${kpis?.peak_demand_kva.toFixed(0)} kVA`}
          sub={contractKva ? `vs ${contractKva} kVA contract` : undefined}
          trendColor={peakRisk && peakRisk > 0.85 ? 'warning' : 'default'}
          delta={
            peakRisk
              ? { value: fmtPct(peakRisk), direction: peakRisk > 0.85 ? 'up' : 'flat', good: peakRisk <= 0.85 }
              : undefined
          }
        />
        <KpiCard
          label='Scope 1 + 2'
          value={kpisLoading ? '—' : fmtTco2((kpis?.scope1_tco2 ?? 0) + (kpis?.scope2_tco2 ?? 0))}
          sub={kpis ? `${fmtTco2(kpis.scope1_tco2)} Scope 1 · ${fmtTco2(kpis.scope2_tco2)} Scope 2` : undefined}
          icon={<Leaf className='size-4' />}
        />
        <KpiCard
          label='Solar Share'
          value={kpisLoading ? '—' : fmtPct(kpis?.solar_share)}
          sub={kpis ? `${fmtTco2(kpis.solar_avoided_tco2)} avoided` : undefined}
          icon={<Sun className='size-4' />}
        />
      </div>

      <div className='mt-4 grid gap-3 lg:grid-cols-5'>
        <Card className='min-w-0 lg:col-span-3'>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Plant comparison — click a row to switch plant</CardTitle>
          </CardHeader>
          <CardContent className='px-0'>
            {plantsLoading || !plants ? (
              <Skeleton className='mx-4 h-40 w-full' />
            ) : (
              <ChartExplainer explain={() => explainPlantComparison(plants)}>
                <div className='overflow-x-auto'>
                  <table className='w-full text-sm'>
                    <thead>
                      <tr className='border-b text-left text-[11px] text-muted-foreground uppercase'>
                        <th className='px-4 py-2'>Plant</th>
                        <th className='px-2 py-2'>Energy</th>
                        <th className='px-2 py-2 text-right'>Cost</th>
                        <th className='px-2 py-2 text-right'>tCO₂e</th>
                        <th className='px-2 py-2 text-right'>Peak / contract</th>
                        <th className='px-4 py-2 text-right'>Grid kWh/unit</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plants.map((p) => {
                        const ratio = p.peak_kva / p.contract_kva
                        return (
                          <tr
                            key={p.plant_id}
                            data-no-explain
                            onClick={() => setPlant(p.plant_id)}
                            className={cn(
                              'cursor-pointer border-b border-border/50 last:border-0 hover:bg-muted/50',
                              plant === p.plant_id && 'bg-muted/60'
                            )}
                          >
                            <td className='px-4 py-2'>
                              <p className='font-medium'>{p.plant_name}</p>
                              <p className='text-[11px] text-muted-foreground'>{p.division}</p>
                            </td>
                            <td className='w-40 px-2 py-2'>
                              <p className='font-mono text-xs tabular-nums'>{fmtKwh(p.kwh_total)}</p>
                              <div className='mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted'>
                                <div className='h-full rounded-full bg-chart-1' style={{ width: `${(p.kwh_total / maxKwh) * 100}%` }} />
                              </div>
                            </td>
                            <td className='px-2 py-2 text-right font-mono text-xs whitespace-nowrap tabular-nums'>{fmtRupees(p.cost_rs)}</td>
                            <td className='px-2 py-2 text-right font-mono text-xs tabular-nums'>
                              {(p.scope1_tco2 + p.scope2_tco2).toFixed(0)}
                            </td>
                            <td
                              className={cn(
                                'px-2 py-2 text-right font-mono text-xs tabular-nums',
                                ratio > 1 && 'text-destructive'
                              )}
                            >
                              {p.peak_kva.toFixed(0)} / {p.contract_kva.toFixed(0)}
                            </td>
                            <td className='px-4 py-2 text-right font-mono text-xs tabular-nums'>
                              {p.kwh_per_unit ? p.kwh_per_unit.toFixed(0) : '—'}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </ChartExplainer>
            )}
          </CardContent>
        </Card>

        <ForecastCard forecast={forecast} className='lg:col-span-2' />
      </div>

      {(plant === 'ALL' || ownsSolar) && (
        <Card className='mt-3'>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Solar generation vs self-consumption (daily)</CardTitle>
          </CardHeader>
          <CardContent>
            {solarLoading || !solarSeries ? (
              <Skeleton className='h-48 w-full' />
            ) : (
              <TrendChart
                explain={() => explainSolarGeneration((solarSeries ?? []) as never[])}
                data={solarSeries as never[]}
                xKey='ts'
                yUnit=' kW'
                series={[
                  { key: 'kW_generated', label: 'Generated', color: 'brand' },
                  { key: 'kW_self_consumed', label: 'Self-consumed', color: 'neutral' },
                ]}
              />
            )}
          </CardContent>
        </Card>
      )}

      <p className='mt-4 text-[11px] text-muted-foreground'>
        Per-plant figures are an allocation of the simulated company meter: load, cost and Scope 2 follow each plant's
        share of metered load; Scope 1 follows asset ownership; the solar credit is shared in proportion to load
        (virtual net-metering). Contract demands per plant are assumed. See generator/plants.py.
      </p>
    </PageShell>
  )
}
