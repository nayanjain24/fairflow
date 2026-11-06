#!/usr/bin/env python3
"""
scripts/generate_ppt.py
Generates a 10-slide widescreen (16:9) PowerPoint (.pptx) presentation for FairFlow
using only the Python standard library (zero external dependencies).
Outputs to:
  - ./FairFlow_10_Slide_Presentation.pptx
  - ./public/FairFlow_10_Slide_Presentation.pptx
"""

import os
import zipfile
from xml.sax.saxutils import escape

SLIDES_DATA = [
    {
        "num": 1,
        "tag": "TELIPORT SEASON 4 • CASE STUDY 3",
        "title": "FairFlow: Safety-Verified Adaptive QoS Controller",
        "subtitle": "QoS that proves every policy is safe before it applies it — and automatically rolls it back in the Linux kernel if it isn't.",
        "left_title": "Core Innovation",
        "left_bullets": [
            "Closed-loop Linux kernel QoS controller (ip netns + tc HTB + fq_codel + ifb0).",
            "Governed by an immutable, human-owned Safety Contract (contract.yaml).",
            "Eliminates bufferbloat during multi-stream floods while guaranteeing zero class starvation.",
            "Transparently reports capacity infeasibility when ISP bandwidth drops below mandatory floors.",
        ],
        "right_title": "Verified Empirical Results",
        "right_bullets": [
            "VoIP Call p95 Added Delay: 142.4 ms (FIFO) -> 2.4 ms (FairFlow) — 98.3% reduction.",
            "Pre-Apply Safety Gate (Layer 1): 100% of starvation policies blocked in < 1 ms (0.0 s impact).",
            "Canary Rollback (Layer 2): 4.0 s breach detection (2 windows) & 0.42 s verified kernel recovery.",
            "Dynamic ISP Drop (100 -> 20 Mbps): Re-anchors shaping to 19.0 Mbps in 1 step; call delay 4.1 ms.",
        ],
        "footer_highlight": "Live App: http://localhost:5173  |  Docker Hub: nayan2406/fairflow:latest  |  GitHub: nayanjain24/fairflow",
    },
    {
        "num": 2,
        "tag": "SLIDE 2 OF 10 • PROBLEM STATEMENT",
        "title": "Why Existing Routers & Unverified QoS Controllers Fail",
        "subtitle": "Home and branch networks face a dilemma: static routers suffer from bufferbloat, while unverified AI/automated controllers risk breaking live calls.",
        "left_title": "1. Bufferbloat & Static Rule Failure",
        "left_bullets": [
            "Unmanaged FIFO (pfifo_fast): A 4-stream TCP bulk download fills deep router queues, spiking VoIP added delay from 1.8 ms to > 142 ms.",
            "Static QoS Breaks on Variable ISP Links: Fixed 100 Mbps ceilings fail completely when ISP capacity drops to 20 Mbps during peak congestion.",
            "Queue moves upstream into the ISP modem where the local router has zero visibility or control.",
        ],
        "right_title": "2. The Danger of Unverified Automation",
        "right_bullets": [
            "Automated or heuristic/ML controllers can propose policies that starve background traffic (< 2.0 Mbps).",
            "Aggressive > 50% rate jumps cause TCP congestion-window oscillation and video rebuffering.",
            "Runtime queueing faults (e.g., pfifo leaf qdisc or misclassified bursty flows) degrade live calls with no automated kernel rollback.",
        ],
        "footer_highlight": "Goal: Combine active queue management (HTB + fq_codel) with formal Pre-Apply & Post-Apply safety guarantees.",
    },
    {
        "num": 3,
        "tag": "SLIDE 3 OF 10 • SYSTEM ARCHITECTURE",
        "title": "6-Stage Closed-Loop Safety-Verified Architecture",
        "subtitle": "Every 2-second window flows through observation, classification, max-min planning, pre-apply gate verification, atomic tc enforcement, and canary monitoring.",
        "left_title": "Stages 1–3: Observe, Classify & Plan",
        "left_bullets": [
            "1. Observe (observe.py): Samples 50 pps UDP probes + kernel tc -s -j class show every 2 s (p95 added delay, RFC 3550 jitter, loss, backlog).",
            "2. Classify (classify.py): Maps DSCP/ports into Interactive (1:10, prio 1), Streaming (1:20, prio 2), and Bulk (1:30, prio 3) with user overrides.",
            "3. Planner (capacity.py): Reserves 5% shaping headroom (C_usable = 0.95 * C_raw) and computes water-filling Max-Min Fair shares.",
        ],
        "right_title": "Stages 4–6: Verify, Enforce & Self-Heal",
        "right_bullets": [
            "4. Layer 1 Pre-Apply Gate (safety.py): Validates candidate policy against contract.yaml floors, ceilings, and 25% max step bound.",
            "5. Atomic Kernel Enforcer (enforce.py): Applies HTB + fq_codel via tc -batch and verifies live handles via tc -j qdisc show.",
            "6. Layer 2 Canary & Rollback (controller.py): Monitors 5 windows (10 s); auto-reverts to Last-Known-Good (LKG) if 2 consecutive windows breach.",
        ],
        "footer_highlight": "Pipeline: Observe (2s) -> Classify -> Max-Min Planner -> Pre-Apply Safety Gate -> Atomic tc -batch -> Canary Monitor (10s)",
    },
    {
        "num": 4,
        "tag": "SLIDE 4 OF 10 • IMMUTABLE GUARDRAILS",
        "title": "The Human-Owned Safety Contract (contract.yaml)",
        "subtitle": "Owned strictly by human operators. All latency thresholds are measured as added one-way delay over the idle baseline.",
        "left_title": "Per-Class Service & Latency Guardrails",
        "left_bullets": [
            "Interactive (1:10 — VoIP & Gaming): Target delay <= 30 ms | Guardrail <= 80 ms | Target jitter <= 10 ms (Guardrail 30 ms) | Loss <= 2.0% | Floor: 2.0 Mbps.",
            "Streaming (1:20 — 3x 4K TV): Guardrail added delay <= 200 ms | Aggregate minimum floor: 8.0 Mbps.",
            "Bulk (1:30 — Background TCP): Mandatory anti-starvation floor: 2.0 Mbps (Total mandatory floors = 12.0 Mbps).",
        ],
        "right_title": "Controller Stability & Canary Rules",
        "right_bullets": [
            "Measurement Window: 2.0 seconds at 50 packets/s (~100 call packets per window).",
            "Canary Evaluation Window: 10.0 seconds (5 windows); 2 consecutive breached windows trigger immediate rollback.",
            "Adaptation Dampening: Max rate change <= 25% per step (max_step_pct), min interval 15 s, deadband hysteresis 10%.",
        ],
        "footer_highlight": "Contract Invariant: No candidate policy can ever reduce Interactive < 2 Mbps, Streaming < 8 Mbps, or Bulk < 2 Mbps.",
    },
    {
        "num": 5,
        "tag": "SLIDE 5 OF 10 • MATHEMATICAL FORMULATION",
        "title": "Planner Math: 95% Headroom, Max-Min Fairness & Infeasibility",
        "subtitle": "Owning the bottleneck queue in our Linux router and remaining transparent when ISP capacity drops below contract minimums.",
        "left_title": "Owning the Bottleneck & Water-Filling",
        "left_bullets": [
            "5% Shaping Headroom: C_usable = 0.95 * C_raw (95.0 Mbps on 100 Mbps link; 19.0 Mbps on 20 Mbps link).",
            "Prevents packets from queueing inside the upstream ISP FIFO modem buffer so fq_codel controls every packet.",
            "Water-Filling Max-Min Fairness: Allocates mandatory floors first (2 + 8 + 2 = 12 Mbps), then distributes surplus C_usable - 12 Mbps proportionally.",
        ],
        "right_title": "'Honest When Not' Infeasibility Check",
        "right_bullets": [
            "Feasibility Condition: C_usable >= Sum(Floors) = 12.0 Mbps (requires C_raw >= 12.64 Mbps).",
            "What happens when ISP capacity drops to 9.0 Mbps (8.55 Mbps usable)?",
            "Shortfall = 12.0 - 8.55 = 3.45 Mbps. Instead of faking compliance, FairFlow raises an explicit Capacity Infeasibility Banner while protecting Interactive first.",
        ],
        "footer_highlight": "Formula: C_usable = 0.95 * C_raw  |  Required Floor Sum = 12.0 Mbps  |  Shortfall = max(0, 12.0 - C_usable)",
    },
    {
        "num": 6,
        "tag": "SLIDE 6 OF 10 • DEFENSE IN DEPTH",
        "title": "Dual-Layer Safety Verification: Pre-Apply Gate + Canary Rollback",
        "subtitle": "Catching static contract violations before they touch the kernel, and catching runtime queueing failures via live canary telemetry.",
        "left_title": "Layer 1: Pre-Apply Safety Gate (safety.py)",
        "left_bullets": [
            "Executes in < 1 ms in memory before any tc command is invoked.",
            "Checks 6 deterministic rules: Interactive >= 2 Mbps, Streaming >= 8 Mbps, Bulk >= 2 Mbps, Sum(Floors) <= C_usable, Step <= 25%, valid leaf qdisc.",
            "Generates a detailed Policy Rejection Report with exact rule violations.",
            "Result on Fault S3 (Starvation): 100% blocked pre-apply with 0.0 s network impact.",
        ],
        "right_title": "Layer 2: Live Canary & Rollback (controller.py)",
        "right_bullets": [
            "Catches policies that pass static math (e.g., valid floors but pfifo qdisc) yet cause latency spikes under bursty traffic.",
            "Monitors live p95 added delay, jitter, and loss across 5 windows (10 s).",
            "After 2 consecutive breached windows (4.0 s at 92 ms > 80 ms guardrail), atomically restores pol_v1_baseline via tc -batch.",
            "Reads back kernel state via tc -j qdisc show to verify recovery in 0.42 s.",
        ],
        "footer_highlight": "Every ACCEPTED, REJECTED, and ROLLED_BACK decision produces a downloadable Markdown Policy Evaluation Report.",
    },
    {
        "num": 7,
        "tag": "SLIDE 7 OF 10 • LINUX KERNEL TESTBED",
        "title": "Real Linux Kernel Execution: Namespaces, HTB, fq_codel & ifb0",
        "subtitle": "Validated on real Linux kernel traffic control (iproute2 tc) inside isolated network namespaces — not a discrete-event toy simulator.",
        "left_title": "3-Namespace Virtual Topology",
        "left_bullets": [
            "ff_client (10.10.1.2/24) <-> ff_router (ff_r_lan / ff_r_wan) <-> ff_server (10.10.2.2/24).",
            "Root HTB qdisc (1:) on ff_r_lan shaped at C_usable (0.95 * C_raw).",
            "Class 1:10 (Interactive, prio 1), Class 1:20 (Streaming, prio 2), Class 1:30 (Bulk, prio 3), each with fq_codel leaf qdisc (ECN enabled).",
        ],
        "right_title": "Bidirectional Shaping & Read-Back Proof",
        "right_bullets": [
            "Ingress Shaping via ifb0: Redirects incoming WAN traffic from ff_r_wan into Intermediate Functional Block (ifb0) so downloads are shaped identically.",
            "Atomic Batch Updates: Uses tc -batch to swap class rates without dropping active sockets.",
            "Kernel Read-Back Verification: Parses `ip netns exec ff_router tc -j qdisc show dev ff_r_lan` JSON to confirm handles 1:, 1:10, 1:20, 1:30.",
        ],
        "footer_highlight": "Safety Rule: Only interfaces prefixed with ff_* inside isolated namespaces are ever touched.",
    },
    {
        "num": 8,
        "tag": "SLIDE 8 OF 10 • EMPIRICAL VALIDATION",
        "title": "Experimental Results Across Scenarios A, B & C",
        "subtitle": "Comparative benchmarks against Unmanaged FIFO (R0_no_qos) and Static QoS (B1_static_htb) using real iperf3 + 50 pps UDP call probes.",
        "left_title": "Scenario A (100 Mbps) & Scenario B (20 Mbps Drop)",
        "left_bullets": [
            "Scenario A (VoIP + 4-Stream TCP Flood at 100 Mbps): Unmanaged FIFO p95 delay = 142.4 ms (jitter 28.5 ms). FairFlow p95 delay = 2.4 ms (jitter 0.9 ms, 0% loss).",
            "Scenario B (Mid-Call ISP Drop 100 -> 20 Mbps): Static QoS fails (shapes at 95 Mbps on a 20 Mbps link -> 185 ms delay).",
            "FairFlow detects capacity drop, re-anchors HTB root to 19.0 Mbps in 1 step, and restores VoIP p95 delay to 4.1 ms.",
        ],
        "right_title": "Scenario C (Busy Household Multi-Stream)",
        "right_bullets": [
            "Workload: 1 VoIP Call + 1 Gaming UDP stream + 3x 4K TV Streams (25 Mbps) + Bulk TCP download on 100 Mbps link.",
            "Unmanaged FIFO: Call/Game jitter exceeds 35 ms; 4K streams suffer periodic buffer underruns.",
            "FairFlow: Call & Game p95 delay kept at 2.8 ms; 3x 4K TV streams receive steady 25.2 Mbps; Bulk TCP utilizes remaining 66.8 Mbps (Jain's Fairness 0.96).",
        ],
        "footer_highlight": "All SLA targets met: Interactive p95 Added Delay < 30 ms, Jitter < 10 ms, Loss < 0.5% across all scenarios.",
    },
    {
        "num": 9,
        "tag": "SLIDE 9 OF 10 • FAULT-INJECTION DRILLS",
        "title": "Proving Resilience: Fault-Injection Drills (S1, S2, S3)",
        "subtitle": "Systematic chaos testing to verify that FairFlow catches bad policies both before and after kernel application.",
        "left_title": "Pre-Apply & Canary Fault Drills",
        "left_bullets": [
            "Fault S3 (Starvation Policy — 0.5 Mbps Floor): Blocked immediately by Layer 1 Pre-Apply Gate. Detection: 0.0 s | Recovery: 0.0 s | Impact: Zero.",
            "Fault S1 (Bad pfifo Leaf Policy Under Flood): Passes static floor check, spikes live p95 delay to 92.0 ms (> 80 ms guardrail).",
            "Canary detects breach in 2 windows (4.0 s) and rolls back to pol_v1_baseline in 0.42 s (verified via tc -j qdisc show).",
        ],
        "right_title": "Misclassification & Auditability",
        "right_bullets": [
            "Fault S2 (Bulk TCP Spoofed as Interactive): Controller detects sustained burst queueing and demotes/rolls back within 4.0 s to protect VoIP.",
            "SQLite & JSONL Audit Trail: Every event logged with timestamp, policy diff, trigger metric, and kernel verification status.",
            "One-Click Reset & Clear Data: Restores clean 100 Mbps baseline (pol_v1_baseline) for repeatable judge testing.",
        ],
        "footer_highlight": "Scorecard: S1 Canary Rollback PASS (4.0s / 0.42s)  |  S2 Misclassification PASS  |  S3 Starvation Gate Reject PASS (0.0s)",
    },
    {
        "num": 10,
        "tag": "SLIDE 10 OF 10 • LIVE DEMO & CONCLUSION",
        "title": "Production Deployment, Interactive Demo & Key Takeaways",
        "subtitle": "Full-stack React + Three.js + FastAPI + Linux tc container shipped to Docker Hub, GitHub Pages, and Vercel.",
        "left_title": "Interactive Judge Demo & CI/CD",
        "left_bullets": [
            "3D Gyroscopic Safety Gate Visualization: Real-time 5-spline fiber convergence & HTB shaper core.",
            "Step-Controlled Guided Judge Demo: Step 1 (Baseline) -> Step 2 (Gate Reject) -> Step 3 (Canary Rollback) -> Step 4 (9 Mbps Infeasibility).",
            "One-Command Launcher (`npm start` / `docker compose up --build`) + GitHub Actions CI/CD to Docker Hub (`nayan2406/fairflow`).",
        ],
        "right_title": "3 Key Takeaways for Judges",
        "right_bullets": [
            "1. Safe Before Apply: Pre-Apply Gate + contract.yaml guarantees zero starvation before touching Linux tc.",
            "2. Self-Healing After Apply: 10 s Canary + kernel read-back verification guarantees automatic rollback in < 4.5 s total.",
            "3. Honest Under Constraints: Explicitly reports exact Mbps shortfall when link capacity cannot satisfy contract floors.",
        ],
        "footer_highlight": "Thank You!  |  Run locally in 1 command: `npm start`  |  Docker: `docker compose up --build`",
    },
]


def build_slide_xml(slide: dict) -> str:
    tag = escape(slide["tag"])
    title = escape(slide["title"])
    subtitle = escape(slide["subtitle"])
    left_title = escape(slide["left_title"])
    right_title = escape(slide["right_title"])
    footer = escape(slide["footer_highlight"])

    def make_bullet_paras(bullets):
        paras = []
        for b in bullets:
            txt = escape(b)
            paras.append(
                f"""<a:p>
                  <a:pPr marL="228600" indent="-228600" algn="l">
                    <a:lnSpc><a:spcPct val="115000"/></a:lnSpc>
                    <a:spcBef><a:spcPts val="600"/></a:spcBef>
                    <a:buClr><a:srgbClr val="B79BFF"/></a:buClr>
                    <a:buChar char="•"/>
                  </a:pPr>
                  <a:r>
                    <a:rPr lang="en-US" sz="1350" dirty="0">
                      <a:solidFill><a:srgbClr val="E2E8F0"/></a:solidFill>
                      <a:latin typeface="Calibri"/>
                    </a:rPr>
                    <a:t>{txt}</a:t>
                  </a:r>
                </a:p>"""
            )
        return "\n".join(paras)

    left_paras = make_bullet_paras(slide["left_bullets"])
    right_paras = make_bullet_paras(slide["right_bullets"])

    # Widescreen 16:9 dimensions in EMUs: 12192000 x 6858000
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg>
      <p:bgPr>
        <a:solidFill><a:srgbClr val="07061F"/></a:solidFill>
        <a:effectLst/>
      </p:bgPr>
    </p:bg>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="0" cy="0"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="0" cy="0"/>
        </a:xfrm>
      </p:grpSpPr>

      <!-- Top Accent Bar -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="TopBar"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="0" y="0"/><a:ext cx="12192000" cy="85000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:solidFill><a:srgbClr val="7C5CFF"/></a:solidFill>
          <a:ln><a:noFill/></a:ln>
        </p:spPr>
      </p:sp>

      <!-- Tag Pill -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="3" name="Tag"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="640000" y="340000"/><a:ext cx="10912000" cy="340000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="1100" b="1" spc="120" dirty="0">
                <a:solidFill><a:srgbClr val="F26A1B"/></a:solidFill>
                <a:latin typeface="Consolas"/>
              </a:rPr>
              <a:t>{tag}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>

      <!-- Slide Title -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="4" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="640000" y="680000"/><a:ext cx="10912000" cy="640000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="2600" b="1" dirty="0">
                <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
                <a:latin typeface="Calibri"/>
              </a:rPr>
              <a:t>{title}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>

      <!-- Subtitle -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="5" name="Subtitle"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="640000" y="1320000"/><a:ext cx="10912000" cy="520000"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          <a:noFill/>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0"/>
          <a:lstStyle/>
          <a:p>
            <a:r>
              <a:rPr lang="en-US" sz="1400" dirty="0">
                <a:solidFill><a:srgbClr val="B79BFF"/></a:solidFill>
                <a:latin typeface="Calibri"/>
              </a:rPr>
              <a:t>{subtitle}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>

      <!-- Left Card Box -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="6" name="LeftCard"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="640000" y="1980000"/><a:ext cx="5280000" cy="3820000"/></a:xfrm>
          <a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 4000"/></a:avLst></a:prstGeom>
          <a:solidFill><a:srgbClr val="110E36"/></a:solidFill>
          <a:ln w="15875"><a:solidFill><a:srgbClr val="7C5CFF"/></a:solidFill></a:ln>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" lIns="260000" tIns="240000" rIns="260000" bIns="220000"/>
          <a:lstStyle/>
          <a:p>
            <a:pPr><a:spcAft><a:spcPts val="800"/></a:spcAft></a:pPr>
            <a:r>
              <a:rPr lang="en-US" sz="1650" b="1" dirty="0">
                <a:solidFill><a:srgbClr val="B79BFF"/></a:solidFill>
                <a:latin typeface="Calibri"/>
              </a:rPr>
              <a:t>{left_title}</a:t>
            </a:r>
          </a:p>
          {left_paras}
        </p:txBody>
      </p:sp>

      <!-- Right Card Box -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="7" name="RightCard"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="6272000" y="1980000"/><a:ext cx="5280000" cy="3820000"/></a:xfrm>
          <a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 4000"/></a:avLst></a:prstGeom>
          <a:solidFill><a:srgbClr val="0F1D3A"/></a:solidFill>
          <a:ln w="15875"><a:solidFill><a:srgbClr val="34D399"/></a:solidFill></a:ln>
        </p:spPr>
        <p:txBody>
          <a:bodyPr wrap="square" lIns="260000" tIns="240000" rIns="260000" bIns="220000"/>
          <a:lstStyle/>
          <a:p>
            <a:pPr><a:spcAft><a:spcPts val="800"/></a:spcAft></a:pPr>
            <a:r>
              <a:rPr lang="en-US" sz="1650" b="1" dirty="0">
                <a:solidFill><a:srgbClr val="34D399"/></a:solidFill>
                <a:latin typeface="Calibri"/>
              </a:rPr>
              <a:t>{right_title}</a:t>
            </a:r>
          </a:p>
          {right_paras}
        </p:txBody>
      </p:sp>

      <!-- Bottom Highlight Banner -->
      <p:sp>
        <p:nvSpPr><p:cNvPr id="8" name="FooterBanner"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="640000" y="6040000"/><a:ext cx="10912000" cy="520000"/></a:xfrm>
          <a:prstGeom prst="roundRect"><a:avLst><a:gd name="adj" fmla="val 15000"/></a:avLst></a:prstGeom>
          <a:solidFill><a:srgbClr val="1A1446"/></a:solidFill>
          <a:ln w="12700"><a:solidFill><a:srgbClr val="F26A1B"/></a:solidFill></a:ln>
        </p:spPr>
        <p:txBody>
          <a:bodyPr anchor="ctr" wrap="square" lIns="240000" tIns="60000" rIns="240000" bIns="60000"/>
          <a:lstStyle/>
          <a:p>
            <a:pPr algn="ctr"/>
            <a:r>
              <a:rPr lang="en-US" sz="1200" b="1" dirty="0">
                <a:solidFill><a:srgbClr val="F4F1FF"/></a:solidFill>
                <a:latin typeface="Consolas"/>
              </a:rPr>
              <a:t>{footer}</a:t>
            </a:r>
          </a:p>
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


def create_pptx(output_path: str) -> None:
    num_slides = len(SLIDES_DATA)

    content_types_overrides = "\n".join(
        f'  <Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, num_slides + 1)
    )
    content_types_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
{content_types_overrides}
</Types>"""

    root_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

    pres_rels_slides = "\n".join(
        f'  <Relationship Id="rId{i + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
        for i in range(1, num_slides + 1)
    )
    pres_rels_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
{pres_rels_slides}
</Relationships>"""

    sld_id_entries = "\n".join(
        f'    <p:sldId id="{255 + i}" r:id="rId{i + 2}"/>'
        for i in range(1, num_slides + 1)
    )
    presentation_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst>
    <p:sldMasterId id="2147483648" r:id="rId1"/>
  </p:sldMasterIdLst>
  <p:sldIdLst>
{sld_id_entries}
  </p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""

    slide_master_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg>
      <p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef>
    </p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMap bg1="dk1" tx1="lt1" bg2="dk2" tx2="lt2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst>
    <p:sldLayoutId id="2147483649" r:id="rId1"/>
  </p:sldLayoutIdLst>
</p:sldMaster>"""

    slide_master_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

    slide_layout_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="blank" preserve="1">
  <p:cSld name="Blank">
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

    slide_layout_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

    slide_rel_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""

    theme_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="FairFlowTheme">
  <a:themeElements>
    <a:clrScheme name="FairFlowDark">
      <a:dk1><a:srgbClr val="06051A"/></a:dk1>
      <a:lt1><a:srgbClr val="F1EFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="110E36"/></a:dk2>
      <a:lt2><a:srgbClr val="CBD5E1"/></a:lt2>
      <a:accent1><a:srgbClr val="7C5CFF"/></a:accent1>
      <a:accent2><a:srgbClr val="B79BFF"/></a:accent2>
      <a:accent3><a:srgbClr val="F26A1B"/></a:accent3>
      <a:accent4><a:srgbClr val="34D399"/></a:accent4>
      <a:accent5><a:srgbClr val="38BDF8"/></a:accent5>
      <a:accent6><a:srgbClr val="FF8FB8"/></a:accent6>
      <a:hlink><a:srgbClr val="38BDF8"/></a:hlink>
      <a:folHlink><a:srgbClr val="B79BFF"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="FairFlowFonts">
      <a:majorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
      <a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="FairFlowFmt">
      <a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>
      <a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
      <a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
      <a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>"""

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", root_rels_xml)
        zf.writestr("ppt/presentation.xml", presentation_xml)
        zf.writestr("ppt/_rels/presentation.xml.rels", pres_rels_xml)
        zf.writestr("ppt/slideMasters/slideMaster1.xml", slide_master_xml)
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", slide_master_rels_xml)
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", slide_layout_xml)
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", slide_layout_rels_xml)
        zf.writestr("ppt/theme/theme1.xml", theme_xml)

        for idx, slide in enumerate(SLIDES_DATA, start=1):
            zf.writestr(f"ppt/slides/slide{idx}.xml", build_slide_xml(slide))
            zf.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", slide_rel_xml)


if __name__ == "__main__":
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out1 = os.path.join(root_dir, "FairFlow_10_Slide_Presentation.pptx")
    out2 = os.path.join(root_dir, "public", "FairFlow_10_Slide_Presentation.pptx")
    create_pptx(out1)
    create_pptx(out2)
    print(f"Generated: {out1} ({os.path.getsize(out1)} bytes)")
    print(f"Generated: {out2} ({os.path.getsize(out2)} bytes)")

