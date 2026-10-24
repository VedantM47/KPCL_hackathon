import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fmtDateTime, fmtTime } from '@/lib/format'

type Point = { ts: string; pressure_bar: number; pressure_bar_min: number; pressure_bar_max: number }

type PressureSawtoothChartProps = {
  data: Point[]
  lowerBar: number
  upperBar: number
  height?: number
}

// The compressor's load/unload cycling happens faster than our 15-min storage
// resolution, so a literal point-to-point line would hide it. We still have
// each interval's min/max pressure though — plotting that as a band (the
// envelope the sawtooth swung through that interval) with the mean on top
// honestly shows the cycling amplitude without fabricating a fake waveform.
export function PressureSawtoothChart({ data, lowerBar, upperBar, height = 200 }: PressureSawtoothChartProps) {
  const pad = 0.25
  const chartData = data.map((d) => ({ ...d, band: [d.pressure_bar_min, d.pressure_bar_max] as [number, number] }))

  return (
    <ResponsiveContainer width='100%' height={height}>
      <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray='3 3' stroke='var(--border)' vertical={false} />
        <ReferenceArea y1={lowerBar} y2={upperBar} fill='var(--chart-2)' fillOpacity={0.08} />
        <XAxis
          dataKey='ts'
          tickFormatter={fmtDateTime}
          tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
          tickLine={false}
          axisLine={{ stroke: 'var(--border)' }}
          minTickGap={56}
        />
        <YAxis
          domain={[lowerBar - pad, upperBar + pad]}
          tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
          tickLine={false}
          axisLine={false}
          width={64}
          unit=' bar'
          tickFormatter={(v: number) => v.toFixed(2)}
          allowDecimals
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'var(--popover)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            fontSize: 12,
          }}
          labelFormatter={(v) => fmtTime(v as string)}
          formatter={(value, name) => {
            if (name === 'band' && Array.isArray(value)) {
              return [`${Number(value[0]).toFixed(3)} – ${Number(value[1]).toFixed(3)} bar`, 'Range this interval']
            }
            return [`${Number(value).toFixed(3)} bar`, 'Mean']
          }}
        />
        <Area
          type='linear'
          dataKey='band'
          stroke='none'
          fill='var(--chart-1)'
          fillOpacity={0.18}
          isAnimationActive={false}
        />
        <Line
          type='linear'
          dataKey='pressure_bar'
          stroke='var(--chart-1)'
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
