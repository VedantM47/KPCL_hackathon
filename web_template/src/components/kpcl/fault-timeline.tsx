import { useMemo } from 'react'
import { cn } from '@/lib/utils'

const SEVERITY_CLASS: Record<number, string> = {
  0: 'bg-muted/40',
  1: 'bg-chart-1/25',
  2: 'bg-amber-500/45',
  3: 'bg-amber-500/75',
  4: 'bg-destructive/85',
}
const SEVERITY_LABEL = ['none', 'low', 'medium', 'high', 'critical']

type DailyRank = { asset_id: string; date: string; rank: number }

type FaultTimelineProps = {
  daily: DailyRank[]
  assetIds: string[]
  startDate: string // 'YYYY-MM-DD'
  endDate: string
}

// One strip per asset, one cell per day, coloured by that day's worst flagged
// severity — a SCADA alarm-log read, not a generic chart. Built from the
// anomaly detector's actual daily output (pre-aggregated server-side), not a
// replay of the injected fault schedule a real deployment wouldn't have.
export function FaultTimeline({ daily, assetIds, startDate, endDate }: FaultTimelineProps) {
  const days = useMemo(() => {
    const out: string[] = []
    const d = new Date(startDate)
    const end = new Date(endDate)
    while (d <= end) {
      out.push(d.toISOString().slice(0, 10))
      d.setDate(d.getDate() + 1)
    }
    return out
  }, [startDate, endDate])

  const rankByAssetDay = useMemo(() => {
    const map = new Map<string, number>()
    for (const row of daily) map.set(`${row.asset_id}|${row.date}`, row.rank)
    return map
  }, [daily])

  return (
    <div className='overflow-x-auto'>
      <div className='min-w-[720px]'>
        {assetIds.map((assetId) => (
          <div key={assetId} className='flex items-center gap-2 py-[2px]'>
            <span className='w-32 shrink-0 truncate text-right text-[11px] text-muted-foreground'>{assetId}</span>
            <div className='flex grow gap-[1px]'>
              {days.map((day) => {
                const rank = rankByAssetDay.get(`${assetId}|${day}`) ?? 0
                return (
                  <div
                    key={day}
                    title={`${assetId} — ${day}${rank ? ` — flagged (${SEVERITY_LABEL[rank]})` : ''}`}
                    className={cn('h-3 flex-1 rounded-[1px]', SEVERITY_CLASS[rank])}
                  />
                )
              })}
            </div>
          </div>
        ))}
        <div className='mt-2 flex items-center gap-3 pl-[136px] text-[10px] text-muted-foreground'>
          {SEVERITY_LABEL.map((label, rank) => (
            <span key={label} className='flex items-center gap-1'>
              <span className={cn('h-2.5 w-2.5 rounded-[1px]', SEVERITY_CLASS[rank])} /> {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
