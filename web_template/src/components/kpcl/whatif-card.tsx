import { useMemo, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'
import { useWhatIfGrid } from '@/hooks/use-kpcl'
import { fmtRupees, fmtTco2 } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ChartExplainer } from '@/components/kpcl/chart-explainer'
import { explainWhatIf } from '@/lib/chart-explanations'

const NONE = '__baseline'

// What-if simulator: pick a setting per lever; each option is a precomputed
// full-year simulation diff (ml/whatif.py), so numbers are real, not formulas.
export function WhatIfCard() {
  const { data, isLoading, isError } = useWhatIfGrid()
  const [choice, setChoice] = useState<Record<string, string>>({})

  const totals = useMemo(() => {
    const t = { kWh: 0, rs: 0, tco2: 0, scope1: 0, scope2: 0, peak: 0, n: 0 }
    for (const lever of data?.levers ?? []) {
      const opt = lever.options.find((o) => o.option_label === choice[lever.lever])
      if (!opt) continue
      t.kWh += opt.kWh_saved
      t.rs += opt.rs_saved
      t.tco2 += opt.tco2_saved
      t.scope1 += opt.scope1_saved
      t.scope2 += opt.scope2_saved
      t.peak += opt.peak_kva_reduction
      t.n += 1
    }
    return t
  }, [data, choice])

  return (
    <Card>
      <CardHeader className='pb-2'>
        <CardTitle className='flex items-center gap-2 text-sm font-medium'>
          <SlidersHorizontal className='size-4 text-muted-foreground' />
          What-if simulator
          <span className='text-muted-foreground text-xs font-normal'>annual impact vs baseline policy</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isError ? (
          <p className='text-muted-foreground text-xs'>
            What-if grid not generated yet — run <code>python -m ml.whatif</code>.
          </p>
        ) : isLoading || !data ? (
          <Skeleton className='h-40 w-full' />
        ) : (
          <ChartExplainer explain={() => explainWhatIf(data, choice, totals)}>
            <div className='grid gap-4 lg:grid-cols-5'>
              <div className='grid gap-3 sm:grid-cols-2 lg:col-span-3'>
                {data.levers.map((lever) => {
                  const sel = lever.options.find((o) => o.option_label === choice[lever.lever])
                  return (
                    <div key={lever.lever}>
                      <p className='text-muted-foreground mb-1 text-[11px] font-medium uppercase'>{lever.label}</p>
                      <Select
                        value={choice[lever.lever] ?? NONE}
                        onValueChange={(v) => setChoice((c) => ({ ...c, [lever.lever]: v === NONE ? '' : v }))}
                      >
                        <SelectTrigger size='sm' className='w-full text-xs'>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NONE}>Baseline (no change)</SelectItem>
                          {lever.options.map((o) => (
                            <SelectItem key={o.option_label} value={o.option_label}>
                              {o.option_label} · {fmtRupees(o.rs_saved)}/yr
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {sel && (
                        <p className={cn('mt-1 font-mono text-[10px]', sel.rs_saved < 0 ? 'text-destructive' : 'text-muted-foreground')}>
                          {sel.kWh_saved.toFixed(0)} kWh · S1 {sel.scope1_saved.toFixed(1)} / S2 {sel.scope2_saved.toFixed(1)} tCO₂e
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>

              <div className='rounded-md border p-3 font-mono tabular-nums lg:col-span-2'>
                <p className='text-muted-foreground text-[11px] uppercase'>
                  Combined ({totals.n} lever{totals.n === 1 ? '' : 's'}) · approximate
                </p>
                <p className={cn('mt-1 text-2xl font-semibold', totals.rs < 0 && 'text-destructive')}>{fmtRupees(totals.rs)}/yr</p>
                <div className='mt-2 grid grid-cols-3 gap-2 text-xs'>
                  <div>
                    <p className='text-muted-foreground text-[10px] uppercase'>Energy</p>
                    <p className={cn(totals.kWh < 0 && 'text-destructive')}>{(totals.kWh / 1000).toFixed(1)} MWh</p>
                  </div>
                  <div>
                    <p className='text-muted-foreground text-[10px] uppercase'>Emissions</p>
                    <p className={cn(totals.tco2 < 0 && 'text-destructive')}>{fmtTco2(totals.tco2)}</p>
                  </div>
                  <div>
                    <p className='text-muted-foreground text-[10px] uppercase'>Peak</p>
                    <p>{totals.peak.toFixed(0)} kVA</p>
                  </div>
                </div>
                <p className='text-muted-foreground mt-3 font-sans text-[10px] leading-snug'>
                  {data.note} Baseline: {(data.baseline.kWh / 1000).toFixed(0)} MWh, {fmtRupees(data.baseline.cost_rs)}.
                </p>
              </div>
            </div>
          </ChartExplainer>
        )}
      </CardContent>
    </Card>
  )
}
