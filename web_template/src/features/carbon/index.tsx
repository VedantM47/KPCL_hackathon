import { Download, FileText } from 'lucide-react'
import { usePlant } from '@/context/plant-context'
import { useCarbonMonthly } from '@/hooks/use-kpcl'
import { kpclApi } from '@/lib/kpcl-api'
import { fmtTco2 } from '@/lib/format'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { PageShell } from '@/components/kpcl/page-header'
import { TrendChart } from '@/components/kpcl/trend-chart'

export function Carbon() {
  const { plant, info } = usePlant()
  const { data, isLoading } = useCarbonMonthly()
  const monthly = data?.monthly ?? []
  const fuelByType = data?.fuel_by_type ?? []

  const totals = monthly.reduce(
    (acc, m) => ({
      scope1: acc.scope1 + m.scope1_tco2,
      scope2: acc.scope2 + m.scope2_tco2,
      solarAvoided: acc.solarAvoided + m.solar_avoided_tco2,
    }),
    { scope1: 0, scope2: 0, solarAvoided: 0 }
  )

  return (
    <PageShell
      title={plant === 'ALL' ? 'Carbon & ESG' : `${info?.name ?? plant} — Carbon & ESG`}
      description='Benchmark-calibrated simulation — emission factors are config placeholders, VERIFY before external use'
      actions={
        <>
          <Button variant='outline' size='sm' asChild>
            <a href={kpclApi.carbonReportUrl('csv', plant)} download>
              <Download className='mr-1 size-3.5' /> CSV
            </a>
          </Button>
          <Button variant='outline' size='sm' asChild>
            <a href={kpclApi.carbonReportUrl('pdf', plant)} download>
              <FileText className='mr-1 size-3.5' /> BRSR PDF
            </a>
          </Button>
          <Button variant='outline' size='sm' asChild>
            <a href={kpclApi.plantReportUrl(plant)} download>
              <FileText className='mr-1 size-3.5' /> Plant report
            </a>
          </Button>
        </>
      }
    >
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
        <KpiCard label='Scope 1' value={isLoading ? '—' : fmtTco2(totals.scope1)} sub='fuel + refrigerant, annual' />
        <KpiCard label='Scope 2' value={isLoading ? '—' : fmtTco2(totals.scope2)} sub='grid electricity, annual' />
        <KpiCard
          label='Total Emissions'
          value={isLoading ? '—' : fmtTco2(totals.scope1 + totals.scope2)}
          sub='Scope 1 + Scope 2'
          trendColor='warning'
        />
        <KpiCard
          label='Solar Avoided'
          value={isLoading ? '—' : fmtTco2(totals.solarAvoided)}
          sub='counterfactual grid-equivalent'
        />
      </div>

      <div className='mt-4 grid gap-3 lg:grid-cols-2'>
        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Monthly Scope 1 vs Scope 2</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? <Skeleton className='h-52 w-full' /> : (
              <TrendChart
                data={monthly as never[]}
                xKey='month'
                yUnit=' tCO₂e'
                series={[
                  { key: 'scope1_tco2', label: 'Scope 1', color: 'warning' },
                  { key: 'scope2_tco2', label: 'Scope 2', color: 'brand' },
                ]}
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Scope 1 fuel mix (LPG kg · gas kg · diesel L)</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? <Skeleton className='h-52 w-full' /> : (
              <TrendChart
                data={fuelByType as never[]}
                xKey='month'
                series={[
                  { key: 'LPG', label: 'LPG (furnace, kg)', color: 'warning' },
                  { key: 'gas', label: 'Gas (VAM, kg)', color: 'brand' },
                  { key: 'diesel_litre', label: 'Diesel (DG, L)', color: 'destructive' },
                ]}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <Card className='mt-3'>
        <CardHeader className='pb-2'>
          <CardTitle className='text-sm font-medium'>Monthly avoided emissions from solar</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? <Skeleton className='h-40 w-full' /> : (
            <TrendChart
              data={monthly as never[]}
              xKey='month'
              height={160}
              yUnit=' tCO₂e'
              series={[{ key: 'solar_avoided_tco2', label: 'Solar avoided', color: 'brand' }]}
            />
          )}
        </CardContent>
      </Card>
    </PageShell>
  )
}
