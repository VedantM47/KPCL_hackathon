import { createFileRoute } from '@tanstack/react-router'
import { Refrigeration } from '@/features/refrigeration'

export const Route = createFileRoute('/_authenticated/refrigeration')({
  component: Refrigeration,
})
