import { createFileRoute } from '@tanstack/react-router'
import { LiveMonitor } from '@/features/live'

export const Route = createFileRoute('/_authenticated/live')({
  component: LiveMonitor,
})
