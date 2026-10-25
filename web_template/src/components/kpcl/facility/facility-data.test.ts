import { describe, expect, it } from 'vitest'
import type { Asset, FaultWindow, LiveFrame } from '@/lib/kpcl-api'
import { buildFacility, deriveStatus, isWeekend, LAYOUT, windowActive } from './facility-data'

const asset = (asset_id: string, type: string, plant_id: string, rated_kw: number | null, role?: string): Asset => ({
  asset_id, type, plant_id, rated_kw, rated_m3_per_min: null, rated_tr: null, rated_kwp: null,
  extra_json: JSON.stringify(role ? { role } : {}), plant_name: `${plant_id} Works`, city: '', division: '',
})

const frame = (ts: string, assets: LiveFrame['assets']) => ({ ts, assets }) as unknown as LiveFrame

describe('status rules', () => {
  it('uses the meter state first, then kW against rating', () => {
    expect(deriveStatus('cnc', 9, 'cutting', 18, false, true)).toBe('running')
    expect(deriveStatus('cnc', 3, 'idle', 18, false, true)).toBe('idle')
    expect(deriveStatus('furnace_heat_treat', 0, 'off', 120, false, true)).toBe('off')
    expect(deriveStatus('compressor_centrifugal', 100, null, 160, false, true)).toBe('running')
    expect(deriveStatus('compressor_centrifugal', 20, null, 160, false, true)).toBe('idle')
    expect(deriveStatus('compressor_centrifugal', 0.2, null, 160, false, true)).toBe('off')
    expect(deriveStatus('solar_pv', 0, null, null, false, true)).toBe('off')
    expect(deriveStatus('chiller_vam', 12, null, null, false, true)).toBe('running')
  })
  it('a labelled fault overrides everything, missing data says so', () => {
    expect(deriveStatus('cnc', 9, 'cutting', 18, true, true)).toBe('fault')
    expect(deriveStatus('cnc', null, null, 18, false, false)).toBe('no-data')
  })
  it('fault windows with date-only ends cover the whole last day', () => {
    const w = { start_ts: '2025-07-10', end_ts: '2025-07-12' }
    expect(windowActive(w, '2025-07-10 00:00:00')).toBe(true)
    expect(windowActive(w, '2025-07-12 23:45:00')).toBe(true)
    expect(windowActive(w, '2025-07-13 00:00:00')).toBe(false)
    expect(windowActive(w, '2025-07-09 23:45:00')).toBe(false)
  })
  it('knows weekends', () => {
    expect(isWeekend('2025-11-01 10:00:00')).toBe(true)   // Saturday
    expect(isWeekend('2025-11-03 10:00:00')).toBe(false)  // Monday
  })
})

describe('buildFacility', () => {
  const assets = [
    asset('CMP-CENT-01', 'compressor_centrifugal', 'HADAPSAR', 160, 'lead'),
    asset('CMP-SCR-01', 'compressor_screw', 'HADAPSAR', 90, 'lag'),
    asset('CNC-GEAR-01', 'cnc', 'HADAPSAR', 18),
    asset('FURNACE-HT-01', 'furnace_heat_treat', 'HADAPSAR', 120),
    asset('PAINT-BOOTH-01', 'paint_booth', 'HADAPSAR', null),
  ]
  const faults: FaultWindow[] = [
    { asset_id: 'FURNACE-HT-01', fault_type: 'furnace_door_open', start_ts: '2025-07-10', end_ts: '2025-07-12' },
    { asset_id: 'CMP-CENT-01', fault_type: 'weekend_baseload_waste', start_ts: '2025-11-01', end_ts: '2025-12-31' },
  ]

  it('puts every Hadapsar machine in its room with live values and load %', () => {
    const f = buildFacility('HADAPSAR', assets, frame('2025-07-11 09:00:00', [
      { asset_id: 'CMP-CENT-01', kW: 80, state: null },
      { asset_id: 'FURNACE-HT-01', kW: 60, state: 'hold' },
    ]), faults)
    expect(f.rooms.map((r) => r.label)).toEqual(['Compressor Room', 'Machining Room', 'Heat Treatment Room', 'Finishing Room'])
    const cent = f.rooms[0].machines[0]
    expect([cent.assetId, cent.role, cent.status, cent.loadPct]).toEqual(['CMP-CENT-01', 'lead', 'running', 0.5])
    const furnace = f.rooms[2].machines[0]
    expect(furnace.status).toBe('fault')
    expect(furnace.faults[0].label).toBe('Furnace door left open')
    expect(f.rooms[1].machines[0].status).toBe('no-data')   // CNC not in this frame
  })

  it('weekend base-load waste lights the compressor room amber only on weekends', () => {
    const sat = buildFacility('HADAPSAR', assets, frame('2025-11-01 03:00:00', [{ asset_id: 'CMP-CENT-01', kW: 50, state: null }]), faults)
    const mon = buildFacility('HADAPSAR', assets, frame('2025-11-03 03:00:00', [{ asset_id: 'CMP-CENT-01', kW: 50, state: null }]), faults)
    expect(sat.rooms[0].amber).toBe(true)
    expect(mon.rooms[0].amber).toBe(false)
    expect(sat.rooms.slice(1).every((r) => !r.amber)).toBe(true)
  })

  it('every plant layout covers its config.yaml assets exactly once', () => {
    const placed = Object.values(LAYOUT).flatMap((rooms) => rooms.flatMap((r) => r.slots.map((s) => s.assetId)))
    expect(new Set(placed).size).toBe(placed.length)
    expect(placed.sort()).toEqual([
      'CHILLER-SCR-01', 'CHILLER-VAM-01', 'CMP-CENT-01', 'CMP-REC-01', 'CMP-SCR-01', 'CNC-GEAR-01',
      'FURNACE-HT-01', 'PAINT-BOOTH-01', 'SOLAR-SASWAD-01', 'TEST-RIG-CNG-01',
    ])
  })

  it('with no frame everything is "no data", not guessed', () => {
    const f = buildFacility('NASHIK', [], null, [])
    expect(f.ts).toBeNull()
    expect(f.rooms[0].machines.every((m) => m.status === 'no-data')).toBe(true)
  })
})
