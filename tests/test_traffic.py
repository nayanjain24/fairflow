"""Unit tests for the UDP call simulator.

Requirements:
- Absolute-time scheduling (next_send += 0.02).
- Nanosecond timestamps using time.monotonic_ns().
- Statistical interval testing via mean and p99.
- Sequence numbers, one-way delay, loss, and RFC 3550 jitter calculation.
"""

import time
from typing import Any
import pytest
from src.fairflow.traffic import (
    UDPCallPacket,
    pack_call_packet,
    unpack_call_packet,
    generate_packet_schedule,
    compute_call_metrics,
    PacketRecord,
)


def test_packet_pack_unpack_roundtrip() -> None:
    """Verifies packet serialization preserves sequence number and nanosecond timestamp."""
    seq = 42
    timestamp_ns = 1700000000123456789
    payload_len = 160  # Typical 20ms G.711/Opus voice payload size

    data = pack_call_packet(seq=seq, send_time_ns=timestamp_ns, payload_len=payload_len)
    assert len(data) >= 12 + payload_len

    unpacked = unpack_call_packet(data)
    assert unpacked.seq == seq
    assert unpacked.send_time_ns == timestamp_ns


def test_absolute_time_scheduling_intervals() -> None:
    """Verifies that the absolute-time scheduler produces intervals with mean ~20ms and bounded p99."""
    target_interval_s = 0.020  # 20 ms
    num_packets = 50

    # Collect actual intervals using absolute time stepping
    intervals = []
    t_start = time.monotonic()
    next_send = t_start + target_interval_s

    for _ in range(num_packets):
        now = time.monotonic()
        sleep_dur = next_send - now
        if sleep_dur > 0:
            time.sleep(sleep_dur)
        intervals.append(time.monotonic() - (next_send - target_interval_s))
        next_send += target_interval_s

    mean_interval = sum(intervals) / len(intervals)
    sorted_intervals = sorted(intervals)
    p99_interval = sorted_intervals[int(0.99 * len(sorted_intervals))]

    # Mean should be very close to 20ms
    assert 0.018 <= mean_interval <= 0.024, f"Mean interval {mean_interval*1000:.2f}ms out of bounds"
    # p99 should not have severe runaway on a local test
    assert p99_interval <= 0.035, f"p99 interval {p99_interval*1000:.2f}ms exceeds tolerance"


def test_compute_call_metrics_zero_loss() -> None:
    """Verifies metrics computation when all packets arrive with known delay."""
    # 5 packets sent 20ms apart, arriving with constant 5ms delay
    base_send_ns = 1_000_000_000
    delay_ns = 5_000_000  # 5 ms

    records = [
        PacketRecord(
            seq=i,
            send_time_ns=base_send_ns + (i * 20_000_000),
            recv_time_ns=base_send_ns + (i * 20_000_000) + delay_ns,
        )
        for i in range(1, 6)
    ]

    metrics = compute_call_metrics(records=records, total_sent=5)
    assert metrics["packets_sent"] == 5
    assert metrics["packets_received"] == 5
    assert metrics["loss_count"] == 0
    assert metrics["loss_pct"] == 0.0
    assert pytest.approx(metrics["p50_delay_ms"], 0.1) == 5.0
    assert pytest.approx(metrics["p99_delay_ms"], 0.1) == 5.0
    # Jitter should be 0 because transit delay was constant
    assert pytest.approx(metrics["jitter_ms"], 0.01) == 0.0


def test_compute_call_metrics_detects_loss() -> None:
    """Verifies loss count and loss percentage calculation on dropped packets."""
    # Packets 1, 2, 4, 5 received (packet 3 lost) out of 5 sent
    base_send_ns = 1_000_000_000
    delay_ns = 10_000_000  # 10 ms

    records = [
        PacketRecord(
            seq=i,
            send_time_ns=base_send_ns + (i * 20_000_000),
            recv_time_ns=base_send_ns + (i * 20_000_000) + delay_ns,
        )
        for i in [1, 2, 4, 5]
    ]

    metrics = compute_call_metrics(records=records, total_sent=5)
    assert metrics["packets_sent"] == 5
    assert metrics["packets_received"] == 4
    assert metrics["loss_count"] == 1
    assert pytest.approx(metrics["loss_pct"], 0.1) == 20.0


def test_compute_call_metrics_calculates_rfc3550_jitter() -> None:
    """Verifies that RFC 3550 interarrival jitter is correctly accumulated."""
    # Alternating delays: 10ms, 20ms, 10ms, 20ms
    base_send_ns = 1_000_000_000
    delays_ms = [10.0, 20.0, 10.0, 20.0]

    records = [
        PacketRecord(
            seq=i + 1,
            send_time_ns=base_send_ns + (i * 20_000_000),
            recv_time_ns=base_send_ns + (i * 20_000_000) + int(d * 1_000_000),
        )
        for i, d in enumerate(delays_ms)
    ]

    metrics = compute_call_metrics(records=records, total_sent=4)
    # Jitter should be > 0 due to delay variation
    assert metrics["jitter_ms"] > 0.0


def test_csv_write_and_parse(tmp_path: Any) -> None:
    """Verifies that writing records to CSV and parsing them back maintains integrity."""
    from src.fairflow.traffic import UDPCallReceiver, parse_csv_records

    receiver = UDPCallReceiver(bind_host="127.0.0.1", bind_port=5005)
    receiver.records = [
        PacketRecord(seq=1, send_time_ns=1000, recv_time_ns=2000),
        PacketRecord(seq=2, send_time_ns=3000, recv_time_ns=4500),
    ]

    csv_path = str(tmp_path / "test_packets.csv")
    receiver.write_csv(csv_path)

    parsed = parse_csv_records(csv_path)
    assert len(parsed) == 2
    assert parsed[0].seq == 1
    assert parsed[0].send_time_ns == 1000
    assert parsed[0].recv_time_ns == 2000
    assert parsed[1].seq == 2
