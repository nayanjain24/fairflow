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
  call: new THREE.Color('#ff8fb8'), // Pink — Call (interactive)
  game: new THREE.Color('#b79bff'), // Accent-2 — Game (interactive)
  tv: new THREE.Color('#7c5cff'), // Accent — TV x3 (streaming)
  bulk: new THREE.Color('#38bdf8'), // Cyan — Bulk download
  safety: new THREE.Color('#f26a1b'), // Safety Contract Orange
};

function LinkPipeAndStreams({
  metrics,
  onPhaseChange,
}: {
  metrics: LinkSceneMetrics;
  onPhaseChange?: (phase: string) => void;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const gateRingRef = useRef<THREE.Mesh>(null);
  const rollbackRingRef = useRef<THREE.Mesh>(null);
  const queueBarRef = useRef<THREE.Mesh>(null);
  const lastPhaseRef = useRef<string>('');

  // Create instanced packet particles
  const particleCount = 140;
  const instancedRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  const particles = useMemo(() => {
    const arr = [];
    for (let i = 0; i < particleCount; i++) {
      // Assign streams: 0=call, 1=game, 2=tv1, 3=tv2, 4=tv3, 5=bulk
      const streamType = i % 6;
      const laneOffset = (streamType - 2.5) * 0.22;
      const zOffset = ((i % 3) - 1) * 0.16;
      arr.push({
        progress: (i / particleCount) * 10 - 5, // -5 to +5 along X
        speed: streamType === 5 ? 2.6 : 2.1 + (i % 4) * 0.15,
        laneY: laneOffset,
        laneZ: zOffset,
        streamType,
      });
    }
    return arr;
  }, []);

  useFrame((state, delta) => {
    const t = state.clock.getElapsedTime();

    // Story loop cycle (16 seconds total):
    // 0..4s: Flood (Bulk floods, queue fills, call particles stutter before gate)
    // 4..8s: Pre-apply Gate Verifies (Glowing gate ring pulses, rebalances lanes)
    // 8..12s: Smooth Balanced Flow (Queue flat, all streams smooth)
    // 12..16s: Harmful spike -> Red-orange Rollback pulse restores last-known-good
    const cycle = t % 16;
    let queueFill = metrics.queueFillPct ?? 12;
    let isStuttering = false;
    let gateGlow = 0.25;
    let rollbackPulse = 0.0;
    let phaseLabel = 'Balanced Max-Min Fair Flow';

    if (metrics.mode === 'story-loop') {
      if (cycle < 4.2) {
        queueFill = Math.min(95, (cycle / 4.0) * 95);
        isStuttering = cycle > 1.2;
        gateGlow = 0.2;
        phaseLabel = '1. Bulk Floods Link -> Queue Fills & Call Stutters';
      } else if (cycle < 8.0) {
        queueFill = Math.max(12, 95 - ((cycle - 4.2) / 2.2) * 85);
        gateGlow = 1.0;
        isStuttering = false;
        phaseLabel = '2. Pre-Apply Gate Verifies Policy -> Flows Rebalance';
      } else if (cycle < 12.2) {
        queueFill = 8;
        gateGlow = 0.45;
        isStuttering = false;
        phaseLabel = '3. Guardrails Monitored -> Call & Game Protected';
      } else {
        const sub = cycle - 12.2;
        rollbackPulse = Math.sin(Math.min(Math.PI, (sub / 3.2) * Math.PI));
        queueFill = sub < 1.2 ? 78 : 10;
        gateGlow = 0.9;
        phaseLabel = '4. Canary Breach -> Verified Rollback Pulse (#f26a1b)';
      }
    } else {
      queueFill = metrics.queueFillPct ?? 14;
      gateGlow = metrics.gateVerifying ? 1.0 : 0.45;
      rollbackPulse = metrics.rollbackActive ? 1.0 : 0.0;
      isStuttering = queueFill > 65;
      phaseLabel = metrics.rollbackActive
        ? 'Verified Rollback Restoring Baseline'
        : isStuttering
        ? 'Congestion Detected on Link'
        : 'Kernel Verified Policy Enforced';
    }

    if (onPhaseChange && lastPhaseRef.current !== phaseLabel) {
      lastPhaseRef.current = phaseLabel;
      onPhaseChange(phaseLabel);
    }

    // Subtle mouse parallax & scroll dolly
    if (groupRef.current) {
      const targetRotY = state.pointer.x * 0.18;
      const targetRotX = -state.pointer.y * 0.1 + 0.08;
      groupRef.current.rotation.y = THREE.MathUtils.lerp(groupRef.current.rotation.y, targetRotY, 0.06);
      groupRef.current.rotation.x = THREE.MathUtils.lerp(groupRef.current.rotation.x, targetRotX, 0.06);
      const dollyZ = (metrics.scrollProgress || 0) * -1.2;
      groupRef.current.position.z = THREE.MathUtils.lerp(groupRef.current.position.z, dollyZ, 0.08);
    }

    // Animate Gate Ring
    if (gateRingRef.current) {
      gateRingRef.current.rotation.z += delta * (0.5 + gateGlow * 1.4);
      const s = 1 + Math.sin(t * 4) * 0.04 * gateGlow;
      gateRingRef.current.scale.set(s, s, 1);
      const mat = gateRingRef.current.material as THREE.MeshStandardMaterial;
      if (mat) {
        mat.emissiveIntensity = 0.8 + gateGlow * 1.8;
      }
    }

    // Animate Rollback Pulse Ring (#f26a1b)
    if (rollbackRingRef.current) {
      const mat = rollbackRingRef.current.material as THREE.MeshStandardMaterial;
      if (rollbackPulse > 0.02) {
        rollbackRingRef.current.visible = true;
        const pulsePos = THREE.MathUtils.lerp(2.2, -2.2, (t * 1.4) % 1);
        rollbackRingRef.current.position.x = pulsePos;
        const scale = 1.05 + rollbackPulse * 0.35;
        rollbackRingRef.current.scale.set(scale, scale, 1);
        if (mat) mat.opacity = rollbackPulse * 0.9;
      } else {
        rollbackRingRef.current.visible = false;
      }
    }

    // Animate Queue Fill Cylinder
    if (queueBarRef.current) {
      const targetScaleX = Math.max(0.08, (queueFill / 100) * 1.8);
      queueBarRef.current.scale.x = THREE.MathUtils.lerp(queueBarRef.current.scale.x, targetScaleX, 0.1);
      const mat = queueBarRef.current.material as THREE.MeshStandardMaterial;
      if (mat) {
        mat.color.lerp(queueFill > 60 ? STREAM_COLORS.safety : STREAM_COLORS.tv, 0.15);
        mat.emissive.lerp(queueFill > 60 ? STREAM_COLORS.safety : STREAM_COLORS.tv, 0.15);
      }
    }

    // Update packet instances
    if (instancedRef.current) {
      for (let i = 0; i < particleCount; i++) {
        const p = particles[i];
        let stepSpeed = p.speed;

        // When stuttering before the gate (x between -1.6 and 0), call/game packets jitter & stall
        if (isStuttering && (p.streamType === 0 || p.streamType === 1) && p.progress > -1.8 && p.progress < 0.1) {
          stepSpeed *= 0.18;
        }
        if (isStuttering && p.streamType === 5) {
          stepSpeed *= 1.45; // Bulk floods
        }

        p.progress += delta * stepSpeed;
        if (p.progress > 4.6) {
          p.progress = -4.6;
        }

        const jitterY =
          isStuttering && p.streamType <= 1 && p.progress > -1.8 && p.progress < 0.2
            ? Math.sin(t * 28 + i) * 0.12
            : Math.sin(t * 2 + i) * 0.02;

        dummy.position.set(p.progress, p.laneY + jitterY, p.laneZ);
        const radius = p.streamType === 5 && isStuttering ? 0.085 : p.streamType <= 1 ? 0.068 : 0.058;
        dummy.scale.set(radius * 2.2, radius, radius);
        dummy.updateMatrix();
        instancedRef.current.setMatrixAt(i, dummy.matrix);

        // Set stream color
        let c = STREAM_COLORS.bulk;
        if (p.streamType === 0) c = STREAM_COLORS.call;
        else if (p.streamType === 1) c = STREAM_COLORS.game;
        else if (p.streamType >= 2 && p.streamType <= 4) c = STREAM_COLORS.tv;
        if (rollbackPulse > 0.3 && Math.abs(p.progress) < 1.5) {
          c = STREAM_COLORS.safety;
        }
        instancedRef.current.setColorAt(i, c);
      }
      instancedRef.current.instanceMatrix.needsUpdate = true;
      if (instancedRef.current.instanceColor) {
        instancedRef.current.instanceColor.needsUpdate = true;
      }
    }
  });

  return (
    <group ref={groupRef}>
      {/* Main Translucent Link Tube */}
      <mesh rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.88, 0.88, 9.2, 32, 1, true]} />
        <meshPhysicalMaterial
          color="#1b1448"
          emissive="#4c35aa"
          emissiveIntensity={0.28}
          transparent
          opacity={0.24}
          roughness={0.15}
          metalness={0.1}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Inner Core Guide Wireframe */}
      <mesh rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.89, 0.89, 9.2, 16, 6, true]} />
        <meshBasicMaterial color="#7c5cff" wireframe transparent opacity={0.12} />
      </mesh>

      {/* Standing Queue Backlog Volume Indicator before Gate */}
      <mesh ref={queueBarRef} position={[-0.95, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.76, 0.76, 1.0, 24]} />
        <meshStandardMaterial
          color="#7c5cff"
          emissive="#7c5cff"
          emissiveIntensity={0.55}
          transparent
          opacity={0.22}
        />
      </mesh>

      {/* Glowing Pre-Apply Safety Gate Ring at Center (x = 0) */}
      <mesh ref={gateRingRef} position={[0, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
        <torusGeometry args={[1.08, 0.055, 20, 64]} />
        <meshStandardMaterial
          color="#b79bff"
          emissive="#7c5cff"
          emissiveIntensity={1.6}
          roughness={0.2}
        />
      </mesh>

      {/* Secondary Outer Gate Halo */}
      <mesh position={[0, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
        <torusGeometry args={[1.24, 0.018, 16, 64]} />
        <meshBasicMaterial color="#f26a1b" transparent opacity={0.55} />
      </mesh>

      {/* Red-Orange Rollback Verification Pulse Ring (#f26a1b) */}
      <mesh ref={rollbackRingRef} position={[0, 0, 0]} rotation={[0, Math.PI / 2, 0]} visible={false}>
        <torusGeometry args={[1.02, 0.075, 20, 64]} />
        <meshStandardMaterial
          color="#f26a1b"
          emissive="#f26a1b"
          emissiveIntensity={2.4}
          transparent
          opacity={0.9}
        />
      </mesh>

      {/* Instanced Flowing Packet Particles */}
      <instancedMesh ref={instancedRef} args={[undefined, undefined, particleCount]}>
        <sphereGeometry args={[1, 12, 12]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

export const NetworkLinkScene: React.FC<{
  metrics: LinkSceneMetrics;
  fallback?: boolean;
  className?: string;
}> = ({ metrics, fallback = false, className = 'h-[360px] w-full' }) => {
  const [phaseText, setPhaseText] = useState<string>('Observing & Verifying Policy');

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
      aria-label="Interactive 3D network link visualization showing Call, Game, 3 TV streams, and Bulk download passing through the FairFlow Safety Contract Gate."
      className={`relative overflow-hidden rounded-glass border border-[var(--line)] bg-[#07061f]/90 ${className}`}
    >
      {/* Perspective grid floor under the hero visual */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-44 hero-perspective-floor opacity-65" />

      {/* Top HUD Overlay */}
      <div className="pointer-events-none absolute top-4 left-5 right-5 z-10 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 rounded-full border border-white/10 bg-[#06051a]/80 px-3.5 py-1.5 backdrop-blur-md">
          <span className="h-2 w-2 rounded-full bg-[#7c5cff] animate-pulse" />
          <span className="font-mono text-xs text-[#f1efff]">{phaseText}</span>
        </div>

        <div className="flex flex-wrap items-center gap-3 rounded-full border border-white/10 bg-[#06051a]/80 px-3.5 py-1.5 text-[11px] font-mono backdrop-blur-md">
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

      <Canvas
        dpr={[1, 2]}
        camera={{ position: [0, 0.55, 5.6], fov: 42 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <ambientLight intensity={0.7} />
        <pointLight position={[0, 2, 3]} intensity={2.2} color="#b79bff" />
        <pointLight position={[0, -2, -2]} intensity={1.4} color="#f26a1b" />
        <LinkPipeAndStreams metrics={metrics} onPhaseChange={setPhaseText} />
        <EffectComposer enableNormalPass={false}>
          <Bloom luminanceThreshold={0.35} mipmapBlur intensity={0.75} />
        </EffectComposer>
      </Canvas>
    </div>
  );
};

export default NetworkLinkScene;
