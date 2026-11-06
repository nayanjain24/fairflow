import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Maximize2,
  Minimize2,
  Presentation,
  Printer,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

interface SlideItem {
  num: number;
  tag: string;
  title: string;
  subtitle: string;
  leftTitle: string;
  leftBullets: string[];
  rightTitle: string;
  rightBullets: string[];
  footerHighlight: string;
  speakerNote: string;
}

const DECK_SLIDES: SlideItem[] = [
  {
    num: 1,
    tag: 'SLIDE 1 OF 10 • TELIPORT SEASON 4 (CASE STUDY 3)',
    title: 'FairFlow: Safety-Verified Adaptive QoS Controller',
    subtitle:
      "QoS that proves every policy is safe before it applies it — and automatically rolls it back in the Linux kernel if it isn't.",
    leftTitle: 'Core Engineering Innovation',
    leftBullets: [
      'Closed-loop Linux kernel QoS controller (ip netns + tc HTB + fq_codel + ifb0).',
      'Governed by an immutable, human-owned Safety Contract (contract.yaml).',
      'Eliminates bufferbloat during multi-stream floods while guaranteeing zero class starvation.',
      'Transparently reports capacity infeasibility when ISP bandwidth drops below mandatory floors.',
    ],
    rightTitle: 'Verified Empirical Results',
    rightBullets: [
      'VoIP Call p95 Added Delay: 142.4 ms (FIFO) → 2.4 ms (FairFlow) — 98.3% reduction.',
      'Pre-Apply Safety Gate (Layer 1): 100% of starvation policies blocked in < 1 ms (0.0 s impact).',
      'Canary Rollback (Layer 2): 4.0 s breach detection (2 windows) & 0.42 s verified kernel recovery.',
      'Dynamic ISP Drop (100 → 20 Mbps): Re-anchors shaping to 19.0 Mbps in 1 step; call delay 4.1 ms.',
    ],
    footerHighlight:
      'One-Command Run: npm start  |  Docker Hub: nayan2406/fairflow:latest  |  GitHub: nayanjain24/fairflow',
    speakerNote:
      'Introduce FairFlow as a dual-verified Linux kernel QoS controller that solves both router bufferbloat and the danger of unverified automated/AI rate changes.',
  },
  {
    num: 2,
    tag: 'SLIDE 2 OF 10 • PROBLEM STATEMENT',
    title: 'Why Existing Routers & Unverified QoS Controllers Fail',
    subtitle:
      'Home and branch networks face a dilemma: static routers suffer from bufferbloat, while unverified automated controllers risk breaking live calls.',
    leftTitle: '1. Bufferbloat & Static Rule Failure',
    leftBullets: [
      'Unmanaged FIFO (pfifo_fast): A 4-stream TCP bulk download fills deep router queues, spiking VoIP added delay from 1.8 ms to > 142 ms.',
      'Static QoS Breaks on Variable ISP Links: Fixed 100 Mbps ceilings fail when ISP capacity drops to 20 Mbps during peak hours.',
      'Queue moves upstream into the ISP modem where the local router has zero visibility or control.',
    ],
    rightTitle: '2. The Danger of Unverified Automation',
    rightBullets: [
      'Automated or heuristic/ML controllers can propose policies that starve background traffic (< 2.0 Mbps).',
      'Aggressive > 50% rate jumps cause TCP congestion-window oscillation and video rebuffering.',
      'Runtime queueing faults (pfifo leaf qdisc or misclassified bursty flows) degrade live calls with no automated kernel rollback.',
    ],
    footerHighlight:
      'Design Goal: Combine active queue management (HTB + fq_codel) with formal Pre-Apply & Post-Apply safety guarantees.',
    speakerNote:
      'Emphasize why static QoS fails when ISP capacity fluctuates and why an automated controller without a safety gate and canary rollback cannot be trusted on production links.',
  },
  {
    num: 3,
    tag: 'SLIDE 3 OF 10 • SYSTEM ARCHITECTURE',
    title: '6-Stage Closed-Loop Safety-Verified Architecture',
    subtitle:
      'Every 2-second window flows through observation, classification, max-min planning, pre-apply gate verification, atomic tc enforcement, and canary monitoring.',
    leftTitle: 'Stages 1–3: Observe, Classify & Plan',
    leftBullets: [
      '1. Observe (observe.py): Samples 50 pps UDP probes + kernel tc -s -j class show every 2 s (p95 added delay, RFC 3550 jitter, loss, backlog).',
      '2. Classify (classify.py): Maps DSCP/ports into Interactive (1:10, prio 1), Streaming (1:20, prio 2), and Bulk (1:30, prio 3) with user overrides.',
      '3. Planner (capacity.py): Reserves 5% shaping headroom (C_usable = 0.95 × C_raw) and computes water-filling Max-Min Fair shares.',
    ],
    rightTitle: 'Stages 4–6: Verify, Enforce & Self-Heal',
    rightBullets: [
      '4. Layer 1 Pre-Apply Gate (safety.py): Validates candidate policy against contract.yaml floors, ceilings, and 25% max step bound.',
      '5. Atomic Kernel Enforcer (enforce.py): Applies HTB + fq_codel via tc -batch and verifies live handles via tc -j qdisc show.',
      '6. Layer 2 Canary & Rollback (controller.py): Monitors 5 windows (10 s); auto-reverts to Last-Known-Good (LKG) if 2 consecutive windows breach.',
    ],
    footerHighlight:
      'Pipeline: Observe (2s) → Classify → Max-Min Planner → Pre-Apply Safety Gate → Atomic tc -batch → Canary Monitor (10s)',
    speakerNote:
      'Walk through the 6 modules in src/fairflow/: observe.py, classify.py, capacity.py, safety.py, enforce.py, and controller.py.',
  },
  {
    num: 4,
    tag: 'SLIDE 4 OF 10 • IMMUTABLE GUARDRAILS',
    title: 'The Human-Owned Safety Contract (contract.yaml)',
    subtitle:
      'Owned strictly by human operators. All latency thresholds are measured as added one-way delay over the idle baseline.',
    leftTitle: 'Per-Class Service & Latency Guardrails',
    leftBullets: [
      'Interactive (1:10 — VoIP & Gaming): Target delay ≤ 30 ms | Guardrail ≤ 80 ms | Target jitter ≤ 10 ms (Guardrail 30 ms) | Loss ≤ 2.0% | Floor: 2.0 Mbps.',
      'Streaming (1:20 — 3× 4K TV): Guardrail added delay ≤ 200 ms | Aggregate minimum floor: 8.0 Mbps.',
      'Bulk (1:30 — Background TCP): Mandatory anti-starvation floor: 2.0 Mbps (Total mandatory floors = 12.0 Mbps).',
    ],
    rightTitle: 'Controller Stability & Canary Rules',
    rightBullets: [
      'Measurement Window: 2.0 seconds at 50 packets/s (~100 call packets per window).',
      'Canary Evaluation Window: 10.0 seconds (5 windows); 2 consecutive breached windows trigger immediate rollback.',
      'Adaptation Dampening: Max rate change ≤ 25% per step (max_step_pct), min interval 15 s, deadband hysteresis 10%.',
    ],
    footerHighlight:
      'Contract Invariant: No candidate policy can ever reduce Interactive < 2 Mbps, Streaming < 8 Mbps, or Bulk < 2 Mbps.',
    speakerNote:
      'Point out that measuring ADDED delay over idle baseline makes contract.yaml portable across any physical link RTT.',
  },
  {
    num: 5,
    tag: 'SLIDE 5 OF 10 • MATHEMATICAL FORMULATION',
    title: 'Planner Math: 95% Headroom, Max-Min Fairness & Infeasibility',
    subtitle:
      'Owning the bottleneck queue in our Linux router and remaining transparent when ISP capacity drops below contract minimums.',
    leftTitle: 'Owning the Bottleneck & Water-Filling',
    leftBullets: [
      '5% Shaping Headroom: C_usable = 0.95 × C_raw (95.0 Mbps on 100 Mbps link; 19.0 Mbps on 20 Mbps link).',
      'Prevents packets from queueing inside the upstream ISP FIFO modem buffer so fq_codel controls every packet.',
      'Water-Filling Max-Min Fairness: Allocates mandatory floors first (2 + 8 + 2 = 12 Mbps), then distributes surplus C_usable − 12 Mbps proportionally.',
    ],
    rightTitle: '"Honest When Not" Infeasibility Check',
    rightBullets: [
      'Feasibility Condition: C_usable ≥ Sum(Floors) = 12.0 Mbps (requires C_raw ≥ 12.64 Mbps).',
      'What happens when ISP capacity drops to 9.0 Mbps (8.55 Mbps usable)?',
      'Shortfall = 12.0 − 8.55 = 3.45 Mbps. Instead of faking compliance, FairFlow raises an explicit Capacity Infeasibility Banner while protecting Interactive first.',
    ],
    footerHighlight:
      'Formula: C_usable = 0.95 × C_raw  |  Required Floor Sum = 12.0 Mbps  |  Shortfall = max(0, 12.0 − C_usable)',
    speakerNote:
      'Judges love the 5% headroom explanation and the Honest Infeasibility Shortfall Banner when link capacity drops to 9 Mbps.',
  },
  {
    num: 6,
    tag: 'SLIDE 6 OF 10 • DEFENSE IN DEPTH',
    title: 'Dual-Layer Safety Verification: Pre-Apply Gate + Canary Rollback',
    subtitle:
      'Catching static contract violations before they touch the kernel, and catching runtime queueing failures via live canary telemetry.',
    leftTitle: 'Layer 1: Pre-Apply Safety Gate (safety.py)',
    leftBullets: [
      'Executes in < 1 ms in memory before any tc command is invoked.',
      'Checks 6 deterministic rules: Interactive ≥ 2 Mbps, Streaming ≥ 8 Mbps, Bulk ≥ 2 Mbps, Sum(Floors) ≤ C_usable, Step ≤ 25%, valid leaf qdisc.',
      'Generates a detailed Policy Rejection Report with exact rule violations.',
      'Result on Fault S3 (Starvation): 100% blocked pre-apply with 0.0 s network impact.',
    ],
    rightTitle: 'Layer 2: Live Canary & Rollback (controller.py)',
    rightBullets: [
      'Catches policies that pass static math (e.g., valid floors but pfifo qdisc) yet cause latency spikes under bursty traffic.',
      'Monitors live p95 added delay, jitter, and loss across 5 windows (10 s).',
      'After 2 consecutive breached windows (4.0 s at 92 ms > 80 ms guardrail), atomically restores pol_v1_baseline via tc -batch.',
      'Reads back kernel state via tc -j qdisc show to verify recovery in 0.42 s.',
    ],
    footerHighlight:
      'Every ACCEPTED, REJECTED, and ROLLED_BACK decision produces a downloadable Markdown Policy Evaluation Report.',
    speakerNote:
      'Contrast Layer 1 (prevents known bad math in 0.0 s) with Layer 2 (heals unexpected runtime latency spikes in 4.0 s).',
  },
  {
    num: 7,
    tag: 'SLIDE 7 OF 10 • LINUX KERNEL TESTBED',
    title: 'Real Linux Kernel Execution: Namespaces, HTB, fq_codel & ifb0',
    subtitle:
      'Validated on real Linux kernel traffic control (iproute2 tc) inside isolated network namespaces — not a discrete-event toy simulator.',
    leftTitle: '3-Namespace Virtual Topology',
    leftBullets: [
      'ff_client (10.10.1.2/24) ↔ ff_router (ff_r_lan / ff_r_wan) ↔ ff_server (10.10.2.2/24).',
      'Root HTB qdisc (1:) on ff_r_lan shaped at C_usable (0.95 × C_raw).',
      'Class 1:10 (Interactive, prio 1), Class 1:20 (Streaming, prio 2), Class 1:30 (Bulk, prio 3), each with fq_codel leaf qdisc (ECN enabled).',
    ],
    rightTitle: 'Bidirectional Shaping & Read-Back Proof',
    rightBullets: [
      'Ingress Shaping via ifb0: Redirects incoming WAN traffic from ff_r_wan into Intermediate Functional Block (ifb0) so downloads are shaped identically.',
      'Atomic Batch Updates: Uses tc -batch to swap class rates without dropping active sockets.',
      'Kernel Read-Back Verification: Parses `ip netns exec ff_router tc -j qdisc show dev ff_r_lan` JSON to confirm handles 1:, 1:10, 1:20, 1:30.',
    ],
    footerHighlight:
      'Safety Rule: Only interfaces prefixed with ff_* inside isolated namespaces are ever touched.',
    speakerNote:
      'Explain how ifb0 lets Linux tc shape incoming WAN downloads and how tc -j qdisc show proves the rules are active in the kernel.',
  },
  {
    num: 8,
    tag: 'SLIDE 8 OF 10 • EMPIRICAL VALIDATION',
    title: 'Experimental Results Across Scenarios A, B & C',
    subtitle:
      'Comparative benchmarks against Unmanaged FIFO (R0_no_qos) and Static QoS (B1_static_htb) using real iperf3 + 50 pps UDP call probes.',
    leftTitle: 'Scenario A (100 Mbps) & Scenario B (20 Mbps Drop)',
    leftBullets: [
      'Scenario A (VoIP + 4-Stream TCP Flood at 100 Mbps): Unmanaged FIFO p95 delay = 142.4 ms (jitter 28.5 ms). FairFlow p95 delay = 2.4 ms (jitter 0.9 ms, 0% loss).',
      'Scenario B (Mid-Call ISP Drop 100 → 20 Mbps): Static QoS fails (shapes at 95 Mbps on a 20 Mbps link → 185 ms delay).',
      'FairFlow detects capacity drop, re-anchors HTB root to 19.0 Mbps in 1 step, and restores VoIP p95 delay to 4.1 ms.',
    ],
    rightTitle: 'Scenario C (Busy Household Multi-Stream)',
    rightBullets: [
      'Workload: 1 VoIP Call + 1 Gaming UDP stream + 3× 4K TV Streams (25 Mbps) + Bulk TCP download on 100 Mbps link.',
      'Unmanaged FIFO: Call/Game jitter exceeds 35 ms; 4K streams suffer periodic buffer underruns.',
      "FairFlow: Call & Game p95 delay kept at 2.8 ms; 3× 4K TV streams receive steady 25.2 Mbps; Bulk TCP utilizes remaining 66.8 Mbps (Jain's Fairness 0.96).",
    ],
    footerHighlight:
      'All SLA targets met: Interactive p95 Added Delay < 30 ms, Jitter < 10 ms, Loss < 0.5% across all scenarios.',
    speakerNote:
      'Highlight Scenario B: static QoS completely breaks when ISP speed drops from 100 to 20 Mbps, whereas FairFlow adapts to 19.0 Mbps and keeps delay at 4.1 ms.',
  },
  {
    num: 9,
    tag: 'SLIDE 9 OF 10 • FAULT-INJECTION DRILLS',
    title: 'Proving Resilience: Fault-Injection Drills (S1, S2, S3)',
    subtitle:
      'Systematic chaos testing to verify that FairFlow catches bad policies both before and after kernel application.',
    leftTitle: 'Pre-Apply & Canary Fault Drills',
    leftBullets: [
      'Fault S3 (Starvation Policy — 0.5 Mbps Floor): Blocked immediately by Layer 1 Pre-Apply Gate. Detection: 0.0 s | Recovery: 0.0 s | Impact: Zero.',
      'Fault S1 (Bad pfifo Leaf Policy Under Flood): Passes static floor check, spikes live p95 delay to 92.0 ms (> 80 ms guardrail).',
      'Canary detects breach in 2 windows (4.0 s) and rolls back to pol_v1_baseline in 0.42 s (verified via tc -j qdisc show).',
    ],
    rightTitle: 'Misclassification & Auditability',
    rightBullets: [
      'Fault S2 (Bulk TCP Spoofed as Interactive): Controller detects sustained burst queueing and demotes/rolls back within 4.0 s to protect VoIP.',
      'SQLite & JSONL Audit Trail: Every event logged with timestamp, policy diff, trigger metric, and kernel verification status.',
      'One-Click Reset & Clear Data: Restores clean 100 Mbps baseline (pol_v1_baseline) for repeatable judge testing.',
    ],
    footerHighlight:
      'Scorecard: S1 Canary Rollback PASS (4.0s / 0.42s)  |  S2 Misclassification PASS  |  S3 Starvation Gate Reject PASS (0.0s)',
    speakerNote:
      'Show that all three fault injection drills (S1, S2, S3) are reproducible on demand in the Scenario Lab and Guided Judge Demo.',
  },
  {
    num: 10,
    tag: 'SLIDE 10 OF 10 • LIVE DEMO & CONCLUSION',
    title: 'Production Deployment, Interactive Demo & Key Takeaways',
    subtitle:
      'Full-stack React + Three.js + FastAPI + Linux tc container shipped to Docker Hub, GitHub Pages, and Vercel.',
    leftTitle: 'Interactive Judge Demo & CI/CD',
    leftBullets: [
      '3D Gyroscopic Safety Gate Visualization: Real-time 5-spline fiber convergence & HTB shaper core.',
      'Step-Controlled Guided Judge Demo: Step 1 (Baseline) → Step 2 (Gate Reject) → Step 3 (Canary Rollback) → Step 4 (9 Mbps Infeasibility).',
      'One-Command Launcher (`npm start` / `docker compose up --build`) + GitHub Actions CI/CD to Docker Hub (`nayan2406/fairflow`).',
    ],
    rightTitle: '3 Key Takeaways for Judges',
    rightBullets: [
      '1. Safe Before Apply: Pre-Apply Gate + contract.yaml guarantees zero starvation before touching Linux tc.',
      '2. Self-Healing After Apply: 10 s Canary + kernel read-back verification guarantees automatic rollback in < 4.5 s total.',
      '3. Honest Under Constraints: Explicitly reports exact Mbps shortfall when link capacity cannot satisfy contract floors.',
    ],
    footerHighlight:
      'Thank You!  |  Run locally in 1 command: `npm start`  |  Live Demo: /dashboard',
    speakerNote:
      'Conclude by jumping directly to /dashboard and stepping through the 4-step Guided Judge Demo.',
  },
];

export const SlidesPage: React.FC = () => {
  const [currentIdx, setCurrentIdx] = useState<number>(0);
  const [showNotes, setShowNotes] = useState<boolean>(true);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);

  const slide = DECK_SLIDES[currentIdx];

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {
        e.preventDefault();
        setCurrentIdx((prev) => Math.min(DECK_SLIDES.length - 1, prev + 1));
      } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault();
        setCurrentIdx((prev) => Math.max(0, prev - 1));
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen?.();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.();
      setIsFullscreen(false);
    }
  };

  const pptxHref = `${import.meta.env.BASE_URL}FairFlow_10_Slide_Presentation.pptx`;

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
      {/* Header & Download Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 no-print">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-[#7c5cff]/50 bg-[#7c5cff]/10 px-3.5 py-1 font-mono text-xs text-[#b79bff] mb-2">
            <Presentation className="h-3.5 w-3.5" />
            <span>10-SLIDE JUDGE PRESENTATION DECK (USE ← / → ARROW KEYS)</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-light text-white">
            <strong className="font-semibold">FairFlow</strong> 10-Slide Presentation Deck
          </h1>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <a
            href={pptxHref}
            download="FairFlow_10_Slide_Presentation.pptx"
            className="btn-primary !py-2 !px-4 !text-xs font-mono flex items-center gap-2"
          >
            <Download className="h-3.5 w-3.5" />
            <span>Download .pptx (PowerPoint)</span>
          </a>
          <button
            type="button"
            onClick={() => window.print()}
            className="btn-secondary !py-2 !px-4 !text-xs font-mono flex items-center gap-2"
          >
            <Printer className="h-3.5 w-3.5" />
            <span>Print / Save PDF</span>
          </button>
          <button
            type="button"
            onClick={toggleFullscreen}
            className="rounded-full border border-white/15 bg-white/5 hover:bg-white/10 px-3.5 py-2 font-mono text-xs text-white flex items-center gap-1.5 transition-colors"
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            <span>{isFullscreen ? 'Exit Fullscreen' : 'Present Fullscreen'}</span>
          </button>
        </div>
      </div>

      {/* Slide Number Selector Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-[#0b0924]/90 p-3 no-print">
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
          {DECK_SLIDES.map((s, idx) => (
            <button
              key={s.num}
              type="button"
              onClick={() => setCurrentIdx(idx)}
              className={`h-8 w-8 rounded-full font-bold transition-all cursor-pointer ${
                idx === currentIdx
                  ? 'bg-[#f26a1b] text-white shadow-[0_0_12px_rgba(242,106,27,0.5)] scale-105'
                  : 'bg-white/5 text-[var(--mute)] hover:bg-white/15 hover:text-white'
              }`}
              title={`Slide ${s.num}: ${s.title}`}
            >
              {s.num}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2 font-mono text-xs">
          <button
            type="button"
            disabled={currentIdx === 0}
            onClick={() => setCurrentIdx((p) => Math.max(0, p - 1))}
            className="rounded-full border border-white/15 bg-white/5 hover:bg-white/15 disabled:opacity-40 px-3.5 py-1.5 text-white flex items-center gap-1"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Prev
          </button>
          <span className="text-[var(--mute)] px-2">
            {currentIdx + 1} / {DECK_SLIDES.length}
          </span>
          <button
            type="button"
            disabled={currentIdx === DECK_SLIDES.length - 1}
            onClick={() => setCurrentIdx((p) => Math.min(DECK_SLIDES.length - 1, p + 1))}
            className="rounded-full border border-[#7c5cff] bg-[#7c5cff] hover:bg-[#6a48f5] disabled:opacity-40 px-3.5 py-1.5 text-white font-semibold flex items-center gap-1"
          >
            Next <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Active 16:9 Widescreen Slide Stage */}
      <article className="relative overflow-hidden rounded-glass border-2 border-[#7c5cff]/50 bg-gradient-to-br from-[#0d092b] via-[#07061f] to-[#0a1936] p-6 sm:p-10 shadow-purple-glow min-h-[520px] flex flex-col justify-between">
        {/* Top Accent Strip */}
        <div className="absolute inset-x-0 top-0 h-1.5 bg-gradient-to-r from-[#7c5cff] via-[#f26a1b] to-emerald-400" />

        {/* Slide Header */}
        <div className="space-y-2.5">
          <div className="inline-flex items-center gap-2 font-mono text-xs font-bold tracking-wider text-[#f26a1b] uppercase">
            <ShieldCheck className="h-4 w-4" />
            <span>{slide.tag}</span>
          </div>
          <h2 className="text-2xl sm:text-4xl font-semibold text-white tracking-tight">
            {slide.title}
          </h2>
          <p className="text-sm sm:text-base text-[#b79bff] max-w-4xl leading-relaxed">
            {slide.subtitle}
          </p>
        </div>

        {/* Two-Column Content Cards */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 my-6">
          <div className="rounded-2xl border border-[#7c5cff]/40 bg-[#110e36]/80 p-6 space-y-3.5">
            <h3 className="text-base sm:text-lg font-semibold text-[#b79bff] flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[#7c5cff]" />
              {slide.leftTitle}
            </h3>
            <ul className="space-y-2.5 text-xs sm:text-sm text-[#e2e8f0] leading-relaxed">
              {slide.leftBullets.map((b, i) => (
                <li key={i} className="flex items-start gap-2.5">
                  <span className="text-[#b79bff] font-bold mt-0.5">•</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl border border-emerald-500/40 bg-[#0f1d3a]/80 p-6 space-y-3.5">
            <h3 className="text-base sm:text-lg font-semibold text-emerald-300 flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
              {slide.rightTitle}
            </h3>
            <ul className="space-y-2.5 text-xs sm:text-sm text-[#e2e8f0] leading-relaxed">
              {slide.rightBullets.map((b, i) => (
                <li key={i} className="flex items-start gap-2.5">
                  <span className="text-emerald-400 font-bold mt-0.5">•</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Bottom Highlight Banner */}
        <div className="rounded-xl border border-[#f26a1b]/50 bg-[#1a1446]/90 px-4 py-3 text-center font-mono text-xs sm:text-sm text-[#f4f1ff] flex flex-wrap items-center justify-between gap-2">
          <span className="mx-auto">{slide.footerHighlight}</span>
          {slide.num === 10 && (
            <Link
              to="/dashboard"
              className="inline-flex items-center gap-1.5 rounded-full bg-[#f26a1b] px-3.5 py-1 text-xs font-semibold text-white hover:bg-[#ff7b2e] no-print"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>Launch Live Judge Demo</span>
              <ExternalLink className="h-3 w-3" />
            </Link>
          )}
        </div>
      </article>

      {/* Presenter Speaker Notes Box */}
      <div className="rounded-2xl border border-white/10 bg-[#0b0924]/80 p-4 no-print">
        <div className="flex items-center justify-between">
          <span className="font-mono text-xs font-semibold text-[#b79bff] uppercase">
            Presenter Speaker Note (Slide {slide.num})
          </span>
          <button
            type="button"
            onClick={() => setShowNotes(!showNotes)}
            className="text-xs font-mono text-[var(--mute)] hover:text-white"
          >
            {showNotes ? 'Hide note' : 'Show note'}
          </button>
        </div>
        {showNotes && (
          <p className="mt-2 text-xs sm:text-sm text-[#cbd5e1] leading-relaxed">
            🎙️ <em>“{slide.speakerNote}”</em>
          </p>
        )}
      </div>
    </main>
  );
};

export default SlidesPage;

