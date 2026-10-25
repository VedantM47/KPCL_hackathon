import { useMemo, useState } from 'react'
import { usePlant } from '@/context/plant-context'
import { useAnomalies, useAssetSeries } from '@/hooks/use-kpcl'
import { fmtKw, fmtSpecificPower } from '@/lib/format'
import { explainLeakFlow, explainPressure } from '@/lib/chart-explanations'
import { ChartExplainer } from '@/components/kpcl/chart-explainer'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { NoEquipment } from '@/components/kpcl/no-equipment'
import { PageShell } from '@/components/kpcl/page-header'
import { PressureSawtoothChart } from '@/components/kpcl/pressure-sawtooth-chart'
import { SeverityBadge } from '@/components/kpcl/severity-badge'
import { TrendChart } from '@/components/kpcl/trend-chart'

const ASSETS = [
  { id: 'CMP-CENT-01', label: 'CMP-CENT-01 (lead)', lower: 6.8, upper: 7.4 },
  { id: 'CMP-SCR-01', label: 'CMP-SCR-01 (lag)', lower: 6.8, upper: 7.4 },
  { id: 'CMP-REC-01', label: 'CMP-REC-01 (Nashik)', lower: 6.8, upper: 7.4 },
  { id: 'TEST-RIG-CNG-01', label: 'TEST-RIG-CNG-01', lower: 6.8, upper: 7.3 },
] as const

// A week that lands inside CMP-SCR-01's injected leak-growth fault window
// (2025-02-01 to 2025-04-15) so the widget has something real to show by default.
const DEFAULT_FROM = '2025-03-10'
const DEFAULT_TO = '2025-03-17'

type CompressorPoint = {
  ts: string
  kW: number
  pressure_bar: number
  pressure_bar_min: number
  pressure_bar_max: number
  flow_m3min: number
  leak_flow_m3min: number
  specific_power_kwh_m3: number | null
  load_fraction: number
  cycle_count: number
  sequencing_state: string
}

export function CompressorRoom() {
  const { hasAsset } = usePlant()
  const assets = ASSETS.filter((a) => hasAsset(a.id))
  const [picked, setAssetId] = useState<string>(ASSETS[0].id)
  const asset = assets.find((a) => a.id === picked) ?? assets[0]
  const assetId = asset?.id ?? ''

  const { data, isLoading } = useAssetSeries(assetId, { from: DEFAULT_FROM, to: DEFAULT_TO, res: '15m' }, !!assetId)
  const { data: anomalies } = useAnomalies({ asset_id: assetId, from: DEFAULT_FROM, to: DEFAULT_TO })
  const series = (data ?? []) as CompressorPoint[]

  const stats = useMemo(() => {
    if (series.length === 0) return null
    const avgKw = series.reduce((s, p) => s + p.kW, 0) / series.length
    const specPowerVals = series.map((p) => p.specific_power_kwh_m3).filter((v): v is number => v !== null)
    const avgSpecPower = specPowerVals.length ? specPowerVals.reduce((a, b) => a + b, 0) / specPowerVals.length : null
    const totalCycles = series[series.length - 1].cycle_count - series[0].cycle_count
    const avgLeak = series.reduce((s, p) => s + p.leak_flow_m3min, 0) / series.length
    const avgDuty = series.reduce((s, p) => s + p.load_fraction, 0) / series.length
    return { avgKw, avgSpecPower, totalCycles, avgLeak, avgDuty }
  }, [series])

  const inSpecBand = stats?.avgSpecPower !== null && stats && stats.avgSpecPower! >= 0.1 && stats.avgSpecPower! <= 0.13

  if (!asset) {
    return (
      <PageShell title='Compressor Room' description='Compressed-air generation'>
        <NoEquipment what='compressors' />
      </PageShell>
    )
  }

  return (
    <PageShell
      title='Compressor Room'
      description={`${DEFAULT_FROM} → ${DEFAULT_TO} · 15-min resolution · sequencing: ${series[0]?.sequencing_state ?? '—'}`}
    >
      <Tabs value={assetId} onValueChange={setAssetId} className='mb-4'>
        <TabsList>
          {assets.map((a) => (
            <TabsTrigger key={a.id} value={a.id} className='font-mono text-xs'>
              {a.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
        <KpiCard label='Mean Power' value={isLoading || !stats ? '—' : fmtKw(stats.avgKw)} sub='window average' />
        <KpiCard
          label='Specific Power'
          value={isLoading || !stats || stats.avgSpecPower === null ? '—' : fmtSpecificPower(stats.avgSpecPower)}
          sub='target 0.10–0.13 kWh/m³ @ 7 bar'
          trendColor={inSpecBand ? 'default' : 'warning'}
        />
        <KpiCard
          label='Load/Unload Cycles'
          value={isLoading || !stats ? '—' : `${stats.totalCycles}`}
          sub={`over ${series.length ? Math.round(series.length / 96) : 0} days`}
        />
        <KpiCard
          label='Leak Flow'
          value={isLoading || !stats ? '—' : `${stats.avgLeak.toFixed(2)} m³/min`}
          sub={`${isLoading || !stats ? '—' : (stats.avgDuty * 100).toFixed(0)}% duty cycle`}
          trendColor={stats && stats.avgLeak > 2 ? 'warning' : 'default'}
        />
      </div>

      <div className='mt-4 grid gap-3 lg:grid-cols-2'>
        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Header pressure — setpoint band {asset.lower}–{asset.upper} bar</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? <Skeleton className='h-48 w-full' /> : (
              <ChartExplainer explain={() => explainPressure(series as never[], asset.id, asset.lower, asset.upper)}>
                <PressureSawtoothChart data={series} lowerBar={asset.lower} upperBar={asset.upper} />
              </ChartExplainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Leak flow — rising duty signals an undetected leak</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? <Skeleton className='h-48 w-full' /> : (
              <TrendChart
                explain={() => explainLeakFlow(series as never[], assetId)}
                data={series as never[]}
                xKey='ts'
                yUnit=' m³/min'
                series={[{ key: 'leak_flow_m3min', label: 'Leak flow', color: 'warning' }]}
                xTickFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <Card className='mt-3'>
        <CardHeader className='pb-2'>
          <CardTitle className='text-sm font-medium'>Flagged intervals in this window</CardTitle>
        </CardHeader>
        <CardContent>
          {!anomalies || anomalies.length === 0 ? (
            <p className='text-sm text-muted-foreground'>No anomalies flagged for {assetId} in this window.</p>
          ) : (
            <div className='space-y-1'>
              {anomalies.slice(0, 8).map((a) => (
                <div key={a.ts} className='flex items-center justify-between border-b border-border/50 py-1 text-xs last:border-0'>
                  <span className='font-mono text-muted-foreground'>{a.ts}</span>
                  <span className='font-mono'>score {a.anomaly_score.toFixed(3)}</span>
                  <SeverityBadge severity={a.severity} />
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <p className='mt-3 text-[11px] text-muted-foreground'>
        Rated flow and kW figures in this room are assumed, not measured plant specs — see config.yaml. The ranked
        Rs/kWh/tCO2 cost of fixing this specific leak is on the Action Center page, computed from a real
        baseline-vs-fault-removed simulation diff, not estimated inline here.
      </p>
    </PageShell>
  )
}
