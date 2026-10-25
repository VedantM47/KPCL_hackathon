import { lazy, Suspense, useMemo, useState } from 'react'
import { Box, MousePointerClick } from 'lucide-react'
import { usePlant } from '@/context/plant-context'
import { useFacilityState } from '@/hooks/use-kpcl'
import { fmtKw } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { buildFacility, type FacilityData, type FacilityMachine, type FacilityPlantId, FACILITY_PLANTS, type MachineStatus } from './facility-data'

// three.js + react-three-fiber only load when this panel renders
const FacilityScene = lazy(() => import('./facility-scene'))

const STATUS_TEXT: Record<MachineStatus, string> = {
  running: 'Running',
  idle: 'Idle',
  off: 'Off',
  fault: 'Fault',
  'no-data': 'No live data',
}
const STATUS_BADGE: Record<MachineStatus, string> = {
  running: 'border-emerald-500/40 text-emerald-700 dark:text-emerald-400',
  idle: 'border-amber-500/50 text-amber-700 dark:text-amber-400',
  off: 'text-muted-foreground',
  fault: 'border-destructive/50 text-destructive',
  'no-data': 'text-muted-foreground',
}
const DOT: Record<MachineStatus, string> = {
  running: 'bg-emerald-500',
  idle: 'bg-amber-500',
  off: 'bg-slate-500',
  fault: 'bg-red-500 animate-pulse',
  'no-data': 'bg-slate-400',
}
const KIND_LABEL: Record<string, string> = {
  compressor_centrifugal: 'Centrifugal compressor',
  compressor_screw: 'Screw compressor',
  compressor_reciprocating: 'Reciprocating compressor',
  compressor_test_rig: 'CNG test rig',
  chiller_vam: 'VAM chiller (gas-fired)',
  chiller_screw_electric: 'Electric screw chiller',
  cnc: 'CNC machine',
  furnace_heat_treat: 'Heat-treatment furnace',
  paint_booth: 'Paint booth',
  solar_pv: 'Solar PV array',
}

function defaultPlant(global: string): FacilityPlantId {
  return (FACILITY_PLANTS.find((p) => p.id === global)?.id ?? 'HADAPSAR') as FacilityPlantId
}

type Props = {
  /** Supply data directly (e.g. from another source); otherwise the panel reads the live replay. */
  data?: FacilityData
  className?: string
}

/** 3D view of a plant's rooms and machines, coloured by live state; click a machine for details. */
export function FacilityView3D({ data: override, className }: Props) {
  const { plant: globalPlant } = usePlant()
  const [plant, setPlant] = useState<FacilityPlantId>(() => override?.plantId ?? defaultPlant(globalPlant))
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [zoom, setZoom] = useState(false)
  const live = useFacilityState(override ? override.plantId : plant)

  const data = useMemo(
    () => override ?? buildFacility(plant, live.assets, live.frame, live.faultWindows),
    [override, plant, live.assets, live.frame, live.faultWindows]
  )
  const machines = data.rooms.flatMap((r) => r.machines)
  const selected = machines.find((m) => m.assetId === selectedId) ?? null
  const faults = machines.filter((m) => m.status === 'fault')

  return (
    <Card className={cn('gap-3', className)}>
      <CardHeader className='flex flex-row flex-wrap items-center justify-between gap-2 pb-0'>
        <CardTitle className='flex items-center gap-2 text-sm font-medium'>
          <Box className='size-4 text-muted-foreground' />
          Facility View
        </CardTitle>
        <Tabs
          value={plant}
          onValueChange={(v) => {
            setPlant(v as FacilityPlantId)
            setSelectedId(null)
          }}
        >
          <TabsList className='h-8'>
            {FACILITY_PLANTS.map((p) => (
              <TabsTrigger key={p.id} value={p.id} className='px-2.5 text-xs' disabled={!!override && override.plantId !== p.id}>
                {p.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent className='space-y-2'>
        <div
          className='relative h-72 w-full overflow-hidden rounded-md border bg-muted/40 sm:h-80'
          onPointerDown={() => setZoom(true)}
          onPointerLeave={() => setZoom(false)}
        >
          {live.isError && !override ? (
            <p className='text-muted-foreground p-4 text-xs'>Cannot reach the plant server for live machine states.</p>
          ) : live.isLoading && !override ? (
            <Skeleton className='h-full w-full' />
          ) : (
            <Suspense fallback={<Skeleton className='h-full w-full' />}>
              <FacilityScene data={data} selectedId={selectedId} onSelect={setSelectedId} zoomEnabled={zoom} />
            </Suspense>
          )}
          <div className='pointer-events-none absolute bottom-1.5 left-1.5 flex items-center gap-1 rounded bg-background/80 px-1.5 py-0.5 text-[10px] text-muted-foreground'>
            <MousePointerClick className='size-3' />
            {zoom ? 'Drag to orbit · scroll to zoom' : 'Click a machine for details · click here to enable zoom'}
          </div>
        </div>

        <div className='flex flex-wrap items-center justify-between gap-2 text-[11px]'>
          <div className='flex flex-wrap gap-3 text-muted-foreground'>
            {(['running', 'idle', 'off', 'fault'] as const).map((s) => (
              <span key={s} className='flex items-center gap-1'>
                <span className={cn('inline-block size-2 rounded-full', DOT[s])} />
                {STATUS_TEXT[s]}
              </span>
            ))}
          </div>
          <span className='text-muted-foreground tabular-nums'>{data.ts ? `Replay ${data.ts}` : 'No live data'}</span>
        </div>
        {faults.length > 0 && (
          <p className='text-destructive text-[11px]'>
            Fault: {faults.map((m) => `${m.assetId} (${m.faults.map((f) => f.label).join(', ')})`).join(' · ')}
          </p>
        )}
      </CardContent>

      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelectedId(null)}>
        <SheetContent className='w-full sm:max-w-sm'>
          {selected && <MachineDetails m={selected} plantName={data.plantName} ts={data.ts} />}
        </SheetContent>
      </Sheet>
    </Card>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className='flex items-baseline justify-between gap-4 border-b border-border/60 py-2 text-sm last:border-0'>
      <span className='text-muted-foreground'>{label}</span>
      <span className='text-right font-mono tabular-nums'>{children}</span>
    </div>
  )
}

function MachineDetails({ m, plantName, ts }: { m: FacilityMachine; plantName: string; ts: string | null }) {
  const solar = m.kind === 'solar_pv'
  return (
    <>
      <SheetHeader>
        <SheetTitle className='font-mono'>{m.assetId}</SheetTitle>
        <SheetDescription>
          {KIND_LABEL[m.kind] ?? m.kind}
          {m.role ? ` · ${m.role}` : ''} · {plantName}
        </SheetDescription>
      </SheetHeader>
      <div className='px-4'>
        <Row label='Status'>
          <Badge variant='outline' className={cn('font-sans', STATUS_BADGE[m.status])}>
            <span className={cn('mr-1 inline-block size-1.5 rounded-full', DOT[m.status])} />
            {STATUS_TEXT[m.status]}
          </Badge>
        </Row>
        <Row label='Plant'>{plantName}</Row>
        <Row label='Rating'>{m.rating}</Row>
        <Row label={solar ? 'Generating' : 'Power draw'}>{fmtKw(m.kW)}</Row>
        <Row label='Load'>{m.loadPct !== null ? `${(m.loadPct * 100).toFixed(0)}% of rated` : '—'}</Row>
        <Row label='Meter state'>{m.state ?? '—'}</Row>
        {m.faults.length > 0 && (
          <div className='mt-3 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm'>
            <p className='text-destructive font-medium'>Active fault</p>
            {m.faults.map((f) => (
              <p key={f.type} className='mt-1 text-xs'>
                {f.label} <span className='text-muted-foreground'>({f.start} → {f.end})</span>
              </p>
            ))}
          </div>
        )}
        <p className='text-muted-foreground mt-4 text-[11px]'>
          {ts ? `Replay time ${ts}. ` : ''}Values come from the benchmark-calibrated simulation, not real meters. Fault states are the
          simulation&apos;s labelled fault windows.
        </p>
      </div>
    </>
  )
}
