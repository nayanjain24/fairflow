"""tests/test_telemetry.py - Tests for telemetry providers and collectors."""

import pytest
from src.fairflow.telemetry import (
    LiveTelemetryCollector,
    DeterministicTelemetryProvider,
    TelemetryValidationError,
    QdiscStats,
)
from src.fairflow.traffic import PacketRecord
from src.fairflow.classifier import FlowMetadata


def test_live_telemetry_valid_window() -> None:
    collector = LiveTelemetryCollector(min_samples_required=2)
    records = [
        PacketRecord(seq=1, send_time_ns=1_000_000_000, recv_time_ns=1_020_000_000),  # 20ms
        PacketRecord(seq=2, send_time_ns=1_050_000_000, recv_time_ns=1_075_000_000),  # 25ms
        PacketRecord(seq=3, send_time_ns=1_100_000_000, recv_time_ns=1_122_000_000),  # 22ms
    ]

    window, report = collector.process_window(
        window_index=0,
        start_time_mono=1.0,
        end_time_mono=3.0,
        wall_clock_time=1700000000.0,
        packet_records=records,
        packets_sent=4,  # 1 packet lost
        total_bytes_transferred=25_000_000,  # 25 MB in 2s = 100 Mbps
    )

    assert window.window_index == 0
    assert window.packets_received == 3
    assert window.packets_sent == 4
    assert report.is_valid is True
    assert report.is_mock is False
    assert report.sample_count == 3
    assert report.p50_delay_ms == 22.0
    assert report.loss_pct == 25.0
    assert report.throughput_mbps == 100.0


def test_live_telemetry_stale_non_monotonic_rejection() -> None:
    collector = LiveTelemetryCollector()
    collector.process_window(
        window_index=1,
        start_time_mono=10.0,
        end_time_mono=12.0,
        wall_clock_time=1700000010.0,
        packet_records=[],
        packets_sent=0,
    )

    # 1. Non-increasing window index
    with pytest.raises(TelemetryValidationError, match="Non-increasing window index"):
        collector.process_window(
            window_index=1,
            start_time_mono=12.0,
            end_time_mono=14.0,
            wall_clock_time=1700000012.0,
            packet_records=[],
            packets_sent=0,
        )

    # 2. Window overlap / non-monotonic start time
    with pytest.raises(TelemetryValidationError, match="Window overlap"):
        collector.process_window(
            window_index=2,
            start_time_mono=11.5,
            end_time_mono=13.5,
            wall_clock_time=1700000013.0,
            packet_records=[],
            packets_sent=0,
        )


def test_live_telemetry_tc_qdisc_json_parsing() -> None:
    collector = LiveTelemetryCollector()
    tc_json = [
        {
            "kind": "htb",
            "handle": "1:",
            "bytes": 1048576,
            "packets": 800,
            "drops": 12,
            "overlimits": 5,
            "backlog": 2400,
            "qlen": 2,
        }
    ]
    qdisc_stats = collector.parse_tc_qdisc_json(tc_json)
    assert len(qdisc_stats) == 1
    assert qdisc_stats[0].qdisc_type == "htb"
    assert qdisc_stats[0].drops == 12
    assert qdisc_stats[0].backlog_bytes == 2400


def test_deterministic_telemetry_provider() -> None:
    provider = DeterministicTelemetryProvider(
        base_delay_ms=25.0,
        jitter_ms=2.0,
        loss_pct=5.0,
        throughput_mbps=75.0,
        window_duration_s=2.0,
    )

    window1, report1 = provider.generate_next_window(packets_per_sec=50)
    assert window1.window_index == 0
    assert window1.packets_sent == 100
    assert window1.packets_received == 95
    assert report1.is_mock is True
    assert report1.loss_pct == 5.0
    assert report1.throughput_mbps == 75.0

    window2, report2 = provider.generate_next_window(packets_per_sec=50)
    assert window2.window_index == 1
    assert window2.start_time_monotonic == window1.end_time_monotonic
