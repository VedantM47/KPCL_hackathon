import { createFileRoute } from '@tanstack/react-router'
import { Production } from '@/features/production'

export const Route = createFileRoute('/_authenticated/production')({
  component: Production,
})
