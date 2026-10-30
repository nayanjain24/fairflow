"""Unit tests for src/fairflow/classifier.py.

Verifies:
1. FlowMetadata construction and validation (port ranges, DSCP limits, rate limits).
2. Classification of interactive VoIP/call traffic (UDP 5004, small packets, 50 pps, DSCP EF).
3. Classification of bulk download traffic (TCP 5201 iperf3, MTU packets, high throughput).
4. Classification of streaming video traffic (RTMP/RTSP, DSCP AF31).
5. Ambiguous traffic classification resulting in 'unknown' with low confidence.
6. User intent registration and priority override (confidence 1.0, is_override=True).
7. User intent expiration using injectable deterministic clock (active -> expired -> heuristic fallback).
8. User intent pruning and precedence for multiple matching intents.
9. Intent removal and immediate fallback.
10. Strict determinism across repeated evaluations.
"""

import pytest
from src.fairflow.classifier import (
    FlowMetadata,
    ClassificationResult,
    UserIntent,
    UserIntentRegistry,
    TrafficClassifier,
    DSCP_EF,
    DSCP_AF31,
    DSCP_CS0,
)


# ---------------------------------------------------------------------------
# 1. FlowMetadata Construction & Validation
# ---------------------------------------------------------------------------

def test_flow_metadata_valid() -> None:
    flow = FlowMetadata(
        protocol="udp",
        src_ip="10.0.1.2",
        dst_ip="10.0.2.2",
        src_port=5004,
        dst_port=5004,
        packet_count=100,
        byte_count=17200,
        packet_rate_pps=50.0,
        bitrate_bps=68800.0,
        mean_packet_size_bytes=172.0,
        dscp=DSCP_EF,
    )
    assert flow.flow_id == "udp:10.0.1.2:5004->10.0.2.2:5004"
    assert flow.dscp == 46


def test_flow_metadata_invalid_ports_and_rates() -> None:
    with pytest.raises(ValueError, match="dst_port must be in"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=70000)

    with pytest.raises(ValueError, match="src_port must be in"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", src_port=-1)

    with pytest.raises(ValueError, match="dscp must be in"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dscp=64)

    with pytest.raises(ValueError, match="packet_rate_pps must be non-negative"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", packet_rate_pps=-10.0)

    with pytest.raises(ValueError, match="protocol must be a non-empty string"):
        FlowMetadata(protocol="", src_ip="1.1.1.1", dst_ip="2.2.2.2")


# ---------------------------------------------------------------------------
# 2. Heuristic Classification of Standard Flows
# ---------------------------------------------------------------------------

def test_classify_interactive_call_flow() -> None:
    classifier = TrafficClassifier()
    # Scenario A call flow: UDP dst port 5004, 172B packets, 50 pps
    call_flow = FlowMetadata(
        protocol="udp",
        src_ip="10.0.2.2",
        dst_ip="10.0.1.2",
        src_port=5004,
        dst_port=5004,
        packet_rate_pps=50.0,
        bitrate_bps=68800.0,
        mean_packet_size_bytes=172.0,
        dscp=DSCP_EF,
    )
    result = classifier.classify(call_flow, current_time=100.0)
    assert result.traffic_class == "interactive"
    assert result.confidence >= 0.70
    assert result.is_override is False
    assert "Port 5004" in result.reason or "interactive" in result.reason


def test_classify_bulk_download_flow() -> None:
    classifier = TrafficClassifier()
    # Scenario A bulk flow: TCP iperf3 on port 5201, 1448B packets, 80 Mbps
    bulk_flow = FlowMetadata(
        protocol="tcp",
        src_ip="10.0.2.2",
        dst_ip="10.0.1.2",
        src_port=5201,
        dst_port=45678,
        packet_rate_pps=7000.0,
        bitrate_bps=80_000_000.0,
        mean_packet_size_bytes=1448.0,
        dscp=DSCP_CS0,
    )
    result = classifier.classify(bulk_flow, current_time=100.0)
    assert result.traffic_class == "bulk"
    assert result.confidence >= 0.70
    assert result.is_override is False
    assert "bulk" in result.reason.lower()


def test_classify_streaming_video_flow() -> None:
    classifier = TrafficClassifier()
    # Streaming video: RTMP on port 1935, DSCP AF31, moderate bit rate
    streaming_flow = FlowMetadata(
        protocol="tcp",
        src_ip="10.0.2.2",
        dst_ip="10.0.1.2",
        src_port=1935,
        dst_port=54321,
        packet_rate_pps=500.0,
        bitrate_bps=4_000_000.0,
        mean_packet_size_bytes=800.0,
        dscp=DSCP_AF31,
    )
    result = classifier.classify(streaming_flow, current_time=100.0)
    assert result.traffic_class == "streaming"
    assert result.confidence >= 0.70
    assert result.is_override is False


def test_classify_ambiguous_flow_yields_unknown() -> None:
    classifier = TrafficClassifier()
    # Ambiguous flow: unknown ports, tiny packet rate, no DSCP
    ambiguous_flow = FlowMetadata(
        protocol="udp",
        src_ip="10.0.2.2",
        dst_ip="10.0.1.2",
        src_port=9999,
        dst_port=8888,
        packet_rate_pps=1.0,
        bitrate_bps=1000.0,
        mean_packet_size_bytes=500.0,
    )
    result = classifier.classify(ambiguous_flow, current_time=100.0)
    assert result.traffic_class == "unknown"
    assert result.confidence <= 0.40
    assert "Ambiguous" in result.reason


# ---------------------------------------------------------------------------
# 3. User Intent Overrides & Expiration
# ---------------------------------------------------------------------------

def test_user_intent_immediate_override() -> None:
    registry = UserIntentRegistry()
    classifier = TrafficClassifier(intent_registry=registry)

    # Register intent: prioritize port 5201 as 'interactive'
    intent = UserIntent(
        intent_id="gaming_session_1",
        target_class="interactive",
        created_at=100.0,
        expires_at=200.0,
        description="Prioritize low-latency gaming stream",
        dst_port=5201,
    )
    registry.add_intent(intent)

    flow = FlowMetadata(
        protocol="tcp",
        src_ip="10.0.2.2",
        dst_ip="10.0.1.2",
        src_port=40000,
        dst_port=5201,
        packet_rate_pps=1000.0,
        bitrate_bps=10_000_000.0,
        mean_packet_size_bytes=1200.0,
    )

    # Flow would normally be classified as bulk, but intent overrides to interactive
    res = classifier.classify(flow, current_time=150.0)
    assert res.traffic_class == "interactive"
    assert res.confidence == 1.0
    assert res.is_override is True
    assert "User intent 'gaming_session_1' override" in res.reason


def test_user_intent_expiration_and_fallback() -> None:
    clock_time = 100.0

    def get_clock() -> float:
        return clock_time

    registry = UserIntentRegistry()
    classifier = TrafficClassifier(intent_registry=registry, time_fn=get_clock)

    intent = UserIntent(
        intent_id="temp_intent",
        target_class="interactive",
        created_at=100.0,
        expires_at=110.0,  # 10s duration
        description="Short meeting call",
        dst_port=5201,
    )
    registry.add_intent(intent)

    flow = FlowMetadata(
        protocol="tcp",
        src_ip="10.0.2.2",
        dst_ip="10.0.1.2",
        dst_port=5201,
        packet_rate_pps=5000.0,
        bitrate_bps=50_000_000.0,
        mean_packet_size_bytes=1448.0,
    )

    # 1. At t=105.0: intent is active
    clock_time = 105.0
    res_active = classifier.classify(flow)
    assert res_active.traffic_class == "interactive"
    assert res_active.is_override is True
    assert res_active.confidence == 1.0

    # 2. At t=110.0: intent has expired
    clock_time = 110.0
    res_expired = classifier.classify(flow)
    assert res_expired.traffic_class == "bulk"  # Fallback to normal heuristic
    assert res_expired.is_override is False
    assert res_expired.confidence < 1.0

    # 3. Prune expired intents
    pruned = registry.prune_expired(current_time=115.0)
    assert pruned == 1
    assert len(registry.list_active(current_time=115.0)) == 0


def test_user_intent_removal() -> None:
    registry = UserIntentRegistry()
    classifier = TrafficClassifier(intent_registry=registry)

    intent = UserIntent(
        intent_id="cancel_me",
        target_class="interactive",
        created_at=100.0,
        expires_at=200.0,
        dst_port=5004,
    )
    registry.add_intent(intent)
    assert registry.remove_intent("cancel_me") is True
    assert registry.remove_intent("cancel_me") is False  # Already removed


def test_user_intent_precedence_multiple_matches() -> None:
    registry = UserIntentRegistry()
    classifier = TrafficClassifier(intent_registry=registry)

    # Intent 1 created earlier
    intent1 = UserIntent(
        intent_id="older_intent",
        target_class="bulk",
        created_at=100.0,
        expires_at=300.0,
        dst_port=5004,
    )
    # Intent 2 created later (takes precedence)
    intent2 = UserIntent(
        intent_id="newer_intent",
        target_class="interactive",
        created_at=150.0,
        expires_at=250.0,
        dst_port=5004,
    )
    registry.add_intent(intent1)
    registry.add_intent(intent2)

    flow = FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5004)
    res = classifier.classify(flow, current_time=160.0)
    assert res.traffic_class == "interactive"
    assert "newer_intent" in res.reason


# ---------------------------------------------------------------------------
# 4. Determinism & Edge Cases
# ---------------------------------------------------------------------------

def test_classifier_determinism() -> None:
    classifier = TrafficClassifier()
    flow = FlowMetadata(
        protocol="udp",
        src_ip="10.0.1.2",
        dst_ip="10.0.2.2",
        dst_port=5004,
        packet_rate_pps=50.0,
        bitrate_bps=68800.0,
        mean_packet_size_bytes=172.0,
    )
    res1 = classifier.classify(flow, current_time=100.0)
    for _ in range(50):
        res2 = classifier.classify(flow, current_time=100.0)
        assert res1 == res2


def test_user_intent_invalid_creation() -> None:
    with pytest.raises(ValueError, match="target_class must be"):
        UserIntent(intent_id="bad", target_class="unsupported", created_at=100.0, expires_at=200.0, dst_port=5004)

    with pytest.raises(ValueError, match="expires_at .* must be strictly greater"):
        UserIntent(intent_id="bad", target_class="interactive", created_at=200.0, expires_at=100.0, dst_port=5004)

    # Reject intent with no filter criteria (prevents unintended wildcard override of all traffic)
    with pytest.raises(ValueError, match="must specify at least one filter criterion"):
        UserIntent(intent_id="no_filters", target_class="interactive", created_at=100.0, expires_at=200.0)

    # Reject NaN and infinite timestamps
    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        UserIntent(intent_id="nan_time", target_class="interactive", created_at=float("nan"), expires_at=200.0, dst_port=5004)

    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        UserIntent(intent_id="inf_time", target_class="interactive", created_at=100.0, expires_at=float("inf"), dst_port=5004)


def test_user_intent_exact_boundary_conditions() -> None:
    intent = UserIntent(
        intent_id="boundary_test",
        target_class="interactive",
        created_at=100.0,
        expires_at=110.0,
        dst_port=5004,
    )
    # Active on exact created_at
    assert intent.is_active(100.0) is True
    # Active inside window
    assert intent.is_active(105.0) is True
    assert intent.is_active(109.999999) is True
    # Strictly expired at expires_at
    assert intent.is_active(110.0) is False
    assert intent.is_active(110.000001) is False
    # Not active before created_at
    assert intent.is_active(99.999999) is False


def test_user_intent_tie_breaking_identical_timestamps() -> None:
    registry = UserIntentRegistry()
    classifier = TrafficClassifier(intent_registry=registry)

    # Two intents with identical created_at=100.0
    intent_a = UserIntent(intent_id="intent_a", target_class="streaming", created_at=100.0, expires_at=200.0, dst_port=5004)
    intent_b = UserIntent(intent_id="intent_b", target_class="interactive", created_at=100.0, expires_at=200.0, dst_port=5004)

    registry.add_intent(intent_a)
    registry.add_intent(intent_b)

    flow = FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5004)
    # Tie-break sorts by (created_at, intent_id) reverse: 'intent_b' > 'intent_a'
    res = classifier.classify(flow, current_time=150.0)
    assert res.traffic_class == "interactive"
    assert "intent_b" in res.reason


def test_flow_metadata_rejects_nan_and_inf_rates() -> None:
    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", packet_rate_pps=float("nan"))

    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", bitrate_bps=float("inf"))

    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", mean_packet_size_bytes=float("nan"))

    with pytest.raises(TypeError, match="must be a real number"):
        FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", packet_rate_pps=True)


def test_classifier_rejects_nan_and_inf_current_time() -> None:
    classifier = TrafficClassifier()
    flow = FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5004)

    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        classifier.classify(flow, current_time=float("nan"))

    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        classifier.classify(flow, current_time=float("inf"))

    with pytest.raises(TypeError, match="must be a real number"):
        classifier.classify(flow, current_time=True)  # type: ignore
