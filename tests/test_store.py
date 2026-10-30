"""tests/test_store.py - Tests for SQLite-backed AuditStore."""

import os
import time
import pytest
from src.fairflow.store import AuditStore


def test_audit_store_in_memory() -> None:
    store = AuditStore(":memory:")
    evt_id = store.record_event(
        event_type="TEST_EVENT",
        details={"key": "val", "num": 42},
        summary="A test event",
    )
    assert evt_id.startswith("evt_")

    events = store.query_events()
    assert len(events) == 1
    assert events[0]["event_id"] == evt_id
    assert events[0]["details"]["key"] == "val"
    assert events[0]["summary"] == "A test event"
    store.close()


def test_audit_store_file_persistence(tmp_path) -> None:
    db_file = tmp_path / "test_audit.db"
    store = AuditStore(db_file)

    # 1. Telemetry
    tel_id = store.record_telemetry(
        snapshot={
            "wall_clock_time": 1700000000.0,
            "timestamp_monotonic": 100.0,
            "window_duration_s": 2.0,
            "is_valid": True,
            "rtt_ms": 12.5,
            "p95_latency_ms": 18.2,
            "jitter_ms": 1.1,
            "loss_pct": 0.05,
            "throughput_mbps": 85.0,
            "flows": [{"flow_id": "f1", "src": "10.0.0.1"}],
        },
        raw_ref="/path/to/raw.pcap",
    )
    assert tel_id.startswith("tel_")

    latest = store.get_latest_telemetry()
    assert latest is not None
    assert latest["record_id"] == tel_id
    assert latest["rtt_ms"] == 12.5
    assert latest["raw_ref"] == "/path/to/raw.pcap"

    # 2. Capacity estimate
    row_id = store.record_capacity_estimate(
        estimate={
            "capacity_mbps": 100.0,
            "confidence": 0.95,
            "is_available": True,
            "reason": "Stable link",
        }
    )
    assert row_id > 0

    # 3. Policy
    store.record_policy(
        policy_id="pol_1",
        policy_type="DYNAMIC_ADAPTIVE",
        is_valid=True,
        classes=[{"name": "VOIP", "rate_mbps": 10.0}],
        explanation="Allocated based on demand",
    )
    pol = store.get_policy("pol_1")
    assert pol is not None
    assert pol["is_valid"] is True
    assert pol["classes"][0]["name"] == "VOIP"

    # 4. State transition & Rollback
    store.record_transition(
        from_state="ENFORCED",
        to_state="ROLLING_BACK",
        trigger="canary_breach",
        policy_id="pol_1",
        rollback_occurred=True,
        rollback_reason="Latency guardrail exceeded 80ms",
    )
    rollbacks = store.get_rollback_history()
    assert len(rollbacks) == 1
    assert rollbacks[0]["policy_id"] == "pol_1"
    assert "Latency guardrail exceeded" in rollbacks[0]["rollback_reason"]

    # 5. Experiment lifecycle
    store.create_experiment("exp_001", "scenario_a", {"duration_s": 30})
    store.update_experiment("exp_001", status="running")
    exp = store.get_experiment("exp_001")
    assert exp["status"] == "running"

    store.update_experiment("exp_001", status="succeeded", metrics={"achieved_tput": 95.2})
    exp_final = store.get_experiment("exp_001")
    assert exp_final["status"] == "succeeded"
    assert exp_final["metrics_summary"]["achieved_tput"] == 95.2

    store.close()

    # Re-open database from disk and verify persistence
    store2 = AuditStore(db_file)
    assert len(store2.list_policies()) == 1
    assert len(store2.list_experiments()) == 1
    store2.close()
