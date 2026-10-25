import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { usePlant } from '@/context/plant-context'
import { kpclApi, type LiveAlert, type LiveFrame } from '@/lib/kpcl-api'

const LIVE_BUFFER = 288 // 3 simulated days of 15-min frames
const ALERT_BUFFER = 40

export type LiveAlertEntry = LiveAlert & { ts: string; key: string }

// Subscribes to the server-side replay clock (SSE) for the selected plant. Backfills
// from /live/snapshot so charts are populated immediately, then appends one frame per
// tick. Switching plant resets the buffers and reconnects. If the stream drops,
// EventSource retries on its own; `connected` reflects that.
export function useLiveStream() {
  const { plant } = usePlant()
  const [frames, setFrames] = useState<LiveFrame[]>([])
  const [alerts, setAlerts] = useState<LiveAlertEntry[]>([])
  const [connected, setConnected] = useState(false)
  const lastIdx = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false
    lastIdx.current = null
    setFrames([])
    setAlerts([])
    kpclApi
      .liveSnapshot(plant, 96)
      .then((snap) => {
        if (cancelled || snap.length === 0) return
        lastIdx.current = snap[snap.length - 1].idx
        setFrames((prev) => (prev.length ? prev : snap))
      })
      .catch(() => {})

    const es = new EventSource(kpclApi.liveStreamUrl(plant))
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    es.onmessage = (ev) => {
      const frame = JSON.parse(ev.data) as LiveFrame
      if (frame.demo) {
        // simulated alert: show it in the ticker without disturbing the rolling chart buffer
        setAlerts((prev) =>
          [...frame.alerts.map((a, i) => ({ ...a, ts: frame.ts, key: `demo-${Date.now()}-${i}` })), ...prev].slice(0, ALERT_BUFFER)
        )
        return
      }
      // a jump (or year wrap) breaks continuity — restart the rolling window
      const continuous = lastIdx.current !== null && frame.idx > lastIdx.current && frame.idx - lastIdx.current <= 4
      lastIdx.current = frame.idx
      setFrames((prev) => (continuous ? [...prev, frame].slice(-LIVE_BUFFER) : [frame]))
      if (frame.alerts.length) {
        setAlerts((prev) =>
          [
            ...frame.alerts.map((a, i) => ({ ...a, ts: frame.ts, key: `${frame.idx}-${i}` })),
            ...prev,
          ].slice(0, ALERT_BUFFER)
        )
      }
    }
    return () => {
      cancelled = true
      es.close()
    }
  }, [plant])

  return { frames, latest: frames[frames.length - 1], alerts, connected }
}

export function useFaultWindows() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['live-fault-windows', plant],
    queryFn: () => kpclApi.liveFaultWindows(plant),
    staleTime: Infinity,
  })
}

export function useKpis(params?: { from?: string; to?: string }) {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['kpis', plant, params],
    queryFn: () => kpclApi.kpis({ plant, ...params }),
  })
}

export function useCarbonMonthly() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['carbon-monthly', plant],
    queryFn: () => kpclApi.carbonMonthly(plant),
  })
}

export function useProductionDaily() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['production-daily', plant],
    queryFn: () => kpclApi.productionDaily(plant),
  })
}

export function usePlantsCompare() {
  return useQuery({
    queryKey: ['plants-compare'],
    queryFn: () => kpclApi.plantsCompare(),
  })
}

export function useAssets() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['assets', plant],
    queryFn: () => kpclApi.assets(plant),
    staleTime: Infinity, // asset master rarely changes within a session
  })
}

export function useAssetSeries(
  assetId: string,
  params?: { from?: string; to?: string; res?: '15m' | '1h' | '1d' },
  enabled = true
) {
  return useQuery({
    queryKey: ['asset-series', assetId, params],
    queryFn: () => kpclApi.assetSeries(assetId, params),
    enabled: !!assetId && enabled,
  })
}

export function useForecastDemand() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['forecast-demand', plant],
    queryFn: () => kpclApi.forecastDemand(plant),
    // "tomorrow" follows the live replay's simulated day
    refetchInterval: 30_000,
  })
}

export function useAnomalies(params?: { from?: string; to?: string; asset_id?: string }) {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['anomalies', plant, params],
    queryFn: () => kpclApi.anomalies({ plant, ...params }),
  })
}

export function useAnomaliesDaily() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['anomalies-daily', plant],
    queryFn: () => kpclApi.anomaliesDaily(plant),
  })
}

export function useRecommendations() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['recommendations', plant],
    queryFn: () => kpclApi.recommendations(plant),
  })
}

export function useScenarioCompare() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['scenario-compare', plant],
    queryFn: () => kpclApi.scenarioCompare(plant),
  })
}

export function usePeakDays() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['schedule-days', plant],
    queryFn: () => kpclApi.scheduleDays(plant),
    staleTime: Infinity,
  })
}

export function usePeakPlan(date: string | undefined) {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['schedule-plan', plant, date],
    queryFn: () => kpclApi.schedulePlan(date as string, plant),
    enabled: !!date,
    staleTime: Infinity,
  })
}

export function useLossesSummary() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['losses-summary', plant],
    queryFn: () => kpclApi.lossesSummary(plant),
  })
}

export function useLeaksDaily() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['leaks-daily', plant],
    queryFn: () => kpclApi.leaksDaily(plant),
  })
}

export function useWhatIfGrid() {
  const { plant } = usePlant()
  return useQuery({
    queryKey: ['whatif-grid', plant],
    queryFn: () => kpclApi.whatIfGrid(plant),
    staleTime: Infinity,
    retry: false,
  })
}
