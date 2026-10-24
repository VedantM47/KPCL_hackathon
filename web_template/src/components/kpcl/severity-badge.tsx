import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const STYLES: Record<string, string> = {
  low: 'border-chart-1/40 text-chart-1',
  medium: 'border-amber-500/40 text-amber-600 dark:text-amber-400',
  high: 'border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  critical: 'border-destructive/50 bg-destructive/10 text-destructive',
}

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge variant='outline' className={cn('text-[10px] capitalize', STYLES[severity] ?? '')}>
      {severity}
    </Badge>
  )
}
