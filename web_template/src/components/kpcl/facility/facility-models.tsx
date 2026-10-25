import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import type { Group, Mesh, MeshStandardMaterial } from 'three'
import { type FacilityMachine, hasFault, type MachineStatus } from './facility-data'
import { FOOTPRINT, STATUS_COLOR } from './facility-style'

// Low-poly primitive models (boxes / cylinders / cones) so the panel renders fast and stays legible
// at card size. 1 unit ≈ 1 m. Every model sits on the floor at y = 0.


const STEEL = '#8a96a3'
const DARK = '#3b4651'
const LEAD_BLUE = '#2f6fb3'
const LAG_GREEN = '#6b8f74'

type ModelProps = { m: FacilityMachine; active: boolean }

function Box({ args, position, color, rotation, emissive, opacity }: {
  args: [number, number, number]
  position: [number, number, number]
  color: string
  rotation?: [number, number, number]
  emissive?: string
  opacity?: number
}) {
  return (
    <mesh position={position} rotation={rotation} castShadow>
      <boxGeometry args={args} />
      <meshStandardMaterial
        color={color}
        emissive={emissive ?? '#000000'}
        emissiveIntensity={emissive ? 0.8 : 0}
        transparent={opacity !== undefined}
        opacity={opacity ?? 1}
        roughness={0.6}
        metalness={0.2}
      />
    </mesh>
  )
}

function Cyl({ r, h, position, color, rotation, rTop, segments = 20 }: {
  r: number
  h: number
  position: [number, number, number]
  color: string
  rotation?: [number, number, number]
  rTop?: number
  segments?: number
}) {
  return (
    <mesh position={position} rotation={rotation} castShadow>
      <cylinderGeometry args={[rTop ?? r, r, h, segments]} />
      <meshStandardMaterial color={color} roughness={0.5} metalness={0.35} />
    </mesh>
  )
}

/** Spins a group around Y while `on`. */
function Spinner({ on, speed = 3, children, position }: { on: boolean; speed?: number; children: React.ReactNode; position?: [number, number, number] }) {
  const ref = useRef<Group>(null)
  useFrame((_, dt) => {
    if (on && ref.current) ref.current.rotation.y += dt * speed
  })
  return (
    <group ref={ref} position={position}>
      {children}
    </group>
  )
}

const CentrifugalCompressor = ({ m }: ModelProps) => (
  <group>
    <Box args={[1.7, 0.15, 0.9]} position={[0, 0.075, 0]} color={DARK} />
    <Cyl r={0.36} h={1.15} position={[-0.15, 0.55, 0]} rotation={[0, 0, Math.PI / 2]} color={m.role === 'lag' ? LAG_GREEN : LEAD_BLUE} />
    <Cyl r={0.26} h={0.45} position={[0.65, 0.48, 0]} rotation={[0, 0, Math.PI / 2]} color={STEEL} />
    <Cyl r={0.08} h={0.5} position={[-0.45, 1.05, 0]} color={STEEL} />
    <Cyl r={0.08} h={0.35} position={[0.1, 0.98, 0.18]} color={STEEL} />
  </group>
)

const ScrewCompressor = ({ m }: ModelProps) => (
  <group>
    <Box args={[1.1, 0.8, 0.75]} position={[0, 0.4, 0]} color={m.role === 'lead' ? LEAD_BLUE : LAG_GREEN} />
    {[-0.12, 0.12].map((z) => (
      <Cyl key={z} r={0.09} h={0.85} position={[0, 0.9, z]} rotation={[0, 0, Math.PI / 2]} color={STEEL} />
    ))}
    <Box args={[0.02, 0.45, 0.5]} position={[0.56, 0.45, 0]} color={DARK} />
  </group>
)

const ReciprocatingCompressor = ({ m }: ModelProps) => (
  <group>
    <Box args={[1.0, 0.5, 0.6]} position={[0, 0.25, 0]} color={m.role === 'lead' ? LEAD_BLUE : LAG_GREEN} />
    {[-0.3, 0, 0.3].map((x) => (
      <Cyl key={x} r={0.11} h={0.45} position={[x, 0.72, 0]} color={STEEL} />
    ))}
    <Spinner on={m.status === 'running'} position={[0.6, 0.38, 0]}>
      <Cyl r={0.36} h={0.07} position={[0, 0, 0]} rotation={[Math.PI / 2, 0, 0]} color={DARK} segments={28} />
    </Spinner>
  </group>
)

const CngTestRig = ({ m }: ModelProps) => (
  <group>
    <Box args={[1.5, 0.08, 0.9]} position={[0, 0.04, 0]} color={DARK} />
    {[[-0.7, -0.4], [0.7, -0.4], [-0.7, 0.4], [0.7, 0.4]].map(([x, z]) => (
      <Box key={`${x}${z}`} args={[0.06, 1.0, 0.06]} position={[x, 0.55, z]} color={STEEL} />
    ))}
    <Box args={[1.5, 0.06, 0.06]} position={[0, 1.05, -0.4]} color={STEEL} />
    <Box args={[1.5, 0.06, 0.06]} position={[0, 1.05, 0.4]} color={STEEL} />
    {[-0.45, -0.15, 0.15].map((x) => (
      <Cyl key={x} r={0.12} h={0.8} position={[x, 0.5, 0]} color='#c9a227' />
    ))}
    <Box args={[0.35, 0.4, 0.05]} position={[0.45, 0.6, 0.38]} color='#d8dee4' />
    {[0.35, 0.55].map((x) => (
      <mesh key={x} position={[x, 0.66, 0.42]}>
        <sphereGeometry args={[0.06, 12, 12]} />
        <meshStandardMaterial color='#f1f5f9' emissive={m.status === 'running' ? '#22c55e' : '#000000'} emissiveIntensity={0.4} />
      </mesh>
    ))}
  </group>
)

const VamChiller = ({ m }: ModelProps) => (
  <group>
    <Box args={[1.4, 0.95, 0.85]} position={[0, 0.475, 0]} color='#7a8794' />
    <Box args={[0.35, 0.3, 0.3]} position={[0.85, 0.15, 0]} color={DARK} />
    {m.status === 'running' && (
      <mesh position={[0.85, 0.42, 0]}>
        <coneGeometry args={[0.1, 0.25, 12]} />
        <meshStandardMaterial color='#f97316' emissive='#f97316' emissiveIntensity={1.2} />
      </mesh>
    )}
    <Cyl r={0.06} h={0.5} position={[0.85, 0.55, -0.1]} color={STEEL} />
  </group>
)

const ElectricScrewChiller = ({ m }: ModelProps) => (
  <group>
    <Box args={[1.4, 0.95, 0.85]} position={[0, 0.475, 0]} color='#6f8796' />
    <mesh position={[0, 0.98, 0]} rotation={[Math.PI / 2, 0, 0]}>
      <torusGeometry args={[0.3, 0.04, 8, 24]} />
      <meshStandardMaterial color={DARK} />
    </mesh>
    <Spinner on={m.status === 'running'} speed={8} position={[0, 0.99, 0]}>
      {[0, Math.PI / 2].map((r) => (
        <Box key={r} args={[0.52, 0.02, 0.07]} position={[0, 0, 0]} rotation={[0, r, 0]} color={STEEL} />
      ))}
    </Spinner>
  </group>
)

const CncMachine = ({ m }: ModelProps) => {
  const drift = hasFault(m, 'cnc_idle_drift')
  const active = m.state === 'cutting' || m.status === 'running'
  return (
    <group>
      <Box args={[1.1, 0.95, 0.85]} position={[0, 0.475, 0]} color='#cfd6dd' />
      <Box args={[0.7, 0.5, 0.02]} position={[-0.1, 0.55, 0.43]} color='#9cc8e8' opacity={0.4} />
      <Cyl r={0.06} h={0.3} position={[-0.1, 0.62, 0.1]} color={DARK} />
      <Box args={[0.22, 0.32, 0.04]} position={[0.42, 0.62, 0.44]} color={DARK} />
      {/* "active" indicator: bright while cutting; idle-power drift dims it even when the spindle is idle */}
      <mesh position={[0.42, 1.0, 0.3]}>
        <sphereGeometry args={[0.06, 12, 12]} />
        <meshStandardMaterial
          color={active ? '#22c55e' : '#334155'}
          emissive={active ? '#22c55e' : '#000000'}
          emissiveIntensity={drift ? 0.15 : active ? 1.2 : 0}
        />
      </mesh>
    </group>
  )
}

const Furnace = ({ m }: ModelProps) => {
  const doorOpen = hasFault(m, 'furnace_door_open')
  const hot = m.state === 'ramp' || m.state === 'hold'
  return (
    <group>
      <Box args={[0.95, 1.4, 0.95]} position={[0, 0.7, 0]} color='#5b6470' emissive={hot ? '#7c2d12' : undefined} />
      <Cyl r={0.1} h={0.7} position={[0.25, 1.75, -0.2]} color={DARK} />
      {/* door hinged on its left edge: swings open (and turns red) during the door-open fault */}
      <group position={[-0.42, 0.62, 0.49]} rotation={[0, doorOpen ? -1.15 : 0, 0]}>
        <Box args={[0.84, 0.95, 0.06]} position={[0.42, 0, 0]} color={doorOpen ? '#dc2626' : '#9aa3ad'} emissive={doorOpen ? '#7f1d1d' : undefined} />
      </group>
      {doorOpen && (
        <mesh position={[0, 0.62, 0.47]}>
          <planeGeometry args={[0.7, 0.8]} />
          <meshStandardMaterial color='#f97316' emissive='#ea580c' emissiveIntensity={1.4} />
        </mesh>
      )}
    </group>
  )
}

const PaintBooth = ({ m }: ModelProps) => (
  <group>
    <Box args={[1.8, 1.3, 0.06]} position={[0, 0.65, -0.6]} color='#9aa5b1' />
    {[-0.6, -0.2, 0.2, 0.6].map((x) => (
      <Box key={x} args={[0.32, 1.0, 0.03]} position={[x, 0.65, -0.55]} color='#e2e8f0' />
    ))}
    <Box args={[0.06, 1.3, 1.2]} position={[-0.9, 0.65, 0]} color='#aab4bf' />
    <Box args={[0.06, 1.3, 1.2]} position={[0.9, 0.65, 0]} color='#aab4bf' />
    <Box args={[1.86, 0.06, 1.2]} position={[0, 1.33, 0]} color='#aab4bf' />
    <Box args={[0.6, 0.3, 0.5]} position={[0, 1.51, -0.25]} color={DARK} />
    <Spinner on={m.status === 'running' || m.status === 'fault'} speed={6} position={[0, 1.67, -0.25]}>
      {[0, Math.PI / 2].map((r) => (
        <Box key={r} args={[0.4, 0.02, 0.06]} position={[0, 0, 0]} rotation={[0, r, 0]} color={STEEL} />
      ))}
    </Spinner>
  </group>
)

const SolarArray = ({ m }: ModelProps) => {
  const glow = m.status === 'running' ? Math.min(1, (m.kW ?? 0) / 300) : 0
  return (
    <group>
      {[-1.6, -0.55, 0.5, 1.55].map((z) =>
        [-2.2, -1.32, -0.44, 0.44, 1.32, 2.2].map((x) => (
          <group key={`${x}${z}`} position={[x, 0, z]}>
            <Box args={[0.04, 0.35, 0.04]} position={[0, 0.17, 0.15]} color={STEEL} />
            <mesh position={[0, 0.3, 0]} rotation={[-0.45, 0, 0]} castShadow>
              <boxGeometry args={[0.82, 0.03, 0.6]} />
              <meshStandardMaterial color='#1e3a8a' emissive='#3b82f6' emissiveIntensity={glow * 0.35} metalness={0.5} roughness={0.25} />
            </mesh>
          </group>
        ))
      )}
    </group>
  )
}

const MODELS: Record<string, (p: ModelProps) => React.JSX.Element> = {
  compressor_centrifugal: CentrifugalCompressor,
  compressor_screw: ScrewCompressor,
  compressor_reciprocating: ReciprocatingCompressor,
  compressor_test_rig: CngTestRig,
  chiller_vam: VamChiller,
  chiller_screw_electric: ElectricScrewChiller,
  cnc: CncMachine,
  furnace_heat_treat: Furnace,
  paint_booth: PaintBooth,
  solar_pv: SolarArray,
}

/** Status ring on the floor + beacon; red ones pulse. */
function StatusMarker({ status, radius, height }: { status: MachineStatus; radius: number; height: number }) {
  const ring = useRef<MeshStandardMaterial>(null)
  const beacon = useRef<Mesh>(null)
  useFrame(({ clock }) => {
    if (status !== 'fault') return
    const k = 0.5 + 0.5 * Math.sin(clock.elapsedTime * 5)
    if (ring.current) ring.current.emissiveIntensity = 0.4 + 1.4 * k
    if (beacon.current) beacon.current.scale.setScalar(0.85 + 0.4 * k)
  })
  const color = STATUS_COLOR[status]
  return (
    <group>
      <mesh position={[0, 0.012, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[radius, radius + 0.09, 40]} />
        <meshStandardMaterial ref={ring} color={color} emissive={color} emissiveIntensity={status === 'off' || status === 'no-data' ? 0 : 0.6} />
      </mesh>
      <mesh ref={beacon} position={[0, height + 0.18, 0]}>
        <sphereGeometry args={[0.09, 14, 14]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={status === 'off' || status === 'no-data' ? 0.1 : 1} />
      </mesh>
    </group>
  )
}


export function MachineModel({ m, active }: ModelProps) {
  const Model = MODELS[m.kind]
  const fp = FOOTPRINT[m.kind] ?? { r: 0.8, h: 1 }
  return (
    <group>
      {Model ? <Model m={m} active={active} /> : <Box args={[0.8, 0.8, 0.8]} position={[0, 0.4, 0]} color={STEEL} />}
      <StatusMarker status={m.status} radius={fp.r} height={fp.h} />
      {active && (
        <mesh position={[0, 0.006, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <circleGeometry args={[fp.r, 40]} />
          <meshBasicMaterial color='#60a5fa' transparent opacity={0.18} />
        </mesh>
      )}
    </group>
  )
}
