import { useMemo, useState } from 'react'
import { usePlant } from '@/context/plant-context'
import { useAssetSeries, useKpis } from '@/hooks/use-kpcl'
import { fmtCop, fmtRupees, fmtTemp } from '@/lib/format'
import { explainCondenserApproach, explainCop, explainKwPerTr } from '@/lib/chart-explanations'
import { ChartExplainer } from '@/components/kpcl/chart-explainer'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { BenchmarkGauge } from '@/components/kpcl/benchmark-gauge'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { NoEquipment } from '@/components/kpcl/no-equipment'
import { PageShell } from '@/components/kpcl/page-header'
import { TrendChart } from '@/components/kpcl/trend-chart'

// Window lands inside CHILLER-SCR-01's condenser-fouling fault (2025-05-01 to
// 2025-07-31), so the degradation indicator has something real to show.
const DEFAULT_FROM = '2025-06-10'
const DEFAULT_TO = '2025-06-17'

type ScrPoint = {
  ts: string
  TR: number
  kW: number
  kw_per_tr: number
  COP: number | null
  condenser_approach_c: number
  refrigerant_charge_kg: number
}
type VamPoint = {
  ts: string
  TR: number
  kW_electrical: number
  kWh_thermal: number
  thermal_cop: number
  fuel_kg: number
}

export function Refrigeration() {
  const [assetId, setAssetId] = useState<'CHILLER-SCR-01' | 'CHILLER-VAM-01'>('CHILLER-SCR-01')
  const { hasAsset } = usePlant()
  const hasChillers = hasAsset('CHILLER-SCR-01')
  const { data, isLoading } = useAssetSeries(assetId, { from: DEFAULT_FROM, to: DEFAULT_TO, res: '15m' }, hasChillers)
  const { data: kpis } = useKpis()

  const blendedRate = kpis && kpis.grid_energy_kwh > 0 ? kpis.cost_rs / kpis.grid_energy_kwh : null
  // Hooks must run unconditionally on every render, so compute both branches'
  // derived stats up front rather than inside the assetId-dependent if/return.
  const scrStats = useScrStats(assetId === 'CHILLER-SCR-01' ? (data as ScrPoint[] | undefined) : undefined)

  if (!hasChillers) {
    return (
      <PageShell title='Refrigeration' description='Chilled-water plant'>
        <NoEquipment what='chillers' />
      </PageShell>
    )
  }

  if (assetId === 'CHILLER-SCR-01') {
    const series = (data ?? []) as ScrPoint[]
    const stats = scrStats
    return (
      <PageShell
        title='Refrigeration'
        description={`${DEFAULT_FROM} → ${DEFAULT_TO} · 15-min resolution`}
        actions={<ChillerTabs assetId={assetId} setAssetId={setAssetId} />}
      >
        <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
          <KpiCard label='Cooling Load' value={isLoading || !stats ? '—' : `${stats.avgTr.toFixed(1)} TR`} sub='window average' />
          <KpiCard label='COP' value={isLoading || !stats ? '—' : fmtCop(stats.avgCop)} sub='electric, TR·3.517/kW' />
          <KpiCard
            label='Condenser Approach'
            value={isLoading || !stats ? '—' : fmtTemp(stats.avgApproach)}
            sub='cleanest fouling indicator'
            trendColor={stats && stats.avgApproach > 5 ? 'warning' : 'default'}
          />
          <KpiCard
            label='Cost / TR-hour'
            value={isLoading || !stats || !blendedRate ? '—' : fmtRupees(stats.avgKwPerTr * blendedRate)}
            sub='kW/TR × blended tariff rate'
          />
        </div>

        <div className='mt-4 grid gap-3 lg:grid-cols-2'>
          <Card>
            <CardHeader className='pb-2'>
              <CardTitle className='text-sm font-medium'>kW/TR vs benchmark</CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading || !stats ? <Skeleton className='h-24 w-full' /> : (
                <ChartExplainer explain={() => explainKwPerTr(stats.avgKwPerTr, 0.88, 1.05)}>
                  <BenchmarkGauge
                    label='kW per TR'
                    unit='kW/TR'
                    value={stats.avgKwPerTr}
                    min={0.7}
                    max={1.3}
                    goodMax={0.88}
                    warnMax={1.05}
                  />
                </ChartExplainer>
              )}
              <p className='mt-6 text-[11px] text-muted-foreground'>
                Benchmark band is an assumed typical-screw-chiller rule of thumb (0.85 kW/TR base in config.yaml),
                not a vendor-certified spec — VERIFY before external use.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className='pb-2'>
              <CardTitle className='text-sm font-medium'>Condenser approach — fouling trend</CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? <Skeleton className='h-40 w-full' /> : (
                <TrendChart
                  explain={() => explainCondenserApproach(series as never[])}
                  data={series as never[]}
                  xKey='ts'
                  yUnit='°C'
                  height={180}
                  series={[{ key: 'condenser_approach_c', label: 'Approach temp', color: 'warning' }]}
                  xTickFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                />
              )}
            </CardContent>
          </Card>
        </div>

        <Card className='mt-3'>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>COP trend</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? <Skeleton className='h-40 w-full' /> : (
              <TrendChart
                explain={() => explainCop(series as never[], 'COP')}
                data={series as never[]}
                xKey='ts'
                height={160}
                series={[{ key: 'COP', label: 'COP', color: 'brand' }]}
                xTickFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
              />
            )}
          </CardContent>
        </Card>
      </PageShell>
    )
  }

  const series = (data ?? []) as VamPoint[]
  const avgThermalCop = series.length ? series.reduce((s, p) => s + p.thermal_cop, 0) / series.length : null
  const avgTr = series.length ? series.reduce((s, p) => s + p.TR, 0) / series.length : null
  const totalFuel = series.length ? series.reduce((s, p) => s + p.fuel_kg, 0) : null

  return (
    <PageShell
      title='Refrigeration'
      description={`${DEFAULT_FROM} → ${DEFAULT_TO} · 15-min resolution`}
      actions={<ChillerTabs assetId={assetId} setAssetId={setAssetId} />}
    >
      <div className='grid gap-3 sm:grid-cols-3'>
        <KpiCard label='Cooling Load' value={isLoading || avgTr === null ? '—' : `${avgTr.toFixed(1)} TR`} sub='window average' />
        <KpiCard
          label='Thermal COP'
          value={isLoading || avgThermalCop === null ? '—' : fmtCop(avgThermalCop)}
          sub='target 0.7–1.2 (vapour absorption)'
        />
        <KpiCard
          label='Gas Consumed'
          value={isLoading || totalFuel === null ? '—' : `${totalFuel.toFixed(1)} kg`}
          sub='heat input fuel, this window — VERIFY heating value assumption'
        />
      </div>
      <Card className='mt-4'>
        <CardHeader className='pb-2'>
          <CardTitle className='text-sm font-medium'>Thermal COP trend</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? <Skeleton className='h-48 w-full' /> : (
            <TrendChart
              explain={() => explainCop(series as never[], 'thermal_cop')}
              data={series as never[]}
              xKey='ts'
              series={[{ key: 'thermal_cop', label: 'Thermal COP', color: 'brand' }]}
              xTickFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
            />
          )}
        </CardContent>
      </Card>
    </PageShell>
  )
}

function ChillerTabs({
  assetId,
  setAssetId,
}: {
  assetId: string
  setAssetId: (v: 'CHILLER-SCR-01' | 'CHILLER-VAM-01') => void
}) {
  return (
    <Tabs value={assetId} onValueChange={(v) => setAssetId(v as 'CHILLER-SCR-01' | 'CHILLER-VAM-01')}>
      <TabsList>
        <TabsTrigger value='CHILLER-SCR-01' className='font-mono text-xs'>
          CHILLER-SCR-01 (electric)
        </TabsTrigger>
        <TabsTrigger value='CHILLER-VAM-01' className='font-mono text-xs'>
          CHILLER-VAM-01 (gas-fired)
        </TabsTrigger>
      </TabsList>
    </Tabs>
  )
}

function useScrStats(series: ScrPoint[] | undefined) {
  return useMemo(() => {
    if (!series || series.length === 0) return null
    const avgTr = series.reduce((s, p) => s + p.TR, 0) / series.length
    const avgKwPerTr = series.reduce((s, p) => s + p.kw_per_tr, 0) / series.length
    const copVals = series.map((p) => p.COP).filter((v): v is number => v !== null)
    const avgCop = copVals.length ? copVals.reduce((a, b) => a + b, 0) / copVals.length : null
    const avgApproach = series.reduce((s, p) => s + p.condenser_approach_c, 0) / series.length
    return { avgTr, avgKwPerTr, avgCop, avgApproach }
  }, [series])
}
