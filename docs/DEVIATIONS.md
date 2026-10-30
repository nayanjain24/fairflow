# FairFlow Protocol Deviations & Methodological Notes

## DEV-M2-001: Baseline Phase Warmup Discard & Signed Added Delay Reporting

**Date**: 2026-10-26  
**Status**: APPROVED FOR GATE 2 REMEDIATION  
**Affects**: `src/fairflow/stats.py`, `src/fairflow/report.py`, `experiments/scenario_a.yaml` (methodological interpretation)

---

### 1. Discrepancy Description
In Milestone 2 Gate 2 smoke evaluation (`smoke_20261026_144256`), baseline arms `B2a_fq_codel` and `B2b_cake` reported an added p99 delay of `0.000 ms`, while their added p95 delay was positive (`~0.65 – 0.79 ms`).

Investigation revealed that:
1. In `src/fairflow/stats.py` line 106, the comment documented:
   `# Baseline phase: packets sent before iperf_start_t (excluding initial 0.5s warmup)`
   However, the conditional slice was implemented without a lower bound:
   `if t_send_s < iperf_start_t: baseline_records.append(r)`
   As a consequence, the initial 0.5 seconds of the call were included in the baseline sample.
2. In all trials, the first two UDP packets (indices `0` and `1`) experienced elevated one-way delay (`45.11 ms` and `25.13 ms`) caused by socket cold-start, process scheduling, and ARP resolution on newly provisioned veth interfaces.
3. In short smoke baseline phases (3.0 seconds, ~170 received packets), these two cold-start packets constituted `2 / 170 ≈ 1.18%` of the sample, inflating the baseline 99th percentile (`base_p99`) to `~21.67 ms`.
4. In the congested steady-state phase, `fq_codel` and `CAKE` isolate the sparse UDP call flow (50 pps, ~80 kbps) into an empty queue, yielding clean propagation delay of `~15.0 – 15.9 ms` (`cong_p99 ≈ 15.87 – 17.21 ms`).
5. The raw difference `cong_p99 - base_p99` was negative (`-4.50` to `-5.79 ms`).
6. `src/fairflow/stats.py` applied `max(0.0, cong_p99 - base_p99)`, which clipped negative differences to `0.000 ms`, masking the true relationship.

---

### 2. Affected Estimands
- **Primary Estimand**: `congested_added_delay_p99_ms`
  - In `smoke_20261026_144256`, reported as `0.000 ms` for B2a and B2b due to negative clamping.
  - When the 0.5s cold-start warmup is excluded, true baseline p99 drops from `21.67 ms` to `15.18 ms`, yielding a positive steady-state added delay of `~0.71 ms` for B2a (`fq_codel`) and `~2.03 ms` for B2b (`CAKE`).
- **Secondary Estimand**: `added_delay_p95_ms`
  - Largely unaffected by the first two packets (index 161/170 is far from index 0-1), but excluding the warmup ensures strict consistency across all percentile metrics.

---

### 3. Intended Methodological Correction
1. **Explicit Warmup Window Exclusion**:
   Compute `t_warmup_end = (records[0].send_time_ns / 1e9) + warmup_s` (where `warmup_s = 0.5` seconds). Include in `baseline_records` only packets where `t_warmup_end <= t_send_s < iperf_start_t`.
2. **Explicit Sample Size Guardrail**:
   Require a minimum sample count (`N >= 10`) for both baseline and congested steady-state phases. If fewer samples are available, fail trial validity with an explicit `invalid_reason` rather than returning `0.0`.
3. **Preservation of Signed Raw Differences**:
   Compute and record both:
   - `raw_added_delay_p99_ms`: Signed unclamped difference (`cong_p99 - base_p99`).
   - `raw_added_delay_p95_ms`: Signed unclamped difference (`cong_p95 - base_p95`).
   - `congested_added_delay_p99_ms`: Nonnegative contract guardrail metric `max(0.0, raw_added_delay_p99_ms)`.
   - `added_delay_p95_ms`: Nonnegative contract metric `max(0.0, raw_added_delay_p95_ms)`.

---

### 4. Limitations on Comparing Corrected vs. Uncorrected Smoke Runs
1. **Direct Comparability**:
   `smoke_20261026_144256` baseline p99 is contaminated by the cold-start transient. Its reported added p99 is artificially depressed (clamped to zero for B2a/B2b and ~5 ms lower for B1/R0). Corrected metrics cannot be numerically compared to uncorrected baseline p99 metrics without applying the warmup filter.
2. **Preservation of Artifacts**:
   `results/m2/smoke_20261026_144256/` remains completely preserved on disk for auditing. All subsequent smoke and full evaluations will write to distinct, timestamped directories and use the corrected estimator.
