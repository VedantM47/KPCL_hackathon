import { useMemo } from 'react'
import { Activity, Pause, Play, Sun, Zap } from 'lucide-react'
import { kpclApi } from '@/lib/kpcl-api'
import { usePlant } from '@/context/plant-context'
import { useFaultWindows, useLiveStream } from '@/hooks/use-kpcl'
import { fmtBar, fmtDateTime, fmtKw, fmtPct, fmtRupees, fmtTemp, fmtTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { KpiCard } from '@/components/kpcl/kpi-card'
import { PageShell } from '@/components/kpcl/page-header'
import { PeakPlanCard } from '@/components/kpcl/peak-plan-card'
import { SeverityBadge } from '@/components/kpcl/severity-badge'
import { TrendChart } from '@/components/kpcl/trend-chart'

const SPEEDS = [1, 4, 16]

const STATE_STYLE: Record<string, string> = {
  off: 'bg-muted text-muted-foreground',
  idle: 'bg-muted text-muted-foreground',
  cooldown: 'bg-muted text-muted-foreground',
  ramp: 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
}

export function LiveMonitor() {
  const { plant, info } = usePlant()
  const { frames, latest, alerts, connected } = useLiveStream()
  const { data: faultWindows } = useFaultWindows()

  const chartData = useMemo(
    () =>
      frames.map((f) => ({
        ts: f.ts,
        kVA: f.plant.kVA,
        contract: f.plant.contract_kva,
        solar: f.solar_kw,
      })),
    [frames]
  )

  const paused = latest?.paused ?? false
  const speed = latest?.speed ?? 1
  const contractPct = latest?.plant.contract_pct

  return (
    <PageShell
      title={plant === 'ALL' ? 'Live Monitor' : `${info?.name ?? plant} — Live Monitor`}
      description='Simulated live replay of the benchmark-calibrated dataset — not real telemetry'
      actions={
        <>
          <Badge variant='outline' className={cn('gap-1.5', connected ? 'border-emerald-500/50' : 'border-destructive/50')}>
            <span className={cn('size-1.5 rounded-full', connected && !paused ? 'animate-pulse bg-emerald-500' : 'bg-muted-foreground')} />
            {!connected ? 'DISCONNECTED' : paused ? 'PAUSED' : 'LIVE REPLAY'}
          </Badge>
          <span className='font-mono text-xs tabular-nums'>{latest ? fmtDateTime(latest.ts) : '—'}</span>
          <Button size='icon' variant='outline' className='size-8' onClick={() => kpclApi.liveControl({ paused: !paused })}>
            {paused ? <Play className='size-4' /> : <Pause className='size-4' />}
          </Button>
          {SPEEDS.map((s) => (
            <Button
              key={s}
              size='sm'
              variant={speed === s ? 'default' : 'outline'}
              className='h-8 px-2 font-mono text-xs'
              onClick={() => kpclApi.liveControl({ speed: s })}
            >
              {s}×
            </Button>
          ))}
          <Select onValueChange={(v) => kpclApi.liveControl({ jump_to: v })}>
            <SelectTrigger size='sm' className='w-44 text-xs'>
              <SelectValue placeholder='Jump to fault…' />
            </SelectTrigger>
            <SelectContent>
              {faultWindows?.map((w) => (
                <SelectItem key={`${w.asset_id}-${w.fault_type}`} value={w.start_ts}>
                  {w.fault_type.replace(/_/g, ' ')} · {w.asset_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </>
      }
    >
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-5'>
        <KpiCard
          label='Plant Load'
          value={fmtKw(latest?.plant.kW)}
          sub={latest ? `${latest.plant.kVA?.toFixed(0)} kVA · pf ${latest.plant.pf?.toFixed(2)}` : undefined}
          trend={frames.slice(-48).map((f) => f.plant.kW ?? 0)}
          icon={<Zap className='size-4' />}
        />
        <KpiCard
          label='Contract Demand'
          value={fmtPct(contractPct, 0)}
          sub={latest ? `of ${latest.plant.contract_kva} kVA` : undefined}
          trendColor={contractPct && contractPct > 0.85 ? 'warning' : 'default'}
        />
        <KpiCard
          label='Cost Today'
          value={fmtRupees(latest?.today.cost_rs)}
          sub={latest ? `${((latest.today.scope1_tco2 ?? 0) + (latest.today.scope2_tco2 ?? 0)).toFixed(2)} tCO₂e today` : undefined}
        />
        <KpiCard
          label='Solar'
          value={latest && latest.solar_kw === null ? 'n/a' : fmtKw(latest?.solar_kw)}
          sub={latest ? `ambient ${fmtTemp(latest.ambient_c)}` : undefined}
          icon={<Sun className='size-4' />}
        />
        <KpiCard
          label='Compressor Header'
          value={latest && latest.compressor.pressure_bar === null ? 'n/a' : fmtBar(latest?.compressor.pressure_bar)}
          sub={latest ? `leak burning ${fmtRupees(latest.compressor.leak_rs_per_hr)}/h · ${fmtRupees(latest.compressor.avoidable_leak_rs_per_hr)} avoidable` : undefined}
          icon={<Activity className='size-4' />}
        />
      </div>

      <div className='mt-4 grid gap-3 lg:grid-cols-5'>
        <Card className='lg:col-span-3'>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Plant apparent power vs contract demand</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendChart
              data={chartData}
              xKey='ts'
              variant='line'
              yUnit=' kVA'
              yMin={0}
              xTickFormatter={fmtTime}
              series={[
                { key: 'kVA', label: 'Plant kVA', color: 'brand' },
                { key: 'contract', label: 'Contract', color: 'destructive', dashed: true },
              ]}
            />
          </CardContent>
        </Card>

        <Card className='lg:col-span-2'>
          <CardHeader className='pb-2'>
            <CardTitle className='text-sm font-medium'>Live alerts</CardTitle>
          </CardHeader>
          <CardContent>
            {alerts.length === 0 ? (
              <p className='text-muted-foreground text-xs'>No alerts yet — try “Jump to fault”.</p>
            ) : (
              <ul className='max-h-60 space-y-2 overflow-y-auto pe-1'>
                {alerts.map((a) => (
                  <li key={a.key} className='flex items-start gap-2 text-xs'>
                    <SeverityBadge severity={a.severity} />
                    <div className='min-w-0'>
                      <p className='truncate'>{a.message}</p>
                      <p className='text-muted-foreground font-mono text-[10px]'>{fmtDateTime(a.ts)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className='mt-4'>
        <PeakPlanCard date={latest?.ts.slice(0, 10)} title="Today's peak-shaving schedule" />
      </div>

      <Card className='mt-4'>
        <CardHeader className='pb-2'>
          <CardTitle className='text-sm font-medium'>Assets</CardTitle>
        </CardHeader>
        <CardContent>
          <div className='grid gap-2 sm:grid-cols-2 lg:grid-cols-5'>
            {latest?.assets.map((a) => (
              <div key={a.asset_id} className='rounded-md border px-3 py-2'>
                <p className='truncate font-mono text-[11px]'>{a.asset_id}</p>
                <p className='mt-0.5 font-mono text-base font-semibold tabular-nums'>{fmtKw(a.kW)}</p>
                {a.state && (
                  <span className={cn('rounded px-1.5 py-0.5 text-[10px] capitalize', STATE_STYLE[a.state] ?? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400')}>
                    {a.state}
                  </span>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <p className='text-muted-foreground mt-4 text-[11px]'>
        {latest?.data_label ?? 'simulated live replay'} — the server replays the pre-generated year at accelerated speed
        (1 tick = 15 simulated minutes). All tabs share one clock.
      </p>
    </PageShell>
  )
}
