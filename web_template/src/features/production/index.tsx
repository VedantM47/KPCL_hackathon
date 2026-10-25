import { useMemo } from 'react'
import { usePlant } from '@/context/plant-context'
import { useAssetSeries, useProductionDaily } from '@/hooks/use-kpcl'
import { fmtKwh } from '@/lib/format'
import { explainFurnaceFuel, explainPaintAir, explainShifts, explainUnitsVsEnergy } from '@/lib/chart-explanations'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { PageShell } from '@/components/kpcl/page-header'
import { TrendChart } from '@/components/kpcl/trend-chart'

const FURNACE_WINDOW = { from: '2025-01-05', to: '2025-01-12' }

export function Production() {
  const { data: daily, isLoading } = useProductionDaily()
  const { hasAsset } = usePlant()
  const hasFurnace = hasAsset('FURNACE-HT-01')
  const hasPaint = hasAsset('PAINT-BOOTH-01')
  const { data: furnace, isLoading: furnaceLoading } = useAssetSeries('FURNACE-HT-01', { ...FURNACE_WINDOW, res: '15m' }, hasFurnace)
  const { data: paint, isLoading: paintLoading } = useAssetSeries('PAINT-BOOTH-01', { ...FURNACE_WINDOW, res: '15m' }, hasPaint)

  const stats = useMemo(() => {
    if (!daily || daily.length === 0) return null
    const totalUnits = daily.reduce((s, d) => s + d.total_units, 0)
    const totalKwh = daily.reduce((s, d) => s + d.kWh, 0)
    const totalA = daily.reduce((s, d) => s + d.A, 0)
    const totalB = daily.reduce((s, d) => s + d.B, 0)
    const avgPerUnit = totalUnits > 0 ? totalKwh / totalUnits : null
    return { totalUnits, totalKwh, totalA, totalB, avgPerUnit }
  }, [daily])

  const monthly = useMemo(() => {
    if (!daily) return []
    const byMonth = new Map<string, { month: string; A: number; B: number; units: number; kWh: number }>()
    for (const d of daily) {
      const month = d.date.slice(0, 7)
      const entry = byMonth.get(month) ?? { month, A: 0, B: 0, units: 0, kWh: 0 }
      entry.A += d.A
      entry.B += d.B
      entry.units += d.total_units
      entry.kWh += d.kWh
      byMonth.set(month, entry)
    }
    return Array.from(byMonth.values()).sort((a, b) => a.month.localeCompare(b.month))
  }, [daily])

  return (
    <PageShell title='Production' description='Gearbox · compressor package · refrigeration package — full year'>
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
        <KpiCard
          label='Energy per Unit'
          value={isLoading || !stats || stats.avgPerUnit === null ? '—' : `${stats.avgPerUnit.toFixed(2)} kWh/unit`}
          sub={stats && stats.totalUnits === 0 ? 'no production records for this plant' : 'plant kWh ÷ total units produced'}
        />
        <KpiCard
          label='Units Produced'
          value={isLoading || !stats ? '—' : stats.totalUnits.toFixed(0)}
          sub='gearbox + compressor + refrigeration packages'
        />
        <KpiCard
          label='Shift A Share'
          value={isLoading || !stats || stats.totalA + stats.totalB === 0 ? '—' : `${((stats.totalA / (stats.totalA + stats.totalB)) * 100).toFixed(1)}%`}
          sub={stats ? `${stats.totalA.toFixed(0)} units A · ${stats.totalB.toFixed(0)} units B` : undefined}
        />
        <KpiCard
          label='Total Plant Energy'
          value={isLoading || !stats ? '—' : fmtKwh(stats.totalKwh)}
          sub='same window, for reference'
        />
      </div>

      <div className='mt-4 grid gap-3 lg:grid-cols-2'>
        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Shift A vs B — units produced per month</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? <Skeleton className='h-52 w-full' /> : (
              <TrendChart explain={() => explainShifts(monthly as never[])} data={monthly} xKey='month' variant='line' series={[
                { key: 'A', label: 'Shift A', color: 'brand' },
                { key: 'B', label: 'Shift B', color: 'neutral' },
              ]} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Monthly units vs plant energy</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? <Skeleton className='h-52 w-full' /> : (
              <TrendChart explain={() => explainUnitsVsEnergy(monthly as never[])} data={monthly} xKey='month' variant='line' series={[
                { key: 'units', label: 'Units', color: 'brand' },
              ]} />
            )}
          </CardContent>
        </Card>
      </div>

      {(hasFurnace || hasPaint) && (
      <div className='mt-3 grid gap-3 lg:grid-cols-2'>
        {hasFurnace && (
        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Heat-treatment: fuel per batch ({FURNACE_WINDOW.from} → {FURNACE_WINDOW.to})</CardTitle>
          </CardHeader>
          <CardContent>
            {furnaceLoading ? <Skeleton className='h-40 w-full' /> : (
              <TrendChart
                explain={() => explainFurnaceFuel((furnace ?? []) as never[])}
                data={furnace as never[]}
                xKey='ts'
                height={160}
                yUnit=' kg'
                series={[{ key: 'fuel_kg', label: 'LPG fuel rate', color: 'warning' }]}
                xTickFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
              />
            )}
          </CardContent>
        </Card>

        )}

        {hasPaint && (
        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Paint booth air draw ({FURNACE_WINDOW.from} → {FURNACE_WINDOW.to})</CardTitle>
          </CardHeader>
          <CardContent>
            {paintLoading ? <Skeleton className='h-40 w-full' /> : (
              <TrendChart
                explain={() => explainPaintAir((paint ?? []) as never[])}
                data={paint as never[]}
                xKey='ts'
                height={160}
                yUnit=' m³/min'
                series={[{ key: 'air_draw_m3min', label: 'Air draw', color: 'brand' }]}
                xTickFormatter={(v) => new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
              />
            )}
          </CardContent>
        </Card>
        )}
      </div>
      )}
    </PageShell>
  )
}
