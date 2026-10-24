import { type ReactNode } from 'react'
import { Area, AreaChart, ResponsiveContainer } from 'recharts'
import { cn } from '@/lib/utils'
import { Card, CardContent } from '@/components/ui/card'

type KpiCardProps = {
  label: string
  value: string
  sub?: string
  trend?: number[] // optional sparkline series
  trendColor?: 'default' | 'warning' | 'destructive'
  delta?: { value: string; direction: 'up' | 'down' | 'flat'; good?: boolean }
  icon?: ReactNode
}

// Dense, control-room-style KPI tile: tight padding, tabular numerals, a
// small inline sparkline instead of a decorative illustration.
export function KpiCard({ label, value, sub, trend, trendColor = 'default', delta, icon }: KpiCardProps) {
  const sparkColor =
    trendColor === 'warning' ? 'var(--chart-3)' : trendColor === 'destructive' ? 'var(--chart-4)' : 'var(--chart-1)'

  return (
    <Card className='gap-0 py-3'>
      <CardContent className='flex items-start justify-between gap-3 px-4'>
        <div className='min-w-0 flex-1'>
          <p className='text-muted-foreground text-[11px] font-medium tracking-wide uppercase'>{label}</p>
          <p className='mt-1 font-mono text-[1.4rem] leading-none font-semibold whitespace-nowrap tabular-nums'>{value}</p>
          <div className='mt-1 flex items-center gap-1.5'>
            {delta && (
              <span
                className={cn(
                  'text-[11px] font-medium tabular-nums',
                  delta.good === undefined
                    ? 'text-muted-foreground'
                    : delta.good
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-destructive'
                )}
              >
                {delta.direction === 'up' ? '▲' : delta.direction === 'down' ? '▼' : '—'} {delta.value}
              </span>
            )}
            {sub && <span className='text-muted-foreground text-[11px]'>{sub}</span>}
          </div>
        </div>
        {icon && <div className='text-muted-foreground mt-0.5 shrink-0'>{icon}</div>}
        {trend && trend.length > 1 && (
          <div className='h-10 w-20 shrink-0'>
            <ResponsiveContainer width='100%' height='100%'>
              <AreaChart data={trend.map((y, i) => ({ x: i, y }))}>
                <defs>
                  <linearGradient id={`spark-${label.replace(/\s+/g, '')}`} x1='0' y1='0' x2='0' y2='1'>
                    <stop offset='0%' stopColor={sparkColor} stopOpacity={0.35} />
                    <stop offset='100%' stopColor={sparkColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type='monotone'
                  dataKey='y'
                  stroke={sparkColor}
                  strokeWidth={1.5}
                  fill={`url(#spark-${label.replace(/\s+/g, '')})`}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
