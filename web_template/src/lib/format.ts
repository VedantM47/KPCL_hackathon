// Real-unit formatters used throughout the dashboard — never a bare round number.
export function fmtKwh(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(2)} GWh`
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)} MWh`
  return `${v.toFixed(digits)} kWh`
}

export function fmtKw(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(digits)} kW`
}

export function fmtRupees(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const abs = Math.abs(v)
  const sign = v < 0 ? '-' : ''
  if (abs >= 1_00_00_000) return `${sign}₹${(abs / 1_00_00_000).toFixed(2)} Cr`
  if (abs >= 1_00_000) return `${sign}₹${(abs / 1_00_000).toFixed(2)} L`
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}k`
  return `${sign}₹${abs.toFixed(0)}`
}

export function fmtTco2(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(1)} tCO₂e`
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function fmtBar(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(digits)} bar`
}

export function fmtSpecificPower(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(digits)} kWh/m³`
}

export function fmtKwPerTr(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(digits)} kW/TR`
}

export function fmtCop(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(digits)
}

export function fmtTemp(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(digits)}°C`
}

export function fmtDelta(v: number | null | undefined, unit: string, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}${unit}`
}

export function fmtShortDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
}

export function fmtTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}
