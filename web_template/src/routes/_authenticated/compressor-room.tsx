import { createFileRoute } from '@tanstack/react-router'
import { CompressorRoom } from '@/features/compressor-room'

export const Route = createFileRoute('/_authenticated/compressor-room')({
  component: CompressorRoom,
})
