// Turns the dashboard's existing data (asset master, latest live frame, labelled fault windows) into
// the rooms and machines the 3D facility view draws. Pure functions, so the status rules are testable
// without WebGL. All data is the benchmark-calibrated simulation, not real plant telemetry.
import type { Asset, FaultWindow, LiveFrame } from '@/lib/kpcl-api'

export type FacilityPlantId = 'HADAPSAR' | 'SASWAD' | 'NASHIK'
export const FACILITY_PLANTS: { id: FacilityPlantId; label: string }[] = [
  { id: 'HADAPSAR', label: 'Hadapsar' },
  { id: 'SASWAD', label: 'Saswad' },
  { id: 'NASHIK', label: 'Nashik' },
]

export type MachineStatus = 'running' | 'idle' | 'off' | 'fault' | 'no-data'

/** Model to draw, from dim_asset.type (config.yaml assets[].type). */
export type MachineKind =
  | 'compressor_centrifugal'
  | 'compressor_screw'
  | 'compressor_reciprocating'
  | 'compressor_test_rig'
  | 'chiller_vam'
  | 'chiller_screw_electric'
  | 'cnc'
  | 'furnace_heat_treat'
  | 'paint_booth'
  | 'solar_pv'

export type FacilityMachine = {
  assetId: string
  kind: MachineKind | string
  plantId: string
  role: string | null          // lead / lag / standalone, from extra_json
  rating: string               // "160 kW · 27 m³/min"
  ratedKw: number | null
  kW: number | null
  state: string | null         // raw state from the meter (cutting, idle, ramp, ...)
  status: MachineStatus
  loadPct: number | null       // kW / rated kW
  faults: { type: string; label: string; start: string; end: string }[]
  /** room-relative position (metres) */
  x: number
  z: number
}

export type FacilityRoom = {
  id: string
  label: string
  outdoor: boolean
  x: number
  z: number
  w: number
  d: number
  /** dim amber ambient light: weekend base-load waste in progress */
  amber: boolean
  machines: FacilityMachine[]
}

export type FacilityData = {
  plantId: FacilityPlantId
  plantName: string
  ts: string | null
  rooms: FacilityRoom[]
}

export const FAULT_LABEL: Record<string, string> = {
  leak_growth: 'Compressed-air leak growing',
  setpoint_drift: 'Pressure setpoint drift',
  condenser_fouling: 'Condenser fouling',
  refrigerant_leak: 'Refrigerant leak',
  cnc_idle_drift: 'CNC idle-power drift',
  furnace_door_open: 'Furnace door left open',
  paint_fan_overrun: 'Paint-booth fan overrun',
  weekend_baseload_waste: 'Weekend base-load waste',
}

type RoomSpec = Omit<FacilityRoom, 'machines' | 'amber'> & { slots: { assetId: string; x: number; z: number }[] }

/** Floor plan per plant (presentation only — which machine sits in which room comes from here). */
export const LAYOUT: Record<FacilityPlantId, RoomSpec[]> = {
  HADAPSAR: [
    { id: 'compressor', label: 'Compressor Room', outdoor: false, x: -2.5, z: -2, w: 4.6, d: 3.6,
      slots: [{ assetId: 'CMP-CENT-01', x: -1.1, z: 0 }, { assetId: 'CMP-SCR-01', x: 1.2, z: 0 }] },
    { id: 'machining', label: 'Machining Room', outdoor: false, x: 2.5, z: -2, w: 4.6, d: 3.6,
      slots: [{ assetId: 'CNC-GEAR-01', x: 0, z: 0 }] },
    { id: 'heat', label: 'Heat Treatment Room', outdoor: false, x: -2.5, z: 2, w: 4.6, d: 3.6,
      slots: [{ assetId: 'FURNACE-HT-01', x: 0, z: 0 }] },
    { id: 'finishing', label: 'Finishing Room', outdoor: false, x: 2.5, z: 2, w: 4.6, d: 3.6,
      slots: [{ assetId: 'PAINT-BOOTH-01', x: 0, z: 0 }] },
  ],
  SASWAD: [
    { id: 'hvac', label: 'Chiller / HVAC Room', outdoor: false, x: -2.9, z: 0, w: 5, d: 4,
      slots: [{ assetId: 'CHILLER-VAM-01', x: -1.2, z: 0 }, { assetId: 'CHILLER-SCR-01', x: 1.3, z: 0 }] },
    { id: 'solar', label: 'Solar Yard', outdoor: true, x: 3.2, z: 0, w: 6, d: 5,
      slots: [{ assetId: 'SOLAR-SASWAD-01', x: 0, z: 0 }] },
  ],
  NASHIK: [
    { id: 'test', label: 'Compressor / Test Room', outdoor: false, x: 0, z: 0, w: 6.2, d: 4,
      slots: [{ assetId: 'CMP-REC-01', x: -1.5, z: 0 }, { assetId: 'TEST-RIG-CNG-01', x: 1.6, z: 0 }] },
  ],
}

const RUNNING_STATES = new Set(['cutting', 'ramp', 'hold', 'running', 'load', 'loaded'])
const IDLE_STATES = new Set(['idle', 'cooldown', 'unloaded'])

/** Fault windows store whole days ("2025-04-15"), so an end date covers that entire day. */
export function windowActive(w: Pick<FaultWindow, 'start_ts' | 'end_ts'>, ts: string): boolean {
  const end = w.end_ts.length <= 10 ? `${w.end_ts} 23:59:59` : w.end_ts
  return ts >= w.start_ts && ts <= end
}

export function isWeekend(ts: string): boolean {
  const d = new Date(ts.replace(' ', 'T'))
  const day = d.getDay()
  return day === 0 || day === 6
}

/** running / idle / off from the meter, fault if a labelled fault window is active. */
export function deriveStatus(kind: string, kW: number | null, state: string | null, ratedKw: number | null, faulted: boolean, hasData: boolean): MachineStatus {
  if (!hasData) return 'no-data'
  if (faulted) return 'fault'
  if (state && RUNNING_STATES.has(state)) return 'running'
  if (state && IDLE_STATES.has(state)) return 'idle'
  if (state === 'off') return 'off'
  const kw = kW ?? 0
  if (kind === 'solar_pv') return kw > 1 ? 'running' : 'off'   // no sun = not generating
  if (ratedKw && ratedKw > 0) return kw >= 0.25 * ratedKw ? 'running' : kw > 0.5 ? 'idle' : 'off'
  return kw > 3 ? 'running' : kw > 0.3 ? 'idle' : 'off'
}

function ratingOf(a: Asset): string {
  const parts: string[] = []
  if (a.rated_kw) parts.push(`${a.rated_kw} kW`)
  if (a.rated_m3_per_min) parts.push(`${a.rated_m3_per_min} m³/min`)
  if (a.rated_tr) parts.push(`${a.rated_tr} TR`)
  if (a.rated_kwp) parts.push(`${a.rated_kwp} kWp`)
  return parts.join(' · ') || '—'
}

function roleOf(a: Asset): string | null {
  try {
    const extra = JSON.parse(a.extra_json || '{}') as { role?: string }
    return extra.role ?? null
  } catch {
    return null
  }
}

export function buildFacility(
  plantId: FacilityPlantId,
  assets: Asset[] | undefined,
  frame: LiveFrame | null | undefined,
  faultWindows: FaultWindow[] | undefined
): FacilityData {
  const byId = new Map((assets ?? []).map((a) => [a.asset_id, a]))
  const live = new Map((frame?.assets ?? []).map((a) => [a.asset_id, a]))
  const ts = frame?.ts ?? null
  const active = (faultWindows ?? []).filter((w) => ts !== null && windowActive(w, ts))

  const rooms = LAYOUT[plantId].map((spec) => {
    const machines: FacilityMachine[] = spec.slots.map((slot) => {
      const a = byId.get(slot.assetId)
      const l = live.get(slot.assetId)
      const faults = active
        .filter((w) => w.asset_id === slot.assetId)
        .map((w) => ({ type: w.fault_type, label: FAULT_LABEL[w.fault_type] ?? w.fault_type, start: w.start_ts, end: w.end_ts }))
      const ratedKw = a?.rated_kw ?? null
      const kW = l?.kW ?? null
      const kind = a?.type ?? 'unknown'
      return {
        assetId: slot.assetId,
        kind,
        plantId,
        role: a ? roleOf(a) : null,
        rating: a ? ratingOf(a) : '—',
        ratedKw,
        kW,
        state: l?.state ?? null,
        status: deriveStatus(kind, kW, l?.state ?? null, ratedKw, faults.length > 0, !!l),
        loadPct: ratedKw && kW !== null ? Math.max(0, kW / ratedKw) : null,
        faults,
        x: slot.x,
        z: slot.z,
      }
    })
    const amber =
      ts !== null && isWeekend(ts) && machines.some((m) => m.faults.some((f) => f.type === 'weekend_baseload_waste'))
    return { id: spec.id, label: spec.label, outdoor: spec.outdoor, x: spec.x, z: spec.z, w: spec.w, d: spec.d, amber, machines }
  })

  const any = (assets ?? []).find((a) => a.plant_id === plantId)
  return {
    plantId,
    plantName: any?.plant_name ?? FACILITY_PLANTS.find((p) => p.id === plantId)!.label,
    ts,
    rooms,
  }
}

export function hasFault(m: FacilityMachine, type: string): boolean {
  return m.faults.some((f) => f.type === type)
}
