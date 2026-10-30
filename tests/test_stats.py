"""Unit tests for src/fairflow/stats.py."""

import pytest
from src.fairflow.traffic import PacketRecord
from src.fairflow.stats import (
    percentile,
    compute_rfc3550_jitter,
    bootstrap_median_ci,
    compute_trial_metrics,
    compute_arm_summary,
)


def test_percentile_calculation() -> None:
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(data, 0.0) == 1.0
    assert percentile(data, 50.0) == 3.0
    assert percentile(data, 100.0) == 5.0
    assert percentile([], 50.0) == 0.0
    assert percentile([42.0], 50.0) == 42.0


def test_rfc3550_jitter_calculation() -> None:
    # 0 jitter when all packets have identical delay
    records_constant = [
        PacketRecord(seq=i, send_time_ns=int(i * 20e6), recv_time_ns=int(i * 20e6 + 15e6))
        for i in range(10)
    ]
    assert compute_rfc3550_jitter(records_constant) == 0.0

    # Alternating delay produces positive RFC 3550 jitter
    records_jittery = [
        PacketRecord(seq=i, send_time_ns=int(i * 20e6), recv_time_ns=int(i * 20e6 + (15 if i % 2 == 0 else 35) * 1e6))
        for i in range(20)
    ]
    j = compute_rfc3550_jitter(records_jittery)
    assert j > 0.0
    assert j < 25.0


def test_bootstrap_median_ci_reproducible() -> None:
    data = [10.0, 12.0, 11.0, 14.0, 13.0, 12.5, 11.5, 15.0]
    ci1 = bootstrap_median_ci(data, n_resamples=1000, seed=42)
    ci2 = bootstrap_median_ci(data, n_resamples=1000, seed=42)
    assert ci1 == ci2
    assert ci1[0] <= percentile(data, 50.0) <= ci1[1]


def test_compute_trial_metrics_and_invalidation() -> None:
    # Valid trial with min_phase_samples=1
    records = [
        PacketRecord(seq=0, send_time_ns=int(1.0 * 1e9), recv_time_ns=int(1.015 * 1e9)),  # warmup
        PacketRecord(seq=1, send_time_ns=int(1.6 * 1e9), recv_time_ns=int(1.615 * 1e9)),  # baseline: 15ms
        PacketRecord(seq=2, send_time_ns=int(7.0 * 1e9), recv_time_ns=int(7.025 * 1e9)),  # congested: 25ms
    ]
    m_valid = compute_trial_metrics(
        records=records,
        total_call_sent=3,
        iperf_start_t=2.0,
        iperf_end_t=8.0,
        ramp_s=2.0,
        warmup_s=0.5,
        min_phase_samples=1,
        capacity_mbps=100.0,
        bulk_goodput_mbps=95.0,
        max_sender_lateness_ms=2.0,
        observed_p99_lateness_ms=0.5,
    )
    assert m_valid["valid"] is True
    assert m_valid["interactive_target_met"] is True
    assert m_valid["bulk_floor_met"] is True
    assert m_valid["baseline"]["packet_count"] == 1
    assert m_valid["congested"]["packet_count"] == 1
    assert m_valid["raw_added_delay_p99_ms"] == 10.0
    assert m_valid["congested_added_delay_p99_ms"] == 10.0

    # Invalid trial due to lateness
    m_invalid = compute_trial_metrics(
        records=records,
        total_call_sent=3,
        iperf_start_t=2.0,
        iperf_end_t=8.0,
        ramp_s=2.0,
        warmup_s=0.5,
        min_phase_samples=1,
        capacity_mbps=100.0,
        bulk_goodput_mbps=95.0,
        max_sender_lateness_ms=2.0,
        observed_p99_lateness_ms=3.5,
    )
    assert m_invalid["valid"] is False
    assert "lateness" in m_invalid["invalid_reason"]


def test_baseline_warmup_exclusion_eliminates_cold_start() -> None:
    # 25 warmup packets (0.0s to 0.48s) with high delay (45ms cold-start)
    warmup_pkts = [
        PacketRecord(
            seq=i,
            send_time_ns=int(100.0 * 1e9 + i * 20e6),
            recv_time_ns=int(100.0 * 1e9 + i * 20e6 + 45e6),
        )
        for i in range(25)
    ]
    # 50 steady baseline packets (0.5s to 1.5s) with normal delay (15ms)
    steady_pkts = [
        PacketRecord(
            seq=25 + i,
            send_time_ns=int(100.5 * 1e9 + i * 20e6),
            recv_time_ns=int(100.5 * 1e9 + i * 20e6 + 15e6),
        )
        for i in range(50)
    ]
    # 50 congested packets with 18ms delay
    cong_pkts = [
        PacketRecord(
            seq=75 + i,
            send_time_ns=int(105.0 * 1e9 + i * 20e6),
            recv_time_ns=int(105.0 * 1e9 + i * 20e6 + 18e6),
        )
        for i in range(50)
    ]
    all_pkts = warmup_pkts + steady_pkts + cong_pkts

    metrics = compute_trial_metrics(
        records=all_pkts,
        total_call_sent=len(all_pkts),
        iperf_start_t=102.0,
        iperf_end_t=107.0,
        ramp_s=2.0,
        warmup_s=0.5,
        min_phase_samples=10,
    )

    assert metrics["valid"] is True
    # Warmup packets excluded: exactly 50 steady baseline packets remain
    assert metrics["baseline"]["packet_count"] == 50
    assert metrics["baseline"]["p99_ms"] == 15.0
    assert metrics["congested"]["packet_count"] == 50
    assert metrics["congested"]["p99_ms"] == 18.0
    # Clean added delay: 18 - 15 = 3ms
    assert metrics["raw_added_delay_p99_ms"] == 3.0
    assert metrics["congested_added_delay_p99_ms"] == 3.0


def test_signed_negative_added_delay_preservation() -> None:
    # Baseline packets at 20ms delay
    base_pkts = [
        PacketRecord(
            seq=i,
            send_time_ns=int(10.0 * 1e9 + i * 20e6),
            recv_time_ns=int(10.0 * 1e9 + i * 20e6 + 20e6),
        )
        for i in range(30)
    ]
    # Congested packets with lower delay (16ms)
    cong_pkts = [
        PacketRecord(
            seq=30 + i,
            send_time_ns=int(15.0 * 1e9 + i * 20e6),
            recv_time_ns=int(15.0 * 1e9 + i * 20e6 + 16e6),
        )
        for i in range(30)
    ]
    all_pkts = base_pkts + cong_pkts

    metrics = compute_trial_metrics(
        records=all_pkts,
        total_call_sent=len(all_pkts),
        iperf_start_t=12.0,
        iperf_end_t=17.0,
        ramp_s=1.0,
        warmup_s=0.1,  # 5 warmup packets excluded
        min_phase_samples=10,
    )

    assert metrics["valid"] is True
    assert metrics["raw_added_delay_p99_ms"] == -4.0
    assert metrics["raw_added_delay_p95_ms"] == -4.0
    # Nonnegative contract metrics are clamped to 0.0
    assert metrics["congested_added_delay_p99_ms"] == 0.0
    assert metrics["added_delay_p95_ms"] == 0.0


def test_insufficient_samples_invalidates_trial() -> None:
    # Only 5 baseline packets after warmup (< 10 min_phase_samples)
    base_pkts = [
        PacketRecord(
            seq=i,
            send_time_ns=int(10.0 * 1e9 + i * 20e6),
            recv_time_ns=int(10.0 * 1e9 + i * 20e6 + 15e6),
        )
        for i in range(10)  # first 0.5s = 25 pkts, so 10 pkts is only 0.2s!
    ]
    cong_pkts = [
        PacketRecord(
            seq=10 + i,
            send_time_ns=int(15.0 * 1e9 + i * 20e6),
            recv_time_ns=int(15.0 * 1e9 + i * 20e6 + 25e6),
        )
        for i in range(20)
    ]
    metrics = compute_trial_metrics(
        records=base_pkts + cong_pkts,
        total_call_sent=30,
        iperf_start_t=12.0,
        iperf_end_t=17.0,
        ramp_s=1.0,
        warmup_s=0.5,
        min_phase_samples=10,
    )
    assert metrics["valid"] is False
    assert "Insufficient baseline samples" in metrics["invalid_reason"]


def test_compute_arm_summary() -> None:
    trials = [
        {
            "valid": True,
            "congested_added_delay_p99_ms": 10.0,
            "added_delay_p95_ms": 8.0,
            "bulk_goodput_mbps": 95.0,
            "bulk_goodput_fraction": 0.95,
            "call_loss_pct": 0.0,
            "interactive_target_met": True,
        },
        {
            "valid": True,
            "congested_added_delay_p99_ms": 12.0,
            "added_delay_p95_ms": 10.0,
            "bulk_goodput_mbps": 94.0,
            "bulk_goodput_fraction": 0.94,
            "call_loss_pct": 0.0,
            "interactive_target_met": True,
        },
    ]
    summary = compute_arm_summary(trials)
    assert summary["n_valid"] == 2
    assert summary["interactive_target_met"] == "2/2"
    assert summary["primary_added_delay_p99_ms"]["median"] == 11.0
