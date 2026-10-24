import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

// compact axis numbers (1.5k, 12k) so wide rupee/kWh series don't overflow the axis gutter
function fmtAxis(v: number) {
  const a = Math.abs(v)
  if (a >= 1_000_000) return `${+(v / 1_000_000).toFixed(1)}M`
  if (a >= 10_000) return `${Math.round(v / 1000)}k`
  if (a >= 1_000) return `${+(v / 1000).toFixed(1)}k`
  return Number.isInteger(v) ? String(v) : String(+v.toFixed(2))
}

type Series = {
  key: string
  label: string
  color?: 'brand' | 'neutral' | 'warning' | 'destructive'
  dashed?: boolean
}

const COLOR_VAR: Record<NonNullable<Series['color']>, string> = {
  brand: 'var(--chart-1)',
  neutral: 'var(--chart-2)',
  warning: 'var(--chart-3)',
  destructive: 'var(--chart-4)',
}

type TrendChartProps = {
  data: Array<Record<string, number | string | null>>
  xKey: string
  series: Series[]
  height?: number
  variant?: 'area' | 'line'
  xTickFormatter?: (v: string) => string
  yUnit?: string
  yMin?: number
}

// Shared trend chart for 15-min/hourly/daily series — tabular tooltips, one
// brand color for the primary series, neutral grey for comparisons, amber/red
// reserved for threshold or fault series only.
export function TrendChart({ data, xKey, series, height = 220, variant = 'area', xTickFormatter, yUnit, yMin }: TrendChartProps) {
  const Chart = variant === 'area' ? AreaChart : LineChart
  return (
    <ResponsiveContainer width='100%' height={height}>
      <Chart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' vertical={false} />
        <XAxis
          dataKey={xKey}
          tickFormatter={xTickFormatter}
          tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
          tickLine={false}
          axisLine={{ stroke: 'var(--border)' }}
          minTickGap={24}
        />
        <YAxis
          tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
          tickLine={false}
          axisLine={false}
          width={yUnit ? 68 : 52}
          unit={yUnit}
          domain={yMin !== undefined ? [yMin, 'auto'] : undefined}
          allowDataOverflow={yMin !== undefined}
          tickFormatter={fmtAxis}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'var(--popover)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            fontSize: 12,
          }}
          labelStyle={{ color: 'var(--muted-foreground)', marginBottom: 2 }}
          formatter={(value, name) => [typeof value === 'number' ? value.toFixed(2) : String(value ?? '—'), String(name)]}
        />
        {series.map((s) => {
          const color = COLOR_VAR[s.color ?? 'brand']
          if (variant === 'line') {
            return (
              <Line
                key={s.key}
                type='monotone'
                dataKey={s.key}
                name={s.label}
                stroke={color}
                strokeWidth={1.75}
                strokeDasharray={s.dashed ? '4 3' : undefined}
                dot={false}
                isAnimationActive={false}
              />
            )
          }
          return (
            <Area
              key={s.key}
              type='monotone'
              dataKey={s.key}
              name={s.label}
              stroke={color}
              strokeWidth={1.75}
              fill={color}
              fillOpacity={0.12}
              isAnimationActive={false}
            />
          )
        })}
      </Chart>
    </ResponsiveContainer>
  )
}
