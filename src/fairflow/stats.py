"""stats.py — Statistical analysis and metrics computation for FairFlow.

Provides:
- Non-parametric percentile computation (p50, p75, p95, p99).
- RFC 3550 interarrival jitter calculation.
- Pure-Python bootstrap 95% confidence intervals of the median (10,000 resamples).
- Summary statistics per arm (median, IQR, min, max, CV, bootstrap CI).
- Phase slicing based on observed monotonic timestamps.
"""

import math
import random
from typing import List, Tuple, Dict, Any, Optional
from src.fairflow.traffic import PacketRecord


def percentile(data: List[float], p: float) -> float:
    """Calculate the p-th percentile (0 <= p <= 100) using linear interpolation."""
    if not data:
        return 0.0
    sorted_d = sorted(data)
    n = len(sorted_d)
    if n == 1:
        return sorted_d[0]
    # Rank index
    k = (n - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_d[int(k)]
    d0 = sorted_d[int(f)] * (c - k)
    d1 = sorted_d[int(c)] * (k - f)
    return d0 + d1


def compute_rfc3550_jitter(records: List[PacketRecord]) -> float:
    """Calculate RFC 3550 interarrival jitter in milliseconds from packet records.

    D(i-1, i) = (R_i - S_i) - (R_{i-1} - S_{i-1})
    J_i = J_{i-1} + (|D(i-1, i)| - J_{i-1}) / 16.0
    """
    if len(records) < 2:
        return 0.0
    jitter_ms = 0.0
    prev_d_ms = records[0].one_way_delay_ms
    for r in records[1:]:
        curr_d_ms = r.one_way_delay_ms
        d_diff = abs(curr_d_ms - prev_d_ms)
        jitter_ms += (d_diff - jitter_ms) / 16.0
        prev_d_ms = curr_d_ms
    return jitter_ms


def bootstrap_median_ci(
    data: List[float],
    n_resamples: int = 10000,
    seed: int = 42,
    ci: float = 0.95,
) -> Tuple[float, float]:
    """Compute non-parametric bootstrap confidence interval for the median.

    Uses pure Python with fixed random seed for reproducible resampling.
    """
    if not data:
        return (0.0, 0.0)
    if len(data) == 1:
        return (data[0], data[0])

    rng = random.Random(seed)
    n = len(data)
    medians: List[float] = []

    for _ in range(n_resamples):
        sample = [data[rng.randint(0, n - 1)] for _ in range(n)]
        medians.append(percentile(sample, 50.0))

    alpha = (1.0 - ci) / 2.0
    lower = percentile(medians, alpha * 100.0)
    upper = percentile(medians, (1.0 - alpha) * 100.0)
    return (round(lower, 4), round(upper, 4))


def compute_trial_metrics(
    records: List[PacketRecord],
    total_call_sent: int,
    iperf_start_t: float,
    iperf_end_t: float,
    ramp_s: float = 5.0,
    warmup_s: float = 0.5,
    min_phase_samples: int = 10,
    capacity_mbps: float = 100.0,
    bulk_goodput_mbps: float = 0.0,
    max_sender_lateness_ms: float = 2.0,
    observed_p99_lateness_ms: float = 0.0,
) -> Dict[str, Any]:
    """Compute per-trial metrics partitioned by observed monotonic timestamps.
    
    Excludes the first `warmup_s` (0.5s) of the baseline phase to eliminate
    socket cold-start and ARP resolution transients. Requires at least `min_phase_samples`
    in each phase for valid statistical estimation.
    """
    if not records:
        return {
            "valid": False,
            "invalid_reason": "No packets received",
        }

    # Validity check on sender lateness
    is_valid = observed_p99_lateness_ms <= max_sender_lateness_ms
    invalid_reason = "" if is_valid else f"Sender lateness p99 ({observed_p99_lateness_ms:.2f}ms) > {max_sender_lateness_ms}ms"

    # Slice packets by observed monotonic timestamps
    # Baseline phase: packets sent between (t_call_start + warmup_s) and iperf_start_t
    # Congested steady-state phase: packets sent between (iperf_start_t + ramp_s) and iperf_end_t
    t_call_start_s = records[0].send_time_ns / 1e9
    t_baseline_start_s = t_call_start_s + warmup_s

    baseline_records: List[PacketRecord] = []
    congested_records: List[PacketRecord] = []

    for r in records:
        t_send_s = r.send_time_ns / 1e9
        if t_baseline_start_s <= t_send_s < iperf_start_t:
            baseline_records.append(r)
        elif (iperf_start_t + ramp_s) <= t_send_s <= iperf_end_t:
            congested_records.append(r)

    # Sample size guardrail: invalidate trials with insufficient baseline or congested samples
    if is_valid:
        if len(baseline_records) < min_phase_samples:
            is_valid = False
            invalid_reason = f"Insufficient baseline samples ({len(baseline_records)} < {min_phase_samples})"
        elif len(congested_records) < min_phase_samples:
            is_valid = False
            invalid_reason = f"Insufficient congested samples ({len(congested_records)} < {min_phase_samples})"

    base_delays = [r.one_way_delay_ms for r in baseline_records]
    cong_delays = [r.one_way_delay_ms for r in congested_records]

    base_p50 = percentile(base_delays, 50.0)
    base_p95 = percentile(base_delays, 95.0)
    base_p99 = percentile(base_delays, 99.0)
    base_jitter = compute_rfc3550_jitter(baseline_records)

    cong_p50 = percentile(cong_delays, 50.0)
    cong_p95 = percentile(cong_delays, 95.0)
    cong_p99 = percentile(cong_delays, 99.0)
    cong_max = max(cong_delays) if cong_delays else 0.0
    cong_jitter = compute_rfc3550_jitter(congested_records)

    # Raw signed differences (unclamped)
    raw_added_delay_p95 = cong_p95 - base_p95 if (cong_delays and base_delays) else 0.0
    raw_added_delay_p99 = cong_p99 - base_p99 if (cong_delays and base_delays) else 0.0

    # Contract-facing nonnegative metrics (clamped to 0.0)
    added_delay_p95 = max(0.0, raw_added_delay_p95)
    added_delay_p99 = max(0.0, raw_added_delay_p99)

    loss_pct = 0.0
    if total_call_sent > 0:
        loss_pct = max(0.0, (total_call_sent - len(records)) / total_call_sent * 100.0)

    goodput_fraction = bulk_goodput_mbps / capacity_mbps if capacity_mbps > 0 else 0.0

    # Contract checks
    interactive_target_met = added_delay_p99 <= 30.0
    bulk_floor_met = bulk_goodput_mbps >= 2.0

    return {
        "valid": is_valid,
        "invalid_reason": invalid_reason,
        "sender_lateness_p99_ms": round(observed_p99_lateness_ms, 3),
        "total_packets_sent": total_call_sent,
        "total_packets_received": len(records),
        "call_loss_pct": round(loss_pct, 3),
        "baseline": {
            "packet_count": len(baseline_records),
            "p50_ms": round(base_p50, 3),
            "p95_ms": round(base_p95, 3),
            "p99_ms": round(base_p99, 3),
            "jitter_ms": round(base_jitter, 3),
        },
        "congested": {
            "packet_count": len(congested_records),
            "p50_ms": round(cong_p50, 3),
            "p95_ms": round(cong_p95, 3),
            "p99_ms": round(cong_p99, 3),
            "max_ms": round(cong_max, 3),
            "jitter_ms": round(cong_jitter, 3),
        },
        "raw_added_delay_p95_ms": round(raw_added_delay_p95, 3),
        "raw_added_delay_p99_ms": round(raw_added_delay_p99, 3),
        "added_delay_p95_ms": round(added_delay_p95, 3),
        "congested_added_delay_p99_ms": round(added_delay_p99, 3),
        "bulk_goodput_mbps": round(bulk_goodput_mbps, 3),
        "bulk_goodput_fraction": round(goodput_fraction, 4),
        "interactive_target_met": interactive_target_met,
        "bulk_floor_met": bulk_floor_met,
    }


def compute_arm_summary(trial_metrics_list: List[Dict[str, Any]], seed: int = 42) -> Dict[str, Any]:
    """Compute aggregate summary across valid trials of an arm."""
    valid_trials = [t for t in trial_metrics_list if t.get("valid", True)]
    n_valid = len(valid_trials)
    n_total = len(trial_metrics_list)

    if n_valid == 0:
        return {
            "n_total": n_total,
            "n_valid": 0,
            "interactive_target_met_ratio": f"0/{n_total}",
        }

    p99_delays = [t["congested_added_delay_p99_ms"] for t in valid_trials]
    p95_delays = [t["added_delay_p95_ms"] for t in valid_trials]
    goodputs = [t["bulk_goodput_mbps"] for t in valid_trials]
    goodput_fractions = [t["bulk_goodput_fraction"] for t in valid_trials]
    losses = [t["call_loss_pct"] for t in valid_trials]

    k_target_met = sum(1 for t in valid_trials if t["interactive_target_met"])

    def _summary_series(vals: List[float]) -> Dict[str, Any]:
        med = percentile(vals, 50.0)
        p25 = percentile(vals, 25.0)
        p75 = percentile(vals, 75.0)
        iqr = p75 - p25
        mean_val = sum(vals) / len(vals)
        std_val = math.sqrt(sum((x - mean_val) ** 2 for x in vals) / len(vals)) if len(vals) > 1 else 0.0
        cv = (std_val / mean_val) if mean_val > 0 else 0.0
        ci_low, ci_high = bootstrap_median_ci(vals, seed=seed)
        return {
            "median": round(med, 3),
            "iqr": round(iqr, 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
            "mean": round(mean_val, 3),
            "cv": round(cv, 4),
            "bootstrap_ci95": [ci_low, ci_high],
        }

    return {
        "n_total": n_total,
        "n_valid": n_valid,
        "interactive_target_met": f"{k_target_met}/{n_total}",
        "primary_added_delay_p99_ms": _summary_series(p99_delays),
        "secondary_added_delay_p95_ms": _summary_series(p95_delays),
        "secondary_bulk_goodput_mbps": _summary_series(goodputs),
        "secondary_bulk_goodput_fraction": _summary_series(goodput_fractions),
        "secondary_call_loss_pct": _summary_series(losses),
    }
