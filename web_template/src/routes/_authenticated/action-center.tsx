import { createFileRoute } from '@tanstack/react-router'
import { ActionCenter } from '@/features/action-center'

export const Route = createFileRoute('/_authenticated/action-center')({
  component: ActionCenter,
})
