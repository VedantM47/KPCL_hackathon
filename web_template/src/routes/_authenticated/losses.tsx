import { createFileRoute } from '@tanstack/react-router'
import { LossTracker } from '@/features/losses'

export const Route = createFileRoute('/_authenticated/losses')({
  component: LossTracker,
})
