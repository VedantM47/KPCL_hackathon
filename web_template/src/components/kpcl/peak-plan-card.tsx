import { useMemo, useState } from 'react'
import { ArrowRight, CalendarClock, Power } from 'lucide-react'
import { usePeakDays, usePeakPlan } from '@/hooks/use-kpcl'
import { fmtRupees } from '@/lib/format'
import { cn } from '@/lib/utils'
import { explainPeakPlan } from '@/lib/chart-explanations'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { TrendChart } from '@/components/kpcl/trend-chart'

type Props = {
  // fixed date (e.g. the live replay's current day); omit to show a day picker
  date?: string
  title?: string
}

// Peak-shaving schedule: forecast kVA for the day, which loads to move or idle,
// and what that is worth. Plans come from ml/peak_shaving.py via /schedule/plan.
export function PeakPlanCard({ date: fixedDate, title = 'Peak-shaving schedule' }: Props) {
  const { data: days } = usePeakDays()
  const [picked, setPicked] = useState<string | undefined>()
  const date = fixedDate ?? picked ?? days?.[0]?.date
  const { data: plan, isLoading } = usePeakPlan(date)

  const chartData = useMemo(
    () => plan?.profile.map((p) => ({ ...p, contract: plan.contract_kva })) ?? [],
    [plan]
  )

  return (
    <Card>
      <CardHeader className='flex-row flex-wrap items-center justify-between gap-2 pb-2'>
        <CardTitle className='flex items-center gap-2 text-sm font-medium'>
          <CalendarClock className='size-4 text-muted-foreground' />
          {title}
          {plan && (
            <span className='text-muted-foreground text-xs font-normal'>
              {plan.date} · {plan.source}
            </span>
          )}
        </CardTitle>
        {!fixedDate && days && (
          <Select value={date} onValueChange={setPicked}>
            <SelectTrigger size='sm' className='w-72 text-xs'>
              <SelectValue placeholder='Pick a day…' />
            </SelectTrigger>
            <SelectContent>
              {days.map((d) => (
                <SelectItem key={d.date} value={d.date}>
                  {d.date} · peak {d.peak_kva.toFixed(0)} kVA ({(d.contract_pct * 100).toFixed(0)}%)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </CardHeader>
      <CardContent>
        {isLoading || !plan ? (
          <Skeleton className='h-56 w-full' />
        ) : (
          <div className='grid gap-4 lg:grid-cols-5'>
            <div className='lg:col-span-3'>
              <TrendChart
                explain={() => explainPeakPlan(plan)}
                data={chartData}
                xKey='time'
                variant='line'
                yUnit=' kVA'
                yMin={0}
                height={200}
                series={[
                  { key: 'before', label: plan.source === 'forecast' ? 'Forecast' : 'Actual', color: 'neutral' },
                  { key: 'after', label: 'After plan', color: 'brand' },
                  { key: 'contract', label: 'Contract', color: 'destructive', dashed: true },
                ]}
              />
              <div className='mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs tabular-nums'>
                <span>
                  Peak {plan.peak_before_kva.toFixed(0)} kVA at {plan.peak_time}
                </span>
                <ArrowRight className='size-3 text-muted-foreground' />
                <span className='font-semibold'>{plan.peak_after_kva.toFixed(0)} kVA</span>
                <Badge
                  variant='outline'
                  className={cn(
                    'text-[10px]',
                    plan.breach_before && !plan.breach_after && 'border-emerald-500/50 text-emerald-600',
                    plan.breach_after && 'border-destructive/50 text-destructive'
                  )}
                >
                  {plan.breach_before
                    ? plan.breach_after
                      ? 'still above contract'
                      : 'breach avoided'
                    : plan.at_risk
                      ? 'near contract'
                      : 'within contract'}
                </Badge>
              </div>
            </div>

            <div className='lg:col-span-2'>
              <div className='grid grid-cols-2 gap-3 font-mono tabular-nums'>
                <div>
                  <p className='text-muted-foreground text-[11px] uppercase'>Demand cut</p>
                  <p className='text-lg font-semibold'>{plan.kva_reduction.toFixed(0)} kVA</p>
                  <p className='text-muted-foreground text-[11px]'>{fmtRupees(plan.demand_charge_at_stake_rs)} demand charge at stake</p>
                </div>
                <div>
                  <p className='text-muted-foreground text-[11px] uppercase'>ToD energy</p>
                  <p className='text-lg font-semibold'>{fmtRupees(plan.tod_energy_saving_rs)}</p>
                  <p className='text-muted-foreground text-[11px]'>saved this day</p>
                </div>
              </div>
              <ul className='mt-3 space-y-2'>
                {plan.actions.length === 0 && (
                  <li className='text-muted-foreground text-xs'>No schedule change worth making for this day.</li>
                )}
                {plan.actions.map((a) => (
                  <li key={`${a.type}-${a.asset_id}`} className='flex items-start gap-2 text-xs'>
                    {a.type === 'idle_shutdown' ? (
                      <Power className='mt-0.5 size-3.5 shrink-0 text-muted-foreground' />
                    ) : (
                      <ArrowRight className='mt-0.5 size-3.5 shrink-0 text-muted-foreground' />
                    )}
                    <div>
                      <p>{a.message}</p>
                      <p className='text-muted-foreground font-mono text-[10px]'>
                        {a.kva_reduction > 0 && `−${a.kva_reduction.toFixed(0)} kVA · `}
                        {fmtRupees(a.tod_energy_saving_rs)} ToD
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
        {plan && <p className='text-muted-foreground mt-3 text-[11px]'>{plan.notes}</p>}
      </CardContent>
    </Card>
  )
}
