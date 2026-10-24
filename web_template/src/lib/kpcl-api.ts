// Thin client for the FastAPI backend (api/main.py). Base URL is configurable
// via VITE_API_BASE_URL so the dev server and a future deployed build can
// point at different hosts; defaults to the local uvicorn dev server.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

async function getJson<T>(path: string, params?: Record<string, string | undefined>): Promise<T> {
  const url = new URL(path, BASE_URL)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) url.searchParams.set(k, v)
    }
  }
  const res = await fetch(url.toString())
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  return res.json() as Promise<T>
}

export type PlantInfo = { plant_id: string; name: string; city: string; division: string; contract_kva: number }

export type Kpis = {
  plant: string | null
  contract_kva: number
  peak_demand_kva: number
  from: string | null
  to: string | null
  total_energy_kwh: number
  grid_energy_kwh: number
  cost_rs: number
  peak_demand_kw: number
  scope1_tco2: number
  scope2_tco2: number
  solar_avoided_tco2: number
  energy_intensity_kwh_per_unit: number | null
  solar_share: number | null
  data_label: string
}

export type Asset = {
  asset_id: string
  type: string
  plant_id: string
  rated_kw: number | null
  rated_m3_per_min: number | null
  rated_tr: number | null
  rated_kwp: number | null
  extra_json: string
  plant_name: string
  city: string
  division: string
}

export type SeriesPoint = Record<string, string | number | boolean | null>

export type ForecastResponse = {
  metrics: {
    mape_pct: number
    wape_pct: number
    naive_climatology_wape_pct: number
    contract_kva: number
    n_breaches_in_test_period: number
  }
  last_24h: Array<{
    ts: string
    kW: number
    pred_kw: number
    pred_kva: number
    breach_flag: boolean
  }>
}

export type Anomaly = {
  ts: string
  asset_id: string
  anomaly_score: number
  severity: 'low' | 'medium' | 'high' | 'critical'
  model_flag: boolean
  rule_flag: boolean
}

export type Recommendation = {
  plant_id: string
  action: string
  type: 'policy' | 'fault_fix'
  kWh_saved: number
  rs_saved: number
  tco2_saved: number
  rank: number
}

export type ScenarioCompare = {
  baseline: { kWh: number; cost_rs: number; tco2: number }
  optimized: { kWh: number; cost_rs: number; tco2: number }
  savings: { kWh: number; cost_rs: number; tco2: number }
}

export type PlantCompare = {
  plant_id: string
  plant_name: string
  city: string
  division: string
  kwh_total: number
  cost_rs: number
  scope1_tco2: number
  scope2_tco2: number
  peak_kva: number
  contract_kva: number
  units: number | null
  kwh_per_unit: number | null
}

export type ProductionDay = {
  date: string
  total_units: number
  kWh: number
  A: number
  B: number
  energy_per_unit_kwh: number | null
}

export type CarbonMonth = {
  month: string
  scope1_tco2: number
  scope2_tco2: number
  solar_avoided_tco2: number
  total_tco2: number
}
export type FuelByMonth = { month: string } & Record<string, number>
export type CarbonMonthly = { monthly: CarbonMonth[]; fuel_by_type: FuelByMonth[] }

export type LiveAlert = {
  asset_id: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  source: string
  message: string
}

export type LiveFrame = {
  idx: number
  plant_id: string
  ts: string
  plant: { kW: number | null; kVA: number | null; pf: number | null; contract_kva: number; contract_pct: number }
  today: { cost_rs: number | null; scope1_tco2: number | null; scope2_tco2: number | null }
  solar_kw: number | null
  ambient_c: number | null
  compressor: {
    pressure_bar: number | null
    specific_power: number | null
    leak_m3min: number | null
    leak_kw: number | null
    leak_rs_per_hr: number | null
    avoidable_leak_rs_per_hr: number | null
  }
  chiller_kw_per_tr: number | null
  assets: Array<{ asset_id: string; kW: number | null; state: string | null }>
  alerts: LiveAlert[]
  paused: boolean
  speed: number
  data_label: string
}

export type FaultWindow = { asset_id: string; fault_type: string; start_ts: string; end_ts: string }

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(new URL(path, BASE_URL).toString(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export type PeakDay = { date: string; peak_kva: number; source: string; contract_pct: number }

export type PeakAction = {
  type: 'shift' | 'idle_shutdown'
  asset_id: string
  asset_label: string
  from_time: string | null
  to_time: string | null
  shift_hours: number
  kva_reduction: number
  tod_energy_saving_rs: number
  message: string
}

export type PeakPlan = {
  date: string
  plant_id: string
  source: string
  contract_kva: number
  peak_before_kva: number
  peak_after_kva: number
  peak_time: string
  kva_reduction: number
  breach_before: boolean
  breach_after: boolean
  at_risk: boolean
  demand_charge_at_stake_rs: number
  tod_energy_saving_rs: number
  actions: PeakAction[]
  profile: Array<{ time: string; before: number; after: number }>
  notes: string
}

export type LeakAsset = {
  asset_id: string
  avoidable_kwh: number
  avoidable_rs: number
  total_leak_kwh: number
  total_leak_rs: number
  leak_floor_m3min: number
  peak_leak_m3min: number
  avoidable_tco2: number
}

export type ExcessAsset = {
  asset_id: string
  flagged_intervals: number
  excess_kwh: number
  excess_rs: number
  excess_tco2: number
}

export type LossesSummary = {
  leaks_by_asset: LeakAsset[]
  anomaly_excess_by_asset: ExcessAsset[]
  totals: {
    avoidable_leak_rs: number
    avoidable_leak_kwh: number
    avoidable_leak_tco2: number
    anomaly_excess_rs: number
    anomaly_excess_kwh: number
  }
  method: string
}

export type LeakDaily = {
  date: string
  asset_id: string
  avoidable_kwh: number
  avoidable_rs: number
  total_leak_kwh: number
  total_leak_rs: number
  avoidable_kgco2: number
}

export type WhatIfOption = {
  option_label: string
  option_value: string
  kWh_saved: number
  rs_saved: number
  tco2_saved: number
  scope1_saved: number
  scope2_saved: number
  peak_kva_reduction: number
}
export type WhatIfGrid = {
  baseline: { kWh: number; cost_rs: number; scope1: number; scope2: number; peak_kva: number }
  levers: Array<{ lever: string; label: string; options: WhatIfOption[] }>
  note: string
}

// `plant` is a plant_id or 'ALL' (whole company, the default). Omitted params fall back to ALL on the server.
const pl = (plant?: string) => (plant && plant !== 'ALL' ? plant : undefined)

export const kpclApi = {
  plants: () => getJson<PlantInfo[]>('/plants'),

  scheduleDays: (plant?: string, topN = 40) =>
    getJson<PeakDay[]>('/schedule/days', { top_n: String(topN), plant: pl(plant) }),

  schedulePlan: (date: string, plant?: string) => getJson<PeakPlan>('/schedule/plan', { date, plant: pl(plant) }),

  lossesSummary: (plant?: string) => getJson<LossesSummary>('/losses/summary', { plant: pl(plant) }),

  leaksDaily: (plant?: string) => getJson<LeakDaily[]>('/losses/leaks/daily', { plant: pl(plant) }),

  whatIfGrid: (plant?: string) => getJson<WhatIfGrid>('/whatif/grid', { plant: pl(plant) }),

  liveSnapshot: (plant?: string, n = 96) => getJson<LiveFrame[]>('/live/snapshot', { n: String(n), plant: pl(plant) }),

  liveFaultWindows: (plant?: string) => getJson<FaultWindow[]>('/live/fault-windows', { plant: pl(plant) }),

  liveControl: (body: { speed?: number; paused?: boolean; jump_to?: string }) =>
    postJson<{ idx: number; ts: string; speed: number; paused: boolean }>('/live/control', body),

  liveStreamUrl: (plant?: string) => {
    const url = new URL('/live/stream', BASE_URL)
    if (pl(plant)) url.searchParams.set('plant', pl(plant) as string)
    return url.toString()
  },

  productionDaily: (plant?: string) => getJson<ProductionDay[]>('/production/daily', { plant: pl(plant) }),

  carbonMonthly: (plant?: string) => getJson<CarbonMonthly>('/carbon/monthly', { plant: pl(plant) }),

  kpis: (params?: { plant?: string; from?: string; to?: string }) =>
    getJson<Kpis>('/kpis', { plant: pl(params?.plant), from: params?.from, to: params?.to }),

  plantsCompare: () => getJson<PlantCompare[]>('/plants/compare'),

  assets: (plant?: string) => getJson<Asset[]>('/assets', { plant: pl(plant) }),

  assetSeries: (assetId: string, params?: { from?: string; to?: string; res?: '15m' | '1h' | '1d' }) =>
    getJson<SeriesPoint[]>(`/assets/${assetId}/series`, {
      from: params?.from,
      to: params?.to,
      res: params?.res ?? '1h',
    }),

  forecastDemand: (plant?: string) => getJson<ForecastResponse>('/forecast/demand', { plant: pl(plant) }),

  anomalies: (params?: { from?: string; to?: string; asset_id?: string; plant?: string }) =>
    getJson<Anomaly[]>('/anomalies', {
      from: params?.from, to: params?.to, asset_id: params?.asset_id, plant: pl(params?.plant),
    }),

  anomaliesDaily: (plant?: string) =>
    getJson<Array<{ asset_id: string; date: string; rank: number }>>('/anomalies/daily', { plant: pl(plant) }),

  recommendations: (plant?: string) => getJson<Recommendation[]>('/recommendations', { plant: pl(plant) }),

  scenarioCompare: (plant?: string) => getJson<ScenarioCompare>('/scenario/compare', { plant: pl(plant) }),

  carbonReportUrl: (format: 'csv' | 'pdf', plant?: string) =>
    new URL(`/carbon/report?format=${format}${pl(plant) ? `&plant=${pl(plant)}` : ''}`, BASE_URL).toString(),

  plantReportUrl: (plant?: string) =>
    new URL(`/reports/plant${pl(plant) ? `?plant=${pl(plant)}` : ''}`, BASE_URL).toString(),
}
