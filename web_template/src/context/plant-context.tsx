import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { kpclApi, type PlantInfo } from '@/lib/kpcl-api'

export const ALL_PLANTS = 'ALL'
const STORAGE_KEY = 'kpcl-plant'

type PlantContextValue = {
  plant: string // 'ALL' or a plant_id
  setPlant: (plant: string) => void
  plants: PlantInfo[]
  info: PlantInfo | undefined
  // assets owned by the selected plant (undefined while loading) — pages use this to hide
  // equipment the plant does not have instead of showing another site's machines
  assetIds: Set<string> | undefined
  hasAsset: (assetId: string) => boolean
}

const PlantContext = createContext<PlantContextValue | null>(null)

function readStored(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || ALL_PLANTS
  } catch {
    return ALL_PLANTS
  }
}

export function PlantProvider({ children }: { children: ReactNode }) {
  const [plant, setPlantState] = useState<string>(readStored)

  const { data: plants } = useQuery({
    queryKey: ['plants'],
    queryFn: () => kpclApi.plants(),
    staleTime: Infinity,
  })
  const { data: assets } = useQuery({
    queryKey: ['assets', plant],
    queryFn: () => kpclApi.assets(plant),
    staleTime: Infinity,
  })

  const setPlant = useCallback((next: string) => {
    setPlantState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // storage blocked — selection just won't persist across reloads
    }
  }, [])

  const value = useMemo<PlantContextValue>(() => {
    const assetIds = assets ? new Set(assets.map((a) => a.asset_id)) : undefined
    return {
      plant,
      setPlant,
      plants: plants ?? [],
      info: plants?.find((p) => p.plant_id === plant),
      assetIds,
      hasAsset: (id: string) => (assetIds ? assetIds.has(id) : true),
    }
  }, [plant, setPlant, plants, assets])

  return <PlantContext.Provider value={value}>{children}</PlantContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePlant() {
  const ctx = useContext(PlantContext)
  if (!ctx) throw new Error('usePlant must be used inside <PlantProvider>')
  return ctx
}
