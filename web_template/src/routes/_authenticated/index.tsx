import { createFileRoute } from '@tanstack/react-router'
import { PlantOverview } from '@/features/plant'

export const Route = createFileRoute('/_authenticated/')({
  component: PlantOverview,
})
