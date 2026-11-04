import React, { useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { EffectComposer, Bloom } from '@react-three/postprocessing';
import * as THREE from 'three';

export interface LinkSceneMetrics {
  mode: 'story-loop' | 'live';
  callRateMbps?: number;
  gameRateMbps?: number;
  tvRateMbps?: number;
  bulkRateMbps?: number;
  queueFillPct?: number; // 0 to 100
  gateVerifying?: boolean;
  rollbackActive?: boolean;
  scrollProgress?: number;
}

const STREAM_COLORS = {
  call: new THREE.Color('#ff8fb8'), // VoIP Call (Interactive 1:10)
  game: new THREE.Color('#b79bff'), // Gaming UDP (Interactive 1:10)
  tv: new THREE.Color('#7c5cff'), // 4K TV Streams (Streaming 1:20)
  bulk: new THREE.Color('#38bdf8'), // Bulk Download (Bulk 1:30)
  safety: new THREE.Color('#f26a1b'), // Safety Contract / Rollback
  emerald: new THREE.Color('#34d399'), // Verified Protected State
  white: new THREE.Color('#f4f1ff'),
};

interface StreamTrackDef {
  id: number;
  name: string;
  streamType: 0 | 1 | 2 | 3; // 0=Call, 1=Game, 2=TV, 3=Bulk
  colorHex: string;
  inY: number;
  inZ: number;
  gateY: number;
  gateZ: number;
  outY: number;
  outZ: number;
}

// 5 3D fiber-optic pathways that fan in from left WAN sources, converge through the
// central Pre-Apply Safety Gate (x = 0), and emerge as a protected laminar bundle on the right.
const TRACK_DEFS: StreamTrackDef[] = [
  {
    id: 0,
    name: 'VoIP Call (1:10)',
    streamType: 0,
    colorHex: '#ff8fb8',
    inY: 0.92,
    inZ: 0.42,
    gateY: 0.34,
    gateZ: 0.16,
    outY: 0.34,
    outZ: 0.14,
  },
  {
    id: 1,
    name: 'Gaming UDP (1:10)',
    streamType: 1,
    colorHex: '#b79bff',
    inY: 0.48,
    inZ: -0.52,
    gateY: 0.14,
    gateZ: -0.2,
    outY: 0.14,
    outZ: -0.16,
  },
  {
    id: 2,
    name: '4K TV Stream A (1:20)',
    streamType: 2,
    colorHex: '#7c5cff',
    inY: 0.04,
    inZ: 0.56,
    gateY: -0.02,
    gateZ: 0.22,
    outY: -0.02,
    outZ: 0.18,
  },
  {
    id: 3,
    name: '4K TV Stream B (1:20)',
    streamType: 2,
    colorHex: '#7c5cff',
    inY: -0.44,
    inZ: -0.46,
    gateY: -0.18,
    gateZ: -0.18,
    outY: -0.18,
    outZ: -0.15,
  },
  {
    id: 4,
    name: 'Bulk TCP Download (1:30)',
    streamType: 3,
    colorHex: '#38bdf8',
    inY: -0.92,
    inZ: 0.28,
    gateY: -0.35,
    gateZ: 0.08,
    outY: -0.35,
    outZ: 0.06,
  },
];

function FairFlow3DCore({
  metrics,
  lockedStoryPhase,
  onPhaseChange,
}: {
  metrics: LinkSceneMetrics;
  lockedStoryPhase: number | null;
  onPhaseChange?: (phase: string, activeStepIndex: number) => void;
}) {
  const rootRef = useRef<THREE.Group>(null);
  const gatePrimaryRingRef = useRef<THREE.Mesh>(null);
  const gateGyroRingARef = useRef<THREE.Mesh>(null);
  const gateGyroRingBRef = useRef<THREE.Mesh>(null);
  const shaperCoreRef = useRef<THREE.Mesh>(null);
  const gateLensRef = useRef<THREE.Mesh>(null);
  const rollbackWaveRef = useRef<THREE.Mesh>(null);
  const queueHaloRef = useRef<THREE.Mesh>(null);
  const lastPhaseRef = useRef<string>('');

  // Build smooth 3D CatmullRom curves and tube geometries for each of the 5 optical pathways
  const { curves, tubeGeometries, ingressNodes } = useMemo(() => {
    const builtCurves: THREE.CatmullRomCurve3[] = [];
    const builtGeos: THREE.TubeGeometry[] = [];
    const nodes: Array<{ pos: THREE.Vector3; color: string }> = [];

    for (const def of TRACK_DEFS) {
      const p0 = new THREE.Vector3(-4.35, def.inY, def.inZ);
      const p1 = new THREE.Vector3(-2.45, def.inY * 0.72, def.inZ * 0.75);
      const p2 = new THREE.Vector3(-0.9, def.gateY * 1.08, def.gateZ * 1.08);
      const p3 = new THREE.Vector3(0.0, def.gateY, def.gateZ);
      const p4 = new THREE.Vector3(1.6, def.outY, def.outZ);
      const p5 = new THREE.Vector3(4.35, def.outY, def.outZ);

      const curve = new THREE.CatmullRomCurve3([p0, p1, p2, p3, p4, p5]);
      builtCurves.push(curve);
      builtGeos.push(new THREE.TubeGeometry(curve, 72, 0.012, 8, false));
      nodes.push({ pos: p0, color: def.colorHex });
    }

    return { curves: builtCurves, tubeGeometries: builtGeos, ingressNodes: nodes };
  }, []);

  // 130 sleek light-pulse capsules banking along the 5 3D splines (26 per track)
  const particleCount = 130;
  const instancedPacketsRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const upAxis = useMemo(() => new THREE.Vector3(0, 1, 0), []);
  const pointVec = useMemo(() => new THREE.Vector3(), []);
  const tangentVec = useMemo(() => new THREE.Vector3(), []);

  const particles = useMemo(() => {
    const arr = [];
    const tracks = TRACK_DEFS.length;
    const perTrack = particleCount / tracks;
    for (let i = 0; i < particleCount; i++) {
      const trackIdx = i % tracks;
      const slot = Math.floor(i / tracks);
      const def = TRACK_DEFS[trackIdx];
      arr.push({
        u: slot / perTrack, // 0.0 -> 1.0 along the 3D curve
        baseSpeed: def.streamType === 3 ? 0.21 : def.streamType === 2 ? 0.175 : 0.195,
        trackIdx,
        streamType: def.streamType,
        phaseSeed: slot * 0.7 + trackIdx,
      });
    }
    return arr;
  }, []);

  useFrame((state, delta) => {
    const t = state.clock.getElapsedTime();

    // 32-second narrative cycle (8 seconds per stage) or manual stage lock
    const cycle = t % 32;
    let queueFill = metrics.queueFillPct ?? 12;
    let isCongested = false;
    let gateVerifyIntensity = 0.35;
    let rollbackPulse = 0.0;
    let phaseLabel = 'Balanced Max-Min Fair Flow';
    let stepIdx = 3;

    if (metrics.mode === 'story-loop') {
      const effectiveStage =
        lockedStoryPhase !== null
          ? lockedStoryPhase
          : cycle < 8
          ? 1
          : cycle < 16
          ? 2
          : cycle < 24
          ? 3
          : 4;

      stepIdx = effectiveStage;

      if (effectiveStage === 1) {
        const sub = lockedStoryPhase !== null ? 4.0 : cycle;
        queueFill = Math.min(92, 24 + (sub / 6.0) * 68);
        isCongested = true;
        gateVerifyIntensity = 0.25;
        phaseLabel = '1. Unshaped Bulk Flood → Upstream Queue Pressure Builds';
      } else if (effectiveStage === 2) {
        const sub = lockedStoryPhase !== null ? 2.5 : cycle - 8;
        queueFill = Math.max(12, 86 - (sub / 5.0) * 74);
        gateVerifyIntensity = 1.0;
        isCongested = false;
        phaseLabel = '2. Pre-Apply Safety Gate Verifies Policy → Flows Rebalance';
      } else if (effectiveStage === 3) {
        queueFill = 9;
        gateVerifyIntensity = 0.6;
        isCongested = false;
        phaseLabel = '3. Guardrails Active (HTB + fq_codel) → Laminar Protected Egress';
      } else {
        const sub = lockedStoryPhase !== null ? (t % 4.2) : cycle - 24;
        rollbackPulse = Math.sin(Math.min(Math.PI, (sub / 3.8) * Math.PI));
        queueFill = sub < 1.4 ? 80 : 10;
        gateVerifyIntensity = 0.95;
        phaseLabel = '4. Canary Breach Detected → Verified Rollback Pulse (#f26a1b)';
      }
    } else {
      queueFill = metrics.queueFillPct ?? 12;
      gateVerifyIntensity = metrics.gateVerifying ? 1.0 : 0.55;
      rollbackPulse = metrics.rollbackActive ? 1.0 : 0.0;
      isCongested = queueFill > 65;
      stepIdx = metrics.rollbackActive ? 4 : metrics.gateVerifying ? 2 : isCongested ? 1 : 3;
      phaseLabel = metrics.rollbackActive
        ? 'Verified Rollback Restoring Baseline (pol_v1_baseline)'
        : isCongested
        ? 'Link Congestion Detected • Guardrail Shaping Active'
        : 'Kernel-Verified Policy Active (HTB + fq_codel)';
    }

    if (onPhaseChange && lastPhaseRef.current !== phaseLabel) {
      lastPhaseRef.current = phaseLabel;
      onPhaseChange(phaseLabel, stepIdx);
    }

    // Smooth 3D Isometric Camera Parallax & Gentle Breathing
    if (rootRef.current) {
      const targetRotY = -0.24 + state.pointer.x * 0.22 + Math.sin(t * 0.4) * 0.035;
      const targetRotX = 0.15 - state.pointer.y * 0.1 + Math.cos(t * 0.3) * 0.02;
      rootRef.current.rotation.y = THREE.MathUtils.lerp(rootRef.current.rotation.y, targetRotY, 0.05);
      rootRef.current.rotation.x = THREE.MathUtils.lerp(rootRef.current.rotation.x, targetRotX, 0.05);
      rootRef.current.position.y = Math.sin(t * 0.85) * 0.035;
      const dollyZ = (metrics.scrollProgress || 0) * -0.75;
      rootRef.current.position.z = THREE.MathUtils.lerp(rootRef.current.position.z, dollyZ, 0.06);
    }

    // Animate 3D Gyroscopic Safety Gate Core at x = 0
    const isAlert = rollbackPulse > 0.15;
    if (gatePrimaryRingRef.current) {
      gatePrimaryRingRef.current.rotation.z += delta * 0.3;
      const mat = gatePrimaryRingRef.current.material as THREE.MeshStandardMaterial;
      if (mat) {
        mat.color.lerp(isAlert ? STREAM_COLORS.safety : STREAM_COLORS.white, 0.12);
        mat.emissive.lerp(isAlert ? STREAM_COLORS.safety : STREAM_COLORS.tv, 0.12);
        mat.emissiveIntensity = 1.2 + gateVerifyIntensity * 1.1 + rollbackPulse * 1.0;
      }
    }

    if (gateGyroRingARef.current) {
      gateGyroRingARef.current.rotation.x = Math.sin(t * 0.7) * 0.35;
      gateGyroRingARef.current.rotation.z -= delta * (0.55 + gateVerifyIntensity * 0.6);
      const mat = gateGyroRingARef.current.material as THREE.MeshStandardMaterial;
      if (mat) {
        mat.color.lerp(isAlert ? STREAM_COLORS.safety : STREAM_COLORS.game, 0.12);
        mat.emissive.lerp(isAlert ? STREAM_COLORS.safety : STREAM_COLORS.game, 0.12);
      }
    }

    if (gateGyroRingBRef.current) {
      gateGyroRingBRef.current.rotation.y = Math.PI / 2 + Math.cos(t * 0.6) * 0.28;
      gateGyroRingBRef.current.rotation.z += delta * 0.45;
    }

    if (shaperCoreRef.current) {
      shaperCoreRef.current.rotation.x += delta * 0.5;
      shaperCoreRef.current.rotation.y += delta * 0.7;
      const s = 1 + Math.sin(t * 3.0) * 0.06 * gateVerifyIntensity;
      shaperCoreRef.current.scale.set(s, s, s);
      const mat = shaperCoreRef.current.material as THREE.MeshStandardMaterial;
      if (mat) {
        mat.emissive.lerp(
          isAlert
            ? STREAM_COLORS.safety
            : stepIdx === 3
            ? STREAM_COLORS.emerald
            : STREAM_COLORS.tv,
          0.12
        );
      }
    }

    if (gateLensRef.current) {
      const mat = gateLensRef.current.material as THREE.MeshBasicMaterial;
      if (mat) {
        mat.color.lerp(isAlert ? STREAM_COLORS.safety : STREAM_COLORS.game, 0.12);
        mat.opacity = 0.07 + gateVerifyIntensity * 0.1;
      }
    }

    // Rollback Shockwave Portal (#f26a1b)
    if (rollbackWaveRef.current) {
      const mat = rollbackWaveRef.current.material as THREE.MeshStandardMaterial;
      if (rollbackPulse > 0.02) {
        rollbackWaveRef.current.visible = true;
        const progress = (t * 0.85) % 1;
        rollbackWaveRef.current.position.x = THREE.MathUtils.lerp(2.2, -2.4, progress);
        const s = 0.85 + Math.sin(progress * Math.PI) * 0.45;
        rollbackWaveRef.current.scale.set(s, s, 1);
        if (mat) mat.opacity = rollbackPulse * 0.9;
      } else {
        rollbackWaveRef.current.visible = false;
      }
    }

    // Upstream Queue Pressure Halo (x = -0.65)
    if (queueHaloRef.current) {
      const mat = queueHaloRef.current.material as THREE.MeshBasicMaterial;
      if (mat) {
        mat.color.lerp(queueFill > 60 ? STREAM_COLORS.safety : STREAM_COLORS.tv, 0.12);
        mat.opacity = queueFill > 35 ? 0.12 + (queueFill / 100) * 0.28 : 0.04;
      }
      const haloScale = 0.92 + (queueFill / 100) * 0.25;
      queueHaloRef.current.scale.set(haloScale, haloScale, 1);
    }

    // Update 130 3D Spline-Following Light Capsules
    if (instancedPacketsRef.current) {
      for (let i = 0; i < particleCount; i++) {
        const p = particles[i];
        let speed = p.baseSpeed;

        // Pre-gate zone is u in [0.22, 0.50]
        const inPreGate = p.u > 0.22 && p.u < 0.5;
        if (isCongested && (p.streamType === 0 || p.streamType === 1) && inPreGate) {
          speed *= 0.32;
        } else if (isCongested && p.streamType === 3 && p.u < 0.5) {
          speed *= 1.35;
        }

        p.u = (p.u + delta * speed) % 1.0;

        const curve = curves[p.trackIdx];
        curve.getPointAt(p.u, pointVec);
        curve.getTangentAt(p.u, tangentVec);

        // Micro-jitter upstream of gate during Stage 1 congestion
        if (isCongested && (p.streamType === 0 || p.streamType === 1) && inPreGate) {
          pointVec.y += Math.sin(t * 22 + p.phaseSeed) * 0.038;
        }

        dummy.position.copy(pointVec);
        // Align capsule Y-axis along the 3D spline tangent vector
        dummy.quaternion.setFromUnitVectors(upAxis, tangentVec.normalize());

        const stretch =
          isCongested && (p.streamType === 0 || p.streamType === 1) && inPreGate ? 0.65 : 1.3;
        dummy.scale.set(1, stretch, 1);
        dummy.updateMatrix();
        instancedPacketsRef.current.setMatrixAt(i, dummy.matrix);

        let c = STREAM_COLORS.bulk;
        if (p.streamType === 0) c = STREAM_COLORS.call;
        else if (p.streamType === 1) c = STREAM_COLORS.game;
        else if (p.streamType === 2) c = STREAM_COLORS.tv;

        if (rollbackPulse > 0.25 && Math.abs(p.u - 0.5) < 0.16) {
          c = STREAM_COLORS.safety;
        }
        instancedPacketsRef.current.setColorAt(i, c);
      }

      instancedPacketsRef.current.instanceMatrix.needsUpdate = true;
      if (instancedPacketsRef.current.instanceColor) {
        instancedPacketsRef.current.instanceColor.needsUpdate = true;
      }
    }
  });

  return (
    <group ref={rootRef}>
      {/* LEFT SIDE: 5 Curved 3D Fiber-Optic Spline Tubes Converging into the Safety Gate */}
      {tubeGeometries.map((geo, idx) => (
        <mesh key={idx} geometry={geo}>
          <meshBasicMaterial
            color={TRACK_DEFS[idx].colorHex}
            transparent
            opacity={0.22}
          />
        </mesh>
      ))}

      {/* WAN Source Emitter Nodes on the Left (x = -4.35) */}
      {ingressNodes.map((node, idx) => (
        <group key={idx} position={node.pos}>
          <mesh rotation={[0, Math.PI / 2, 0]}>
            <torusGeometry args={[0.09, 0.014, 12, 32]} />
            <meshBasicMaterial color={node.color} />
          </mesh>
          <mesh>
            <sphereGeometry args={[0.045, 16, 16]} />
            <meshBasicMaterial color="#ffffff" />
          </mesh>
        </group>
      ))}

      {/* RIGHT SIDE: Protected Sapphire Glass Trunk Housing the Shaped Laminar Egress (x = 0 to +4.35) */}
      <group position={[2.18, -0.05, 0]}>
        <mesh rotation={[0, 0, Math.PI / 2]}>
          <cylinderGeometry args={[0.58, 0.58, 4.35, 64, 1, true]} />
          <meshPhysicalMaterial
            color="#120d36"
            emissive="#3b278c"
            emissiveIntensity={0.24}
            transparent
            opacity={0.2}
            roughness={0.1}
            metalness={0.25}
            clearcoat={1}
            side={THREE.DoubleSide}
          />
        </mesh>

        {/* Precision Section Rings along the Protected Right Trunk */}
        {[-1.1, 0.0, 1.1].map((offset, idx) => (
          <mesh key={idx} position={[offset, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
            <torusGeometry args={[0.585, 0.005, 12, 64]} />
            <meshBasicMaterial color="#34d399" transparent opacity={0.28} />
          </mesh>
        ))}
      </group>

      {/* Protected LAN Egress Portal at Right End (x = +4.35) */}
      <group position={[4.35, -0.05, 0]} rotation={[0, Math.PI / 2, 0]}>
        <mesh>
          <torusGeometry args={[0.59, 0.022, 20, 64]} />
          <meshStandardMaterial color="#34d399" emissive="#34d399" emissiveIntensity={1.1} />
        </mesh>
        <mesh>
          <circleGeometry args={[0.58, 48]} />
          <meshBasicMaterial color="#34d399" transparent opacity={0.07} side={THREE.DoubleSide} />
        </mesh>
      </group>

      {/* Pre-Gate Queue Pressure Ring Upstream of Gate (x = -0.65) */}
      <mesh ref={queueHaloRef} position={[-0.65, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
        <torusGeometry args={[0.72, 0.018, 16, 64]} />
        <meshBasicMaterial color="#7c5cff" transparent opacity={0.12} />
      </mesh>

      {/* CENTERPIECE: 3D GYROSCOPIC PRE-APPLY SAFETY GATE & HTB SHAPER CORE (x = 0) */}
      <group position={[0, 0, 0]}>
        {/* Translucent Verification Scan Plane */}
        <mesh ref={gateLensRef} rotation={[0, Math.PI / 2, 0]}>
          <circleGeometry args={[0.92, 64]} />
          <meshBasicMaterial color="#b79bff" transparent opacity={0.09} side={THREE.DoubleSide} />
        </mesh>

        {/* Primary Outer Architectural Gate Portal */}
        <mesh ref={gatePrimaryRingRef} rotation={[0, Math.PI / 2, 0]}>
          <torusGeometry args={[0.95, 0.032, 28, 96]} />
          <meshStandardMaterial
            color="#f4f1ff"
            emissive="#7c5cff"
            emissiveIntensity={1.5}
            roughness={0.15}
            metalness={0.5}
          />
        </mesh>

        {/* Gyroscopic Orbital Verification Ring A */}
        <mesh ref={gateGyroRingARef} rotation={[0.35, Math.PI / 2, 0]}>
          <torusGeometry args={[0.78, 0.014, 20, 72]} />
          <meshStandardMaterial
            color="#b79bff"
            emissive="#b79bff"
            emissiveIntensity={1.2}
          />
        </mesh>

        {/* Gyroscopic Orbital Verification Ring B */}
        <mesh ref={gateGyroRingBRef} rotation={[0, Math.PI / 2 + 0.35, 0]}>
          <torusGeometry args={[0.64, 0.01, 16, 64]} />
          <meshBasicMaterial color="#38bdf8" transparent opacity={0.55} />
        </mesh>

        {/* Center Crystalline Octahedral HTB Shaper Core */}
        <mesh ref={shaperCoreRef}>
          <octahedronGeometry args={[0.16, 0]} />
          <meshStandardMaterial
            color="#ffffff"
            emissive="#7c5cff"
            emissiveIntensity={1.8}
            roughness={0.1}
            metalness={0.6}
            wireframe
          />
        </mesh>
      </group>

      {/* Safety Contract Orange Rollback Shockwave Portal (#f26a1b) */}
      <mesh ref={rollbackWaveRef} position={[0, 0, 0]} rotation={[0, Math.PI / 2, 0]} visible={false}>
        <torusGeometry args={[0.88, 0.038, 24, 72]} />
        <meshStandardMaterial
          color="#f26a1b"
          emissive="#f26a1b"
          emissiveIntensity={2.6}
          transparent
          opacity={0.92}
        />
      </mesh>

      {/* 130 Sleek 3D Curve-Following Light Capsules */}
      <instancedMesh ref={instancedPacketsRef} args={[undefined, undefined, particleCount]}>
        <capsuleGeometry args={[0.026, 0.095, 8, 16]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

const STORY_STAGES = [
  { id: 1, short: '1. Surge' },
  { id: 2, short: '2. Gate Verify' },
  { id: 3, short: '3. Protected' },
  { id: 4, short: '4. Rollback' },
] as const;

export const NetworkLinkScene: React.FC<{
  metrics: LinkSceneMetrics;
  fallback?: boolean;
  className?: string;
}> = ({ metrics, fallback = false, className = 'h-[360px] w-full' }) => {
  const [phaseText, setPhaseText] = useState<string>('Observing & Verifying Policy');
  const [activeStageIdx, setActiveStageIdx] = useState<number>(3);
  const [lockedStoryPhase, setLockedStoryPhase] = useState<number | null>(null);

  if (fallback) {
    return (
      <div
        role="img"
        aria-label="FairFlow network link visualization showing four traffic classes (call, game, TV x3, bulk download) passing through the Pre-apply Safety Gate."
        className={`relative overflow-hidden rounded-glass border border-[var(--line)] bg-gradient-to-br from-[#120d38] via-[#090724] to-[#0f2347] p-6 flex flex-col justify-between ${className}`}
      >
        <div className="flex items-center justify-between text-xs font-mono text-[#b79bff]">
          <span>STATIC FALLBACK (REDUCED MOTION / MOBILE)</span>
          <span className="text-[#f26a1b]">SAFETY GATE ACTIVE</span>
        </div>
        <div className="my-auto space-y-3">
          <div className="h-3 w-full rounded-full bg-white/5 overflow-hidden flex">
            <div className="h-full w-2/12 bg-[#ff8fb8]" title="Call stream" />
            <div className="h-full w-2/12 bg-[#b79bff]" title="Game stream" />
            <div className="h-full w-4/12 bg-[#7c5cff]" title="TV x3 streams" />
            <div className="h-full w-4/12 bg-[#38bdf8]" title="Bulk download" />
          </div>
          <p className="text-xs text-[var(--mute)] text-center font-mono">
            Call (#ff8fb8) • Game (#b79bff) • 3× TV (#7c5cff) • Bulk (#38bdf8) → Verified by Pre-Apply Gate
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      role="region"
      aria-label="Interactive 3D network link visualization showing Call, Game, 3 TV streams, and Bulk download converging through the FairFlow Gyroscopic Safety Gate Core into a protected laminar trunk."
      className={`relative overflow-hidden rounded-glass border border-white/15 bg-gradient-to-b from-[#0b0829] via-[#07051c] to-[#0b1530] shadow-purple-glow ${className}`}
    >
      {/* Ambient radial spotlight behind the 3D Gyroscopic Safety Gate */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(circle at 50% 50%, rgba(124, 92, 255, 0.22), rgba(56, 189, 248, 0.05) 45%, transparent 72%)',
        }}
      />

      {/* Perspective grid floor */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 hero-perspective-floor opacity-65" />

      {/* Top Status Pill & Traffic Class Legend */}
      <div className="pointer-events-none absolute top-4 left-5 right-5 z-10 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 rounded-full border border-white/15 bg-[#06051a]/85 px-3.5 py-1.5 backdrop-blur-md shadow-md">
          <span
            className={`h-2 w-2 rounded-full animate-pulse ${
              activeStageIdx === 4
                ? 'bg-[#f26a1b] shadow-[0_0_8px_#f26a1b]'
                : activeStageIdx === 3
                ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]'
                : 'bg-[#7c5cff] shadow-[0_0_8px_#7c5cff]'
            }`}
          />
          <span className="font-mono text-xs text-[#f1efff] tracking-tight">{phaseText}</span>
        </div>

        <div className="flex flex-wrap items-center gap-3 rounded-full border border-white/15 bg-[#06051a]/85 px-3.5 py-1.5 text-[11px] font-mono backdrop-blur-md shadow-md">
          <span className="flex items-center gap-1.5 text-[#ff8fb8]">
            <span className="h-2 w-2 rounded-full bg-[#ff8fb8]" /> Call
          </span>
          <span className="flex items-center gap-1.5 text-[#b79bff]">
            <span className="h-2 w-2 rounded-full bg-[#b79bff]" /> Game
          </span>
          <span className="flex items-center gap-1.5 text-[#7c5cff]">
            <span className="h-2 w-2 rounded-full bg-[#7c5cff]" /> TV ×3
          </span>
          <span className="flex items-center gap-1.5 text-[#38bdf8]">
            <span className="h-2 w-2 rounded-full bg-[#38bdf8]" /> Bulk
          </span>
          <span className="flex items-center gap-1.5 text-[#f26a1b]">
            <span className="h-2 w-2 rounded-full bg-[#f26a1b]" /> Gate / Rollback
          </span>
        </div>
      </div>

      {/* Bottom Architecture Flow Label & Interactive Stage Controls */}
      <div className="absolute bottom-3.5 left-5 right-5 z-10 flex flex-wrap items-center justify-between gap-2">
        <div className="pointer-events-none hidden sm:flex items-center gap-2 rounded-full border border-white/10 bg-[#06051a]/75 px-3 py-1 font-mono text-[10px] tracking-wider text-[#cbd5e1] uppercase backdrop-blur-md">
          <span className="text-[#38bdf8]">5× Unshaped WAN Streams</span>
          <span className="text-white/40">→</span>
          <span className="text-[#b79bff]">Pre-Apply Safety Gate Core</span>
          <span className="text-white/40">→</span>
          <span className="text-emerald-300">Shaped Laminar Trunk</span>
        </div>

        {metrics.mode === 'story-loop' && (
          <div className="flex items-center gap-1 rounded-full border border-white/15 bg-[#06051a]/85 p-1 font-mono text-[11px] backdrop-blur-md shadow-md">
            <button
              type="button"
              onClick={() => setLockedStoryPhase(null)}
              className={`rounded-full px-2.5 py-0.5 transition-all cursor-pointer ${
                lockedStoryPhase === null
                  ? 'bg-[#7c5cff] text-white font-semibold'
                  : 'text-[var(--mute)] hover:text-white'
              }`}
            >
              Auto
            </button>
            {STORY_STAGES.map((st) => {
              const isSelected = lockedStoryPhase === st.id;
              const isCurrentAuto = lockedStoryPhase === null && activeStageIdx === st.id;
              return (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => setLockedStoryPhase(st.id)}
                  className={`rounded-full px-2.5 py-0.5 transition-all cursor-pointer ${
                    isSelected
                      ? st.id === 4
                        ? 'bg-[#f26a1b] text-white font-semibold'
                        : 'bg-[#b79bff]/30 border border-[#b79bff] text-white font-semibold'
                      : isCurrentAuto
                      ? 'bg-white/15 text-white'
                      : 'text-[var(--mute)] hover:text-white'
                  }`}
                >
                  {st.short}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <Canvas
        dpr={[1, 2]}
        camera={{ position: [0, 0.25, 5.05], fov: 38 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <ambientLight intensity={0.9} />
        <pointLight position={[0, 2.5, 3.2]} intensity={2.5} color="#b79bff" />
        <pointLight position={[0, -2.0, -2.0]} intensity={1.4} color="#7c5cff" />
        <pointLight position={[-4.0, 0.6, 2.0]} intensity={1.2} color="#38bdf8" />
        <pointLight position={[4.0, 0.6, 2.0]} intensity={1.2} color="#34d399" />
        <FairFlow3DCore
          metrics={metrics}
          lockedStoryPhase={lockedStoryPhase}
          onPhaseChange={(label, idx) => {
            setPhaseText(label);
            setActiveStageIdx(idx);
          }}
        />
        <EffectComposer enableNormalPass={false}>
          <Bloom luminanceThreshold={0.32} mipmapBlur intensity={0.8} />
        </EffectComposer>
      </Canvas>
    </div>
  );
};

export default NetworkLinkScene;
