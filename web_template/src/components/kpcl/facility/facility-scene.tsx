import { type RefObject, useEffect, useMemo, useRef, useState } from 'react'
import { OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Vector3 } from 'three'
import { cn } from '@/lib/utils'
import type { FacilityData, FacilityMachine, FacilityRoom } from './facility-data'
import { MachineModel } from './facility-models'
import { machineHeight, STATUS_COLOR } from './facility-style'

// The WebGL part of the facility view. Loaded lazily by facility-view-3d.tsx so three.js stays out of
// the main dashboard bundle.
//
// Labels are ordinary DOM elements laid over the canvas and moved every frame to their projected 3D
// anchor. (drei's <Html> mounts a separate React root per label, and unmounting those while React is
// rendering logs errors under React 19.) Being normal DOM, they also use the dashboard theme tokens.

export type FacilitySceneProps = {
  data: FacilityData
  selectedId: string | null
  onSelect: (assetId: string | null) => void
  /** scroll-to-zoom only after the user clicks into the canvas, so the page still scrolls normally */
  zoomEnabled: boolean
}

type Anchor = { id: string; pos: [number, number, number] }

const INDOOR_FLOOR = '#c3ccd6'
const OUTDOOR_FLOOR = '#9fbf8f'
const CURB = '#6b7785'

function bounds(rooms: FacilityRoom[]) {
  let maxX = 0
  let maxZ = 0
  for (const r of rooms) {
    maxX = Math.max(maxX, Math.abs(r.x) + r.w / 2)
    maxZ = Math.max(maxZ, Math.abs(r.z) + r.d / 2)
  }
  return { maxX, maxZ }
}

/** Re-frames the camera when the plant changes. */
function CameraRig({ plantId, radius }: { plantId: string; radius: number }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    // direction (0.55, 0.85, 0.95) has length ~1.39, so this starts ~2.7 radii away: the whole plant fits
    // the panel's landscape aspect with a little margin
    const d = radius * 1.95
    camera.position.set(d * 0.55, d * 0.85, d * 0.95)
    const c = controls as unknown as { target: Vector3; update: () => void } | null
    if (c) {
      c.target.set(0, 0, 0)
      c.update()
    } else {
      camera.lookAt(0, 0, 0)
    }
  }, [plantId, radius, camera, controls])
  return null
}

/** Moves each DOM label to the screen position of its 3D anchor, every frame. */
function LabelProjector({ anchors, els }: { anchors: Anchor[]; els: RefObject<Map<string, HTMLDivElement>> }) {
  const v = useMemo(() => new Vector3(), [])
  useFrame(({ camera, size }) => {
    for (const a of anchors) {
      const el = els.current.get(a.id)
      if (!el) continue
      v.set(a.pos[0], a.pos[1], a.pos[2]).project(camera)
      const behind = v.z > 1
      const x = (v.x * 0.5 + 0.5) * size.width
      const y = (-v.y * 0.5 + 0.5) * size.height
      el.style.transform = `translate(-50%, -50%) translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`
      el.style.visibility = behind ? 'hidden' : ''
    }
  })
  return null
}

function Room({ room }: { room: FacilityRoom }) {
  const curb = 0.07
  const h = 0.12
  return (
    <group position={[room.x, 0, room.z]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.002, 0]} receiveShadow>
        <planeGeometry args={[room.w, room.d]} />
        <meshStandardMaterial color={room.outdoor ? OUTDOOR_FLOOR : INDOOR_FLOOR} roughness={0.95} />
      </mesh>
      {!room.outdoor &&
        ([
          [0, -room.d / 2, room.w, curb],
          [0, room.d / 2, room.w, curb],
          [-room.w / 2, 0, curb, room.d],
          [room.w / 2, 0, curb, room.d],
        ] as const).map(([x, z, w, d], i) => (
          <mesh key={i} position={[x, h / 2, z]} castShadow>
            <boxGeometry args={[w, h, d]} />
            <meshStandardMaterial color={CURB} />
          </mesh>
        ))}
      {room.amber && (
        <>
          <pointLight position={[0, 2.2, 0]} color='#f59e0b' intensity={6} distance={6} />
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.004, 0]}>
            <planeGeometry args={[room.w, room.d]} />
            <meshBasicMaterial color='#f59e0b' transparent opacity={0.16} />
          </mesh>
        </>
      )}
    </group>
  )
}

function Machine({ m, room, selected, onSelect, onHover }: {
  m: FacilityMachine
  room: FacilityRoom
  selected: boolean
  onSelect: (id: string) => void
  onHover: (id: string | null) => void
}) {
  const [hover, setHover] = useState(false)
  return (
    <group
      position={[room.x + m.x, 0, room.z + m.z]}
      onClick={(e) => {
        e.stopPropagation()
        onSelect(m.assetId)
      }}
      onPointerOver={(e) => {
        e.stopPropagation()
        setHover(true)
        onHover(m.assetId)
      }}
      onPointerOut={() => {
        setHover(false)
        onHover(null)
      }}
    >
      <MachineModel m={m} active={selected || hover} />
    </group>
  )
}

export default function FacilityScene({ data, selectedId, onSelect, zoomEnabled }: FacilitySceneProps) {
  const { maxX, maxZ } = useMemo(() => bounds(data.rooms), [data.rooms])
  const radius = Math.max(maxX, maxZ, 3)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const labelEls = useRef(new Map<string, HTMLDivElement>())

  useEffect(() => {
    document.body.style.cursor = hoverId ? 'pointer' : ''
    return () => {
      document.body.style.cursor = ''
    }
  }, [hoverId])

  const anchors = useMemo<Anchor[]>(
    () => [
      ...data.rooms.map((r) => ({ id: `room:${r.id}`, pos: [r.x, 0.05, r.z + r.d / 2 - 0.3] as [number, number, number] })),
      ...data.rooms.flatMap((r) =>
        r.machines.map((m) => ({ id: `m:${m.assetId}`, pos: [r.x + m.x, machineHeight(m.kind) + 0.45, r.z + m.z] as [number, number, number] }))
      ),
    ],
    [data.rooms]
  )
  const setEl = (id: string) => (el: HTMLDivElement | null) => {
    if (el) labelEls.current.set(id, el)
    else labelEls.current.delete(id)
  }

  return (
    <div className='relative h-full w-full'>
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ fov: 40, near: 0.1, far: 200, position: [radius, radius * 1.2, radius * 1.4] }}
        gl={{ antialias: true, alpha: true }}
        onPointerMissed={() => onSelect(null)}
        className='touch-none'
      >
        <hemisphereLight args={['#ffffff', '#5b6470', 0.9]} />
        <directionalLight
          position={[6, 10, 5]}
          intensity={1.6}
          castShadow
          shadow-mapSize-width={1024}
          shadow-mapSize-height={1024}
          shadow-camera-left={-12}
          shadow-camera-right={12}
          shadow-camera-top={12}
          shadow-camera-bottom={-12}
        />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]} receiveShadow>
          <planeGeometry args={[maxX * 2 + 1.5, maxZ * 2 + 1.5]} />
          <meshStandardMaterial color='#7d8792' roughness={1} />
        </mesh>
        {data.rooms.map((room) => (
          <group key={room.id}>
            <Room room={room} />
            {room.machines.map((m) => (
              <Machine
                key={m.assetId}
                m={m}
                room={room}
                selected={selectedId === m.assetId}
                onSelect={onSelect}
                onHover={setHoverId}
              />
            ))}
          </group>
        ))}
        <OrbitControls
          makeDefault
          enablePan={false}
          enableZoom={zoomEnabled}
          minDistance={radius * 0.8}
          maxDistance={radius * 4}
          maxPolarAngle={Math.PI / 2.2}
        />
        <CameraRig plantId={data.plantId} radius={radius} />
        <LabelProjector anchors={anchors} els={labelEls} />
      </Canvas>

      <div className='pointer-events-none absolute inset-0 overflow-hidden'>
        {data.rooms.map((r) => (
          <div
            key={r.id}
            ref={setEl(`room:${r.id}`)}
            className='bg-background/85 text-foreground border-border absolute top-0 left-0 rounded border px-1.5 py-0.5 text-[10px] font-medium whitespace-nowrap shadow-xs'
          >
            {r.label}
            {r.amber && <span className='ml-1 text-amber-600 dark:text-amber-400'>· weekend waste</span>}
          </div>
        ))}
        {data.rooms.flatMap((r) =>
          r.machines.map((m) => (
            <div
              key={m.assetId}
              ref={setEl(`m:${m.assetId}`)}
              className={cn(
                'bg-popover text-popover-foreground border-border absolute top-0 left-0 flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] whitespace-nowrap shadow-sm transition-opacity',
                hoverId === m.assetId || selectedId === m.assetId ? 'opacity-100' : 'opacity-0'
              )}
            >
              <span className='inline-block size-2 rounded-full' style={{ background: STATUS_COLOR[m.status] }} />
              {m.assetId}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
