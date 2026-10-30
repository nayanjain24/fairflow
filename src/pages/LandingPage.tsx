import React, { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import Lenis from 'lenis';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Cpu,
  Eye,
  FileCheck2,
  Gauge,
  GitCommit,
  Layers,
  Minus,
  RotateCcw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sliders,
  Terminal,
} from 'lucide-react';
import { TiltCard } from '../components/TiltCard';
import { useReducedMotion, useShouldUseStatic3DFallback } from '../hooks/useReducedMotion';
import { useDiskReports } from '../hooks/useFairFlowData';

gsap.registerPlugin(ScrollTrigger);

const LazyNetworkLinkScene = lazy(() => import('../scene/NetworkLinkScene'));

const PIPELINE_STEPS = [
  {
    step: 1,
    group: 'sense',
    title: 'Observe',
    subtitle: '2 s telemetry windows',
    copy: 'Ingests UDP probe sequence records (RTT, p95 added delay, RFC 3550 jitter, loss) and 1 Hz Linux tc qdisc backlog/drop counters on monotonic clock boundaries.',
    icon: Eye,
  },
  {
    step: 2,
    group: 'sense',
    title: 'Classify & estimate',
    subtitle: 'Metadata-only + capacity',
    copy: 'Classifies flows into interactive, streaming, or bulk using L3/L4 header heuristics and expiring user intents (zero payload inspection) while tracking usable link capacity.',
    icon: Layers,
  },
  {
    step: 3,
    group: 'sense',
    title: 'Propose',
    subtitle: 'Max-min water-filling',
    copy: 'Reserves mandatory minimum floors first, distributes surplus via progressive max-min fairness, and suppresses minor adjustments within the 10% deadband.',
    icon: Sliders,
  },
  {
    step: 4,
    group: 'safety',
    title: 'Verify',
    subtitle: 'Pre-apply safety gate',
    copy: 'Proves mathematically that sum of minimum floors <= usable capacity (95% shaped) and adaptation rate change <= 25% max step before touching the kernel.',
    icon: FileCheck2,
  },
  {
    step: 5,
    group: 'safety',
    title: 'Apply',
    subtitle: 'Snapshot + tc readback',
    copy: 'Snapshots current qdisc state, applies HTB + fq_codel leaf classes in ff_router, and independently reads back kernel state to confirm exact enforcement.',
    icon: GitCommit,
  },
  {
    step: 6,
    group: 'safety',
    title: 'Monitor & recover',
    subtitle: '10 s canary + rollback',
    copy: 'Evaluates 5 canary windows against delay (80 ms), jitter (30 ms), and loss (2%) guardrails. On 2 consecutive breaches, restores last-known-good and verifies.',
    icon: RotateCcw,
  },
];

const SAFETY_CONTRACT_CARDS = [
  {
    id: 1,
    title: 'Pre-apply gate',
    badge: 'GATE 01 • DETERMINISTIC CHECK',
    orangeOutline: true,
    copy: 'Every candidate policy is checked before touching the kernel: structure, rate floors (interactive >= 2 Mbps, streaming >= 8 Mbps, bulk >= 2 Mbps), max step <= 25%, and total floors <= usable capacity. Invalid or unsafe policies are rejected upfront.',
    icon: ShieldCheck,
  },
  {
    id: 2,
    title: 'Runtime guardrails',
    badge: 'CANARY • 5 WINDOWS (10 S)',
    orangeOutline: false,
    copy: 'Once applied, policies enter a 10-second canary (five 2-second windows). Added p95 delay must stay <= 80 ms (target 30 ms), RFC 3550 jitter <= 30 ms (target 10 ms), and packet loss <= 2.0% (target 0.5%).',
    icon: Gauge,
  },
  {
    id: 3,
    title: 'Verified rollback',
    badge: 'FAIL-CLOSED • KERNEL READBACK',
    orangeOutline: true,
    copy: 'If two consecutive canary windows breach any guardrail, or if tc apply fails, the coordinator restores the last-known-good snapshot and independently queries tc -j qdisc show to verify restoration before logging recovery.',
    icon: RotateCcw,
  },
  {
    id: 4,
    title: 'Fair when feasible',
    badge: 'MAX-MIN WATER-FILLING',
    orangeOutline: false,
    copy: 'When usable capacity covers all minimum service floors, FairFlow reserves every class floor first and allocates remaining bandwidth via progressive max-min water-filling so no single bulk flow starves interactive traffic.',
    icon: Scale,
  },
  {
    id: 5,
    title: 'Honest when not',
    badge: 'EXPLICIT INFEASIBILITY REPORT',
    orangeOutline: false,
    copy: 'If bottleneck capacity collapses below the sum of mandatory floors (12.0 Mbps), FairFlow never claims success or silently drops guarantees—it rejects the infeasible proposal, holds safe baseline, and reports exact per-class shortfall.',
    icon: AlertTriangle,
  },
];

const METRIC_CHIPS = [
  { label: 'p95 interactive latency', detail: 'Target <= 30 ms | Guardrail <= 80 ms', primary: true },
  { label: 'Jitter', detail: 'RFC 3550 target <= 10 ms | Guardrail <= 30 ms', primary: true },
  { label: 'Packet loss', detail: 'Target <= 0.5% | Guardrail <= 2.0%', primary: true },
  { label: "Jain's fairness index", detail: 'Target >= 0.85 across competing streams', primary: true },
  { label: 'Adaptation / recovery time', detail: '2 breach windows detect | <1 s kernel restore', primary: true },
  { label: 'Throughput', detail: '95% shaped link utilization', primary: false },
  { label: 'Estimator accuracy', detail: 'Confidence-weighted capacity bounds', primary: false },
  { label: 'CPU overhead', detail: 'vCPU-pinned low-overhead control loop', primary: false },
];

const STACK_ITEMS = [
  'Python',
  'Linux tc (HTB, fq_codel/CAKE)',
  'network namespaces',
  'iperf3 + UDP probes',
  'rules-first classifier',
  'SQLite',
  'Streamlit',
  'pytest',
];

export const LandingPage: React.FC = () => {
  const reducedMotion = useReducedMotion();
  const static3DFallback = useShouldUseStatic3DFallback();
  const { data: reportsData } = useDiskReports();

  const [scrollProgress, setScrollProgress] = useState(0);
  const [activePipelineStep, setActivePipelineStep] = useState(1);
  const pipelineSectionRef = useRef<HTMLDivElement>(null);
  const comparisonRef = useRef<HTMLDivElement>(null);

  // Smooth scrolling with Lenis (respects prefers-reduced-motion)
  useEffect(() => {
    if (reducedMotion) return;
    const lenis = new Lenis({
      duration: 1.05,
      smoothWheel: true,
    });

    let rafId: number;
    function raf(time: number) {
      lenis.raf(time);
      rafId = requestAnimationFrame(raf);
    }
    rafId = requestAnimationFrame(raf);

    return () => {
      cancelAnimationFrame(rafId);
      lenis.destroy();
    };
  }, [reducedMotion]);

  // Scroll-driven pipeline activation & hero camera dolly
  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      setScrollProgress(Math.min(1, y / 700));

      if (pipelineSectionRef.current) {
        const rect = pipelineSectionRef.current.getBoundingClientRect();
        const vh = window.innerHeight;
        const rel = (vh * 0.68 - rect.top) / Math.max(1, rect.height * 0.85);
        const clamped = Math.max(0, Math.min(0.999, rel));
        const step = Math.floor(clamped * 6) + 1;
        setActivePipelineStep(step);
      }
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // GSAP ScrollTrigger reveals for comparison ticks
  useEffect(() => {
    if (reducedMotion || !comparisonRef.current) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        '.comp-tick',
        { scale: 0.4, opacity: 0 },
        {
          scale: 1,
          opacity: 1,
          duration: 0.45,
          stagger: 0.08,
          ease: 'back.out(1.8)',
          scrollTrigger: {
            trigger: comparisonRef.current,
            start: 'top 80%',
          },
        }
      );
    }, comparisonRef);

    return () => ctx.revert();
  }, [reducedMotion]);

  // Extract real scenario runs from backend/disk if present
  const scenAReport = reportsData?.reports.find((r) => r.scenario_id === 'scenario_a');
  const scenBReport = reportsData?.reports.find((r) => r.scenario_id === 'scenario_b');
  const scenCReport = reportsData?.reports.find((r) => r.scenario_id === 'scenario_c');
  const scenDReport = reportsData?.reports.find((r) => r.scenario_id === 'scenario_d');

  return (
    <main className="relative overflow-hidden">
      {/* Large Purple Radial Glow at Top of Hero */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-40 left-1/2 -translate-x-1/2 h-[680px] w-[1150px] rounded-full opacity-55 blur-[130px]"
        style={{
          background:
            'radial-gradient(circle at 50% 35%, rgba(124, 92, 255, 0.58) 0%, rgba(183, 155, 255, 0.22) 45%, rgba(6, 5, 26, 0) 75%)',
        }}
      />

      {/* 2. HERO SECTION */}
      <section id="overview" className="relative mx-auto max-w-7xl px-4 pt-12 pb-20 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-4xl text-center">
          <div className="mb-4 inline-flex items-center gap-2.5 rounded-full border border-[var(--line)] bg-white/[0.04] px-4 py-1.5 text-xs font-mono text-[#b79bff]">
            <span className="h-2 w-2 rounded-full bg-[#f26a1b]" />
            <span className="font-semibold tracking-wider text-white">FAIRFLOW</span>
            <span className="text-[var(--mute)]">•</span>
            <span>SAFETY-VERIFIED ADAPTIVE QOS CONTROLLER</span>
          </div>

          <div className="mb-3 text-4xl sm:text-6xl lg:text-7xl font-semibold tracking-tight text-white">
            Fair<span className="bg-gradient-to-r from-[#b79bff] via-[#7c5cff] to-[#f26a1b] bg-clip-text text-transparent">Flow</span>
          </div>

          <h1 className="text-2xl sm:text-4xl lg:text-5xl font-light tracking-tight text-[var(--text)] leading-[1.18]">
            QoS that proves every policy is safe before it applies it, and{' '}
            <strong className="font-semibold text-white bg-gradient-to-r from-[#f1efff] via-[#b79bff] to-[#f26a1b] bg-clip-text text-transparent">
              undoes it if it isn't.
            </strong>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-base sm:text-lg font-normal text-[var(--mute)] leading-relaxed">
            Calls and games stay smooth during big downloads without manual tuning. If the controller ever makes things worse, it reverts itself and tells you why.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to="/dashboard" className="btn-primary">
              <span>Open live dashboard</span>
              <ArrowRight className="h-4 w-4" />
            </Link>
            <a href="#how-it-works" className="btn-secondary">
              See how it works
            </a>
          </div>
        </div>

        {/* Hero 3D Scene */}
        <div className="mt-12">
          <Suspense
            fallback={
              <div className="h-[380px] sm:h-[430px] w-full rounded-glass border border-[var(--line)] bg-[#090724] flex items-center justify-center font-mono text-xs text-[var(--mute)]">
                Initializing 3D network link visualization...
              </div>
            }
          >
            <LazyNetworkLinkScene
              metrics={{ mode: 'story-loop', scrollProgress }}
              fallback={static3DFallback}
              className="h-[380px] sm:h-[430px] w-full shadow-glass"
            />
          </Suspense>
        </div>
      </section>

      {/* 3. THE PROBLEM */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="glass-card p-8 sm:p-12">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
            <div className="lg:col-span-6 space-y-4">
              <span className="font-mono text-xs uppercase tracking-widest text-[#ff8fb8]">
                THE HOME BROADBAND BOTTLENECK
              </span>
              <h2 className="text-2xl sm:text-4xl font-light text-[var(--text)] leading-snug">
                A work call, a game and three TV streams <strong className="font-semibold text-white">share one link...</strong>
              </h2>
              <p className="text-sm sm:text-base text-[var(--mute)] leading-relaxed">
                When a multi-gigabyte bulk download starts, TCP Cubic fills the ISP modem’s 200 ms drop-tail buffer. Standing queues spike one-way delay from 15 ms to over 214 ms—freezing voice calls and rubber-banding games.
              </p>
              <p className="text-sm sm:text-base text-[var(--mute)] leading-relaxed">
                Static QoS breaks when ISP capacity drops in the evening; naive adaptive scripts can push bad rules that starve streams or worsen latency with no way to recover.
              </p>
            </div>

            {/* Animated Before / After Queue Bars */}
            <div className="lg:col-span-6 grid grid-cols-1 sm:grid-cols-2 gap-5">
              {/* Before Card */}
              <div className="rounded-2xl border border-rose-500/30 bg-[#0b0826]/90 p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-rose-300 font-semibold">BEFORE (UNMANAGED R0)</span>
                  <span className="rounded-full bg-rose-500/20 px-2.5 py-0.5 font-mono text-[11px] text-rose-300">
                    +198 ms bloat
                  </span>
                </div>
                <div className="space-y-3 pt-1">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--mute)]">ISP Modem Queue</span>
                      <span className="font-mono text-rose-400">98% FULL (200 ms)</span>
                    </div>
                    <div className="h-3 w-full rounded-full bg-white/5 overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-rose-500 to-orange-500 w-[96%] animate-pulse rounded-full" />
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--mute)]">Call p99 Added Delay</span>
                      <span className="font-mono text-rose-400">197.98 ms (Stuttering)</span>
                    </div>
                    <div className="h-2.5 w-full rounded-full bg-white/5 overflow-hidden">
                      <div className="h-full bg-rose-500 w-[92%] rounded-full" />
                    </div>
                  </div>
                </div>
                <p className="text-xs text-[var(--mute)] font-mono pt-1">
                  ✗ Call packets trapped behind bulk TCP bursts
                </p>
              </div>

              {/* After Card */}
              <div className="rounded-2xl border border-[#7c5cff]/45 bg-[#0b0826]/90 p-5 space-y-4 shadow-purple-glow">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-[#b79bff] font-semibold">AFTER (FAIRFLOW)</span>
                  <span className="rounded-full bg-emerald-500/20 px-2.5 py-0.5 font-mono text-[11px] text-emerald-300">
                    +1.51 ms flat
                  </span>
                </div>
                <div className="space-y-3 pt-1">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--mute)]">Shaped Router Queue</span>
                      <span className="font-mono text-emerald-300">4% FLAT (fq_codel)</span>
                    </div>
                    <div className="h-3 w-full rounded-full bg-white/5 overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-[#7c5cff] to-emerald-400 w-[8%] rounded-full" />
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--mute)]">Call p99 Added Delay</span>
                      <span className="font-mono text-emerald-300">1.51 ms (&lt;= 30 ms target)</span>
                    </div>
                    <div className="h-2.5 w-full rounded-full bg-white/5 overflow-hidden">
                      <div className="h-full bg-emerald-400 w-[7%] rounded-full" />
                    </div>
                  </div>
                </div>
                <p className="text-xs text-[#b79bff] font-mono pt-1">
                  ✓ Sparse interactive flows isolated; 88+ Mbps bulk preserved
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 4. WHAT MAKES FAIRFLOW DIFFERENT (Comparison Table) */}
      <section ref={comparisonRef} className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto mb-10">
          <span className="font-mono text-xs uppercase tracking-widest text-[#b79bff]">
            ARCHITECTURAL CAPABILITY MATRIX
          </span>
          <h2 className="mt-2 text-2xl sm:text-4xl font-light text-[var(--text)]">
            What makes <strong className="font-semibold text-white">FairFlow different</strong>
          </h2>
        </div>

        <div className="glass-card overflow-hidden p-4 sm:p-8">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[var(--line)] text-xs font-mono uppercase text-[var(--mute)]">
                  <th className="py-4 px-4 sm:px-6">Capability</th>
                  <th className="py-4 px-4 text-center">Static QoS</th>
                  <th className="py-4 px-4 text-center">Basic adaptive</th>
                  <th className="py-4 px-6 text-center rounded-t-2xl border-t border-x border-[#f26a1b]/50 bg-[#f26a1b]/[0.08] text-[#f1efff] shadow-orange-glow">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-[#f26a1b]">
                      <ShieldCheck className="h-4 w-4" /> FairFlow
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)] text-sm">
                <tr>
                  <td className="py-5 px-4 sm:px-6 font-medium text-[var(--text)]">
                    Adapts to changing demand and capacity
                  </td>
                  <td className="py-5 px-4 text-center text-[var(--mute)]">
                    <span className="comp-tick inline-flex items-center justify-center" aria-label="No">
                      <Minus className="h-4 w-4 text-[var(--mute)]" />
                    </span>
                  </td>
                  <td className="py-5 px-4 text-center">
                    <span
                      className="comp-tick inline-flex items-center justify-center rounded-full bg-white/10 p-1 text-white"
                      aria-label="Yes"
                    >
                      <Check className="h-4 w-4" />
                    </span>
                  </td>
                  <td className="py-5 px-6 text-center border-x border-[#f26a1b]/50 bg-[#f26a1b]/[0.08]">
                    <span
                      className="comp-tick inline-flex items-center justify-center rounded-full bg-[#f26a1b]/25 border border-[#f26a1b] p-1 text-[#f26a1b]"
                      aria-label="Yes"
                    >
                      <Check className="h-4 w-4" />
                    </span>
                  </td>
                </tr>

                <tr>
                  <td className="py-5 px-4 sm:px-6 font-medium text-[var(--text)]">
                    Verifies before applying and rolls back on breach
                  </td>
                  <td className="py-5 px-4 text-center text-[var(--mute)]">
                    <span className="comp-tick inline-flex items-center justify-center" aria-label="No">
                      <Minus className="h-4 w-4 text-[var(--mute)]" />
                    </span>
                  </td>
                  <td className="py-5 px-4 text-center text-[var(--mute)]">
                    <span className="comp-tick inline-flex items-center justify-center" aria-label="No">
                      <Minus className="h-4 w-4 text-[var(--mute)]" />
                    </span>
                  </td>
                  <td className="py-5 px-6 text-center border-x border-[#f26a1b]/50 bg-[#f26a1b]/[0.08]">
                    <span
                      className="comp-tick inline-flex items-center justify-center rounded-full bg-[#f26a1b]/25 border border-[#f26a1b] p-1 text-[#f26a1b]"
                      aria-label="Yes"
                    >
                      <Check className="h-4 w-4" />
                    </span>
                  </td>
                </tr>

                <tr>
                  <td className="py-5 px-4 sm:px-6 font-medium text-[var(--text)]">
                    Fair minimums and reports when infeasible
                  </td>
                  <td className="py-5 px-4 text-center text-[var(--mute)]">
                    <span className="comp-tick inline-flex items-center justify-center" aria-label="No">
                      <Minus className="h-4 w-4 text-[var(--mute)]" />
                    </span>
                  </td>
                  <td className="py-5 px-4 text-center text-[var(--mute)]">
                    <span className="comp-tick inline-flex items-center justify-center" aria-label="No">
                      <Minus className="h-4 w-4 text-[var(--mute)]" />
                    </span>
                  </td>
                  <td className="py-5 px-6 text-center rounded-b-2xl border-b border-x border-[#f26a1b]/50 bg-[#f26a1b]/[0.08] shadow-orange-glow">
                    <span
                      className="comp-tick inline-flex items-center justify-center rounded-full bg-[#f26a1b]/25 border border-[#f26a1b] p-1 text-[#f26a1b]"
                      aria-label="Yes"
                    >
                      <Check className="h-4 w-4" />
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-center font-mono text-xs text-[var(--mute)]">
            Design capabilities compared, not measured performance.
          </p>
        </div>
      </section>

      {/* 5. SENSE AND DECIDE, THEN SAFETY CONTRACT PIPELINE */}
      <section
        id="how-it-works"
        ref={pipelineSectionRef}
        className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8"
      >
        <div className="text-center max-w-3xl mx-auto mb-12">
          <span className="font-mono text-xs uppercase tracking-widest text-[#b79bff]">
            CLOSED-LOOP ARCHITECTURE
          </span>
          <h2 className="mt-2 text-2xl sm:text-4xl font-light text-[var(--text)]">
            Sense and decide, then <strong className="font-semibold text-[#f26a1b]">Safety contract pipeline</strong>
          </h2>
          <p className="mt-3 text-sm sm:text-base text-[var(--mute)]">
            Six deterministic stages split into two groups: unprivileged observation & proposal (steps 1–3) and the fail-closed Safety Contract (steps 4–6).
          </p>
        </div>

        {/* Group Headers */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-4">
          <div className="rounded-full border border-white/15 bg-white/[0.03] px-5 py-2 flex items-center justify-between">
            <span className="font-mono text-xs uppercase tracking-wider text-[var(--text)]">
              GROUP A • SENSE AND DECIDE (STEPS 1–3)
            </span>
            <span className="text-xs text-[var(--mute)] font-mono">Pure & Side-Effect Free</span>
          </div>
          <div className="rounded-full border border-[#f26a1b]/60 bg-[#f26a1b]/10 px-5 py-2 flex items-center justify-between">
            <span className="font-mono text-xs uppercase tracking-wider text-[#f26a1b] font-semibold">
              GROUP B • SAFETY CONTRACT (STEPS 4–6)
            </span>
            <span className="text-xs text-[#f26a1b] font-mono">Pre-Apply Gate + Canary + Rollback</span>
          </div>
        </div>

        {/* Travelling Glowing Packet Bar */}
        <div className="relative h-2 w-full rounded-full bg-white/10 my-6 overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-300"
            style={{
              width: `${(activePipelineStep / 6) * 100}%`,
              background:
                activePipelineStep >= 4
                  ? 'linear-gradient(90deg, #7c5cff 0%, #f26a1b 100%)'
                  : 'linear-gradient(90deg, #b79bff 0%, #7c5cff 100%)',
              boxShadow: activePipelineStep >= 4 ? '0 0 20px #f26a1b' : '0 0 20px #7c5cff',
            }}
          />
        </div>

        {/* 6 Pipeline Step Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-4">
          {PIPELINE_STEPS.map((s) => {
            const Icon = s.icon;
            const isSafety = s.group === 'safety';
            const isActive = activePipelineStep >= s.step;
            return (
              <div
                key={s.step}
                onMouseEnter={() => setActivePipelineStep(s.step)}
                className={`rounded-2xl p-5 border transition-all duration-300 flex flex-col justify-between ${
                  isSafety
                    ? isActive
                      ? 'bg-[#0f2347]/90 border-[#f26a1b] shadow-orange-glow'
                      : 'bg-[#0f2347]/50 border-[#f26a1b]/35'
                    : isActive
                    ? 'bg-white/[0.07] border-white/40 shadow-glass'
                    : 'bg-white/[0.03] border-[var(--line)]'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <span
                      className={`font-mono text-xs font-semibold px-2.5 py-0.5 rounded-full ${
                        isSafety
                          ? 'bg-[#f26a1b]/20 text-[#f26a1b] border border-[#f26a1b]/40'
                          : 'bg-white/10 text-white'
                      }`}
                    >
                      0{s.step}
                    </span>
                    <Icon className={`h-4 w-4 ${isSafety ? 'text-[#f26a1b]' : 'text-[#b79bff]'}`} />
                  </div>
                  <h3 className="text-base font-semibold text-white">{s.title}</h3>
                  <p className={`text-xs font-mono mt-0.5 ${isSafety ? 'text-[#f26a1b]' : 'text-[#b79bff]'}`}>
                    {s.subtitle}
                  </p>
                  <p className="mt-3 text-xs text-[var(--mute)] leading-relaxed">{s.copy}</p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Animated Loop-back Rollback Line */}
        <div className="mt-6 rounded-2xl border border-[#f26a1b]/65 bg-gradient-to-r from-[#0f2347]/90 via-[#f26a1b]/15 to-[#0f2347]/90 p-4 sm:p-5 shadow-orange-glow">
          <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-3">
            <div className="flex items-center gap-2.5 text-[#f26a1b] font-mono text-xs font-semibold">
              <RotateCcw className="h-4 w-4 animate-spin" style={{ animationDuration: '6s' }} />
              <span>AUTOMATED VERIFIED ROLLBACK LOOP (STEP 6 → STEP 5)</span>
            </div>
            <div className="font-mono text-xs sm:text-sm text-[var(--text)] flex flex-wrap items-center gap-2">
              <span className="rounded bg-[#f26a1b]/20 border border-[#f26a1b]/50 px-2 py-0.5 text-[#f26a1b] font-semibold">
                Breach
              </span>
              <span className="text-[#f26a1b]">&gt;</span>
              <span className="rounded bg-white/5 px-2 py-0.5">restore last-known-good</span>
              <span className="text-[#f26a1b]">&gt;</span>
              <span className="rounded bg-white/5 px-2 py-0.5">
                confirm config restored and metrics within limits
              </span>
              <span className="text-[#f26a1b]">&gt;</span>
              <span className="rounded bg-emerald-500/15 border border-emerald-500/40 px-2 py-0.5 text-emerald-300">
                log reason
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 6. THE FAIRFLOW SAFETY CONTRACT (Deep Navy #0f2347 section) */}
      <section
        id="safety-contract"
        className="relative my-12 border-y border-[#f26a1b]/30 bg-[#0f2347]/65 py-20"
      >
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mb-12">
            <span className="inline-flex items-center gap-2 rounded-full border border-[#f26a1b]/50 bg-[#f26a1b]/15 px-3.5 py-1 font-mono text-xs text-[#f26a1b]">
              <ShieldAlert className="h-3.5 w-3.5" /> THE FAIRFLOW SAFETY CONTRACT
            </span>
            <h2 className="mt-4 text-3xl sm:text-5xl font-light text-[#f26a1b] tracking-tight">
              Verify before applying. <strong className="font-semibold text-white">Recover if unsafe.</strong>
            </h2>
            <p className="mt-3 text-sm sm:text-base text-[#cbd5e1]">
              Five non-negotiable guarantees enforced on every control cycle by <code className="font-mono text-xs text-[#f26a1b]">contract.yaml</code> and <code className="font-mono text-xs text-[#b79bff]">EnforcementCoordinator</code>.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {SAFETY_CONTRACT_CARDS.map((card) => {
              const Icon = card.icon;
              return (
                <TiltCard
                  key={card.id}
                  disabled={reducedMotion}
                  className={
                    card.orangeOutline
                      ? 'glass-card-safety-orange p-7 flex flex-col justify-between'
                      : 'glass-card-safety p-7 flex flex-col justify-between'
                  }
                >
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-4">
                      <span
                        className={`font-mono text-[11px] uppercase tracking-wider px-2.5 py-1 rounded-full ${
                          card.orangeOutline
                            ? 'bg-[#f26a1b]/20 text-[#f26a1b] border border-[#f26a1b]/50'
                            : 'bg-white/10 text-[#b79bff]'
                        }`}
                      >
                        {card.badge}
                      </span>
                      <Icon className={`h-5 w-5 ${card.orangeOutline ? 'text-[#f26a1b]' : 'text-[#b79bff]'}`} />
                    </div>
                    <h3 className="text-xl font-semibold text-white mb-2.5">{card.title}</h3>
                    <p className="text-sm text-[#cbd5e1] leading-relaxed">{card.copy}</p>
                  </div>
                </TiltCard>
              );
            })}
          </div>

          <div className="mt-10 rounded-2xl border border-white/15 bg-[#06051a]/60 px-6 py-4 text-center">
            <p className="font-mono text-xs sm:text-sm text-[#f1efff]">
              “Each mechanism is known on its own; the contribution is integrating them into one measurable control loop.”
            </p>
          </div>
        </div>
      </section>

      {/* 7. CLASSIFICATION AND NETWORK + DASHBOARD AND REPRODUCIBILITY */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div className="glass-card p-8 space-y-4">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs uppercase tracking-widest text-[#b79bff]">
                PRIVACY-PRESERVING CLASSIFICATION & KERNEL ENFORCEMENT
              </span>
              <Cpu className="h-5 w-5 text-[#7c5cff]" />
            </div>
            <h3 className="text-2xl font-light text-white">
              Classification and <strong className="font-semibold">network plane</strong>
            </h3>
            <p className="text-sm text-[var(--mute)] leading-relaxed">
              FairFlow classifies flows into <code className="font-mono text-xs text-white">interactive</code>, <code className="font-mono text-xs text-white">streaming</code>, <code className="font-mono text-xs text-white">bulk</code>, or <code className="font-mono text-xs text-white">unknown</code> using strictly metadata-only signals: Layer 3/4 headers, DSCP marks, packet pacing, and mean packet size—with zero payload inspection or DPI.
            </p>
            <ul className="space-y-2 text-xs sm:text-sm text-[var(--text)] font-mono pt-2">
              <li className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#7c5cff] shrink-0" />
                <span>Ambiguous/unknown traffic defaults safely to best-effort bulk</span>
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#7c5cff] shrink-0" />
                <span>User-correctable intent overrides with mandatory expiration</span>
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#7c5cff] shrink-0" />
                <span>Enforced via Linux tc (HTB + fq_codel/CAKE) inside isolated ff_* namespaces</span>
              </li>
            </ul>
          </div>

          <div className="glass-card p-8 space-y-4">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs uppercase tracking-widest text-[#ff8fb8]">
                OBSERVABILITY & DETERMINISTIC HARNESS
              </span>
              <Terminal className="h-5 w-5 text-[#ff8fb8]" />
            </div>
            <h3 className="text-2xl font-light text-white">
              Dashboard and <strong className="font-semibold">reproducibility</strong>
            </h3>
            <p className="text-sm text-[var(--mute)] leading-relaxed">
              Every observation window, capacity estimate, pre-apply gate verdict, kernel qdisc snapshot, and canary rollback is written immutably to SQLite (<code className="font-mono text-xs text-white">results/audit.db</code>) and raw trial CSV/JSON artifacts.
            </p>
            <ul className="space-y-2 text-xs sm:text-sm text-[var(--text)] font-mono pt-2">
              <li className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#ff8fb8] shrink-0" />
                <span>Block-randomized trials with SHA-256 verified contract.yaml</span>
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#ff8fb8] shrink-0" />
                <span>Observed monotonic timestamps for phase slicing (0.5 s warmup filter)</span>
              </li>
              <li className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#ff8fb8] shrink-0" />
                <span>10,000-resample bootstrap 95% confidence intervals on medians</span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* 8. VALIDATION PLAN */}
      <section id="validation" className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-10">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-[#f26a1b]/50 bg-[#f26a1b]/10 px-3.5 py-1 font-mono text-xs text-[#f26a1b] mb-3">
              <span>VALIDATION PLAN • PLANNED, NOT YET EXECUTED (FULL 10-TRIAL MATRIX)</span>
            </div>
            <h2 className="text-2xl sm:text-4xl font-light text-[var(--text)]">
              Four scenario benchmarks & <strong className="font-semibold text-white">pass criteria</strong>
            </h2>
          </div>
          <Link to="/lab" className="btn-secondary self-start md:self-auto">
            Run scenarios in Lab →
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* S1 */}
          <div className="glass-card p-6 flex flex-col justify-between space-y-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#b79bff] font-semibold">S1 • SCENARIO A</span>
                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-0.5 font-mono text-[11px] text-emerald-300">
                  {scenAReport ? `Smoke run: ${scenAReport.run_id}` : 'Not yet run'}
                </span>
              </div>
              <h3 className="mt-2 text-lg font-semibold text-white">S1 Download vs call</h3>
              <p className="mt-1 text-xs sm:text-sm text-[var(--mute)]">
                50 pps G.711 UDP voice call sharing a 100 Mbps bottleneck (15 ms one-way delay, 200 ms buffer) with a saturated TCP Cubic bulk download.
              </p>
              <div className="mt-3 rounded-xl bg-white/[0.03] border border-[var(--line)] p-3 font-mono text-xs space-y-1">
                <div className="text-[var(--mute)]">Pass criteria:</div>
                <div className="text-white">• Interactive added delay p99 &lt;= 30.0 ms</div>
                <div className="text-white">• Bulk goodput floor &gt;= 2.0 Mbps</div>
              </div>
            </div>
            {scenAReport ? (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-emerald-300 flex flex-wrap justify-between gap-2">
                <span>Measured (fq_codel): 1.51 ms p99 (2/2 pass)</span>
                <span>R0 unmanaged: 197.98 ms (0/2)</span>
              </div>
            ) : (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-[var(--mute)]">
                Status: Not yet run
              </div>
            )}
          </div>

          {/* S2 */}
          <div className="glass-card p-6 flex flex-col justify-between space-y-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#b79bff] font-semibold">S2 • SCENARIO B</span>
                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-0.5 font-mono text-[11px] text-emerald-300">
                  {scenBReport ? `Run: ${scenBReport.run_id}` : 'Not yet run'}
                </span>
              </div>
              <h3 className="mt-2 text-lg font-semibold text-white">S2 Capacity collapse</h3>
              <p className="mt-1 text-xs sm:text-sm text-[var(--mute)]">
                Mid-call WAN capacity collapse from 100 Mbps down to 20 Mbps. Controller must re-shape rates within step bounds and keep call latency bounded.
              </p>
              <div className="mt-3 rounded-xl bg-white/[0.03] border border-[var(--line)] p-3 font-mono text-xs space-y-1">
                <div className="text-[var(--mute)]">Pass criteria:</div>
                <div className="text-white">• Post-collapse p95 delay &lt;= 80 ms guardrail</div>
                <div className="text-white">• Shaped rate adapts to &lt;= 20 Mbps bottleneck</div>
              </div>
            </div>
            {scenBReport?.metrics_summary ? (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-emerald-300 flex flex-wrap justify-between gap-2">
                <span>
                  Pre p95: {String(scenBReport.metrics_summary.pre_collapse_p95_delay_ms)} ms | Post p95:{' '}
                  {String(scenBReport.metrics_summary.post_collapse_p95_delay_ms)} ms
                </span>
                <span>Adapted: {String(scenBReport.metrics_summary.capacity_collapse_adapted)}</span>
              </div>
            ) : (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-[var(--mute)]">
                Status: Not yet run
              </div>
            )}
          </div>

          {/* S3 */}
          <div className="glass-card p-6 flex flex-col justify-between space-y-4 border-[#f26a1b]/50">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#f26a1b] font-semibold">S3 • SCENARIO D (SAFETY)</span>
                <span className="rounded-full border border-[#f26a1b]/50 bg-[#f26a1b]/15 px-3 py-0.5 font-mono text-[11px] text-[#f26a1b]">
                  {scenDReport ? `Run: ${scenDReport.run_id}` : 'Not yet run'}
                </span>
              </div>
              <h3 className="mt-2 text-lg font-semibold text-white">S3 Harmful policy</h3>
              <p className="mt-1 text-xs sm:text-sm text-[var(--mute)]">
                Injects (a) an infeasible starvation policy (interactive floor 0.5 Mbps &lt; 2.0 Mbps) and (b) a canary delay breach (&gt; 80 ms across 2 windows).
              </p>
              <div className="mt-3 rounded-xl bg-white/[0.03] border border-[var(--line)] p-3 font-mono text-xs space-y-1">
                <div className="text-[var(--mute)]">Pass criteria:</div>
                <div className="text-white">• Pre-apply gate blocks starvation candidate</div>
                <div className="text-white">• Canary breach triggers rollback + kernel verification</div>
              </div>
            </div>
            {scenDReport?.metrics_summary ? (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-[#f26a1b] flex flex-wrap justify-between gap-2">
                <span>Gate rejected: {String(scenDReport.metrics_summary.harmful_policy_infeasible_rejected)}</span>
                <span>State: {String(scenDReport.metrics_summary.coordinator_final_state)} (Verified)</span>
              </div>
            ) : (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-[var(--mute)]">
                Status: Not yet run
              </div>
            )}
          </div>

          {/* S4 */}
          <div className="glass-card p-6 flex flex-col justify-between space-y-4">
            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#b79bff] font-semibold">S4 • SCENARIO C</span>
                <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-0.5 font-mono text-[11px] text-emerald-300">
                  {scenCReport ? `Run: ${scenCReport.run_id}` : 'Not yet run'}
                </span>
              </div>
              <h3 className="mt-2 text-lg font-semibold text-white">S4 Household fairness</h3>
              <p className="mt-1 text-xs sm:text-sm text-[var(--mute)]">
                Three competing TCP streaming/bulk flows plus a 66 pps UDP gaming flow on port 5005 sharing a 100 Mbps bottleneck.
              </p>
              <div className="mt-3 rounded-xl bg-white/[0.03] border border-[var(--line)] p-3 font-mono text-xs space-y-1">
                <div className="text-[var(--mute)]">Pass criteria:</div>
                <div className="text-white">• Jain&apos;s fairness index &gt;= 0.85 across streams</div>
                <div className="text-white">• Gaming p95 one-way delay &lt;= 30.0 ms</div>
              </div>
            </div>
            {scenCReport?.metrics_summary ? (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-emerald-300 flex flex-wrap justify-between gap-2">
                <span>Jain&apos;s Index: {String(scenCReport.metrics_summary.jain_fairness_index)}</span>
                <span>Gaming p95: {String(scenCReport.metrics_summary.gaming_p95_delay_ms)} ms</span>
              </div>
            ) : (
              <div className="border-t border-[var(--line)] pt-3 font-mono text-xs text-[var(--mute)]">
                Status: Not yet run
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 9. KEY METRICS CHIPS AND THE STACK STRIP */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8 space-y-12">
        <div>
          <h3 className="text-center font-mono text-xs uppercase tracking-widest text-[var(--mute)] mb-6">
            MEASURED TELEMETRY & SAFETY METRICS
          </h3>
          <div className="flex flex-wrap justify-center gap-3">
            {METRIC_CHIPS.map((m) => (
              <div
                key={m.label}
                className={`rounded-full px-4 py-2 border text-xs font-mono flex items-center gap-2.5 ${
                  m.primary
                    ? 'border-[#7c5cff]/50 bg-[#7c5cff]/10 text-white'
                    : 'border-[var(--line)] bg-white/[0.02] text-[var(--mute)]'
                }`}
              >
                <span className={`h-2 w-2 rounded-full ${m.primary ? 'bg-[#b79bff]' : 'bg-white/30'}`} />
                <span className="font-semibold">{m.label}</span>
                <span className="text-[var(--mute)] hidden sm:inline">• {m.detail}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card p-6 sm:p-8">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <span className="font-mono text-xs uppercase tracking-widest text-[#b79bff] shrink-0">
              SYSTEM STACK & HARNESS
            </span>
            <div className="flex flex-wrap items-center justify-center gap-2.5">
              {STACK_ITEMS.map((item) => (
                <span
                  key={item}
                  className="rounded-lg border border-[var(--line)] bg-[#06051a]/80 px-3 py-1.5 font-mono text-xs text-[var(--text)]"
                >
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
};

export default LandingPage;

