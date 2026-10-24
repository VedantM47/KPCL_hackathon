import { createFileRoute } from '@tanstack/react-router'
import { Carbon } from '@/features/carbon'

export const Route = createFileRoute('/_authenticated/carbon')({
  component: Carbon,
})
