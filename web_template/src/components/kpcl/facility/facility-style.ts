// Shared constants for the facility models and scene (kept out of the component files so fast
// refresh keeps working).
import type { MachineStatus } from './facility-data'

export const STATUS_COLOR: Record<MachineStatus, string> = {
  running: '#22c55e',
  idle: '#eab308',
  off: '#64748b',
  fault: '#ef4444',
  'no-data': '#94a3b8',
}

/** footprint radius and height (m) per model, for the status ring, beacon and label */
export const FOOTPRINT: Record<string, { r: number; h: number }> = {
  compressor_centrifugal: { r: 1.0, h: 1.3 },
  compressor_screw: { r: 0.75, h: 1.0 },
  compressor_reciprocating: { r: 0.85, h: 0.95 },
  compressor_test_rig: { r: 0.95, h: 1.1 },
  chiller_vam: { r: 1.0, h: 1.0 },
  chiller_screw_electric: { r: 0.9, h: 1.05 },
  cnc: { r: 0.8, h: 1.05 },
  furnace_heat_treat: { r: 0.8, h: 2.1 },
  paint_booth: { r: 1.15, h: 1.7 },
  solar_pv: { r: 2.75, h: 0.55 },
}

export function machineHeight(kind: string): number {
  return (FOOTPRINT[kind] ?? { h: 1 }).h
}
