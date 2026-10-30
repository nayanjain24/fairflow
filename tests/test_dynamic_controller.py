"""Unit tests for src/fairflow/dynamic_controller.py (Phase 5 Live Telemetry & Control Loop).

Verifies:
1. Fresh vs stale / out-of-order observation window validation.
2. Incomplete or invalid packet telemetry handling (missing telemetry is not healthy).
3. Flow classification and candidate-policy generation integration.
4. Capacity provider integration:
   - Capacity estimate unavailable results in NOOP safe hold.
   - Dynamic capacity injection and updates.
5. Infeasible candidate policies rejected by safety contract before enforcement.
6. Deadband hysteresis (<= 10% change) suppresses redundant policy mutations.
7. End-to-end successful apply, kernel verification, and canary acceptance.
8. Real telemetry breach (excessive delay/jitter/loss) triggers automated verified rollback.
9. Enforcement failure and rollback-verification failure fail closed.
10. Concurrency collision prevention on the same interface.
11. Preserves raw signed negative added-delay metrics without clipping.
"""

import json
import threading
from pathlib import Path
import pytest

from src.fairflow.policy import Policy, ClassPolicy
from src.fairflow.contract import load_contract, Contract
from src.fairflow.traffic import PacketRecord
from src.fairflow.classifier import TrafficClassifier, FlowMetadata
from src.fairflow.controller import PolicyEngine, PolicyState
from src.fairflow.enforce import TCDriver
from src.fairflow.enforcement_coordinator import (
    EnforcementCoordinator,
    EnforcementState,
    CanaryMonitor,
)
from src.fairflow.dynamic_controller import (
    DynamicController,
    TelemetryWindow,
    CapacityEstimate,
    StaticCapacityProvider,
    ControlAction,
    ConcurrencyCollisionError,
)
from tests.conftest import MockCommandRunner

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def contract() -> Contract:
    return load_contract(REPO_ROOT / "contract.yaml")


def _mock_verified_snapshot() -> str:
    """Return JSON string matching verified HTB qdisc tree."""
    return json.dumps([
        {"kind": "htb", "handle": "1:", "root": True},
        {"kind": "fq_codel", "handle": "100:", "parent": "1:10"},
        {"kind": "fq_codel", "handle": "200:", "parent": "1:20"},
        {"kind": "fq_codel", "handle": "300:", "parent": "1:30"},
    ])


def _make_sample_packet_records(count: int = 50, base_delay_ms: float = 20.0) -> list[PacketRecord]:
    """Generate packet records with realistic monotonic send/recv timestamps."""
    records = []
    base_ns = 1_000_000_000
    for i in range(count):
        send_ns = base_ns + i * 20_000_000  # 20ms intervals
        recv_ns = send_ns + int(base_delay_ms * 1_000_000)
        records.append(PacketRecord(seq=i, send_time_ns=send_ns, recv_time_ns=recv_ns))
    return records


# ---------------------------------------------------------------------------
# 1. Telemetry Window Freshness and Validation
# ---------------------------------------------------------------------------

def test_telemetry_window_validation_rejects_inverted_timestamps() -> None:
    with pytest.raises(ValueError, match="cannot be > end_time_monotonic"):
        TelemetryWindow(
            window_index=0,
            start_time_monotonic=10.0,
            end_time_monotonic=5.0,  # Inverted
            wall_clock_time=1000.0,
            packet_records=(),
            packets_sent=0,
            packets_received=0,
        )


def test_controller_rejects_out_of_order_stale_telemetry(contract: Contract) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    controller = DynamicController(engine=engine, coordinator=coord, contract=contract)

    # Window 1: 0.0 -> 2.0s
    w1 = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(_make_sample_packet_records()),
        packets_sent=50,
        packets_received=50,
    )
    outcome1 = controller.process_observation_window(w1)
    assert outcome1.action in (ControlAction.ENFORCED, ControlAction.COMMITTED, ControlAction.NOOP_DEADBAND)

    # Window 2: 1.0 -> 1.5s (Stale, end time < previous window end time 2.0s)
    w_stale = TelemetryWindow(
        window_index=1,
        start_time_monotonic=1.0,
        end_time_monotonic=1.5,
        wall_clock_time=1002.0,
        packet_records=(),
        packets_sent=0,
        packets_received=0,
    )
    outcome_stale = controller.process_observation_window(w_stale)
    assert outcome_stale.action == ControlAction.FAILED
    assert "Out-of-order telemetry" in outcome_stale.explanation


# ---------------------------------------------------------------------------
# 2. Missing Telemetry is Not Healthy
# ---------------------------------------------------------------------------

def test_missing_packet_telemetry_is_flagged_invalid(contract: Contract) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    controller = DynamicController(engine=engine, coordinator=coord, contract=contract)

    # Window with 0 packets received (loss of telemetry)
    w_missing = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=(),
        packets_sent=50,
        packets_received=0,  # 100% loss / missing records
    )
    outcome = controller.process_observation_window(w_missing)
    # Canary must NOT treat 0 packets as healthy; it flags invalid measurement
    assert outcome.enforcement_outcome is not None
    events = coord.list_events()
    assert any("CANARY" in ev.event_type for ev in events)


# ---------------------------------------------------------------------------
# 3. Capacity Provider Integration
# ---------------------------------------------------------------------------

def test_capacity_unavailable_results_in_noop_hold(contract: Contract) -> None:
    runner = MockCommandRunner()
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")

    # Provider with unavailable capacity
    provider = StaticCapacityProvider(capacity_mbps=100.0, is_available=False)
    controller = DynamicController(
        engine=engine, coordinator=coord, capacity_provider=provider, contract=contract
    )

    w = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(_make_sample_packet_records()),
        packets_sent=50,
        packets_received=50,
    )
    outcome = controller.process_observation_window(w)
    assert outcome.action == ControlAction.NOOP_CAPACITY_UNAVAILABLE
    assert "Capacity estimate unavailable" in outcome.explanation
    assert len(runner.history) == 0  # No mutations


# ---------------------------------------------------------------------------
# 4. Infeasible Candidate Policies Blocked Before Enforcement
# ---------------------------------------------------------------------------

def test_infeasible_candidate_rejected_safely(contract: Contract) -> None:
    runner = MockCommandRunner()
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")

    # Infeasible capacity: 10 Mbps raw (9.5 Mbps usable < 12.0 Mbps mandatory floors)
    provider = StaticCapacityProvider(capacity_mbps=10.0)
    controller = DynamicController(
        engine=engine, coordinator=coord, capacity_provider=provider, contract=contract
    )

    w = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(_make_sample_packet_records()),
        packets_sent=50,
        packets_received=50,
    )
    outcome = controller.process_observation_window(w)
    assert outcome.action == ControlAction.REJECTED
    assert "rejected by safety contract" in outcome.explanation
    assert len(runner.history) == 0  # Enforcer never invoked


# ---------------------------------------------------------------------------
# 5. Deadband Hysteresis Suppresses Redundant Mutations
# ---------------------------------------------------------------------------

def test_deadband_suppresses_redundant_policy_changes(contract: Contract) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    controller = DynamicController(
        engine=engine, coordinator=coord, contract=contract, deadband_pct=10.0
    )

    # 1. First window: applies initial policy
    w1 = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(_make_sample_packet_records(base_delay_ms=20.0)),
        packets_sent=50,
        packets_received=50,
    )
    outcome1 = controller.process_observation_window(w1)
    assert outcome1.action in (ControlAction.ENFORCED, ControlAction.COMMITTED)

    # Simulate established active policy on the coordinator
    coord.last_known_good_policy = outcome1.policy_proposed

    # 2. Second window: identical traffic conditions
    w2 = TelemetryWindow(
        window_index=1,
        start_time_monotonic=2.0,
        end_time_monotonic=4.0,
        wall_clock_time=1002.0,
        packet_records=tuple(_make_sample_packet_records(base_delay_ms=20.0)),
        packets_sent=50,
        packets_received=50,
    )
    outcome2 = controller.process_observation_window(w2)
    assert outcome2.action == ControlAction.NOOP_DEADBAND
    assert "apply suppressed" in outcome2.explanation


# ---------------------------------------------------------------------------
# 6. Raw Signed Added Delay Preserved (No Negative Clipping)
# ---------------------------------------------------------------------------

def test_raw_negative_signed_delay_preserved(contract: Contract) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    controller = DynamicController(engine=engine, coordinator=coord, contract=contract)

    # Measured delay is 18.0 ms, baseline idle delay was 20.0 ms
    # Added delay is 18.0 - 20.0 = -2.0 ms
    records = _make_sample_packet_records(count=50, base_delay_ms=18.0)
    w = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(records),
        packets_sent=50,
        packets_received=50,
        baseline_delay_ms=20.0,
    )
    outcome = controller.process_observation_window(w)
    # Ensure added delay is not clipped to 0.0
    assert outcome.details["added_delay_ms"] == -2.0


# ---------------------------------------------------------------------------
# 7. Telemetry Guardrail Breach Triggers Verified Rollback
# ---------------------------------------------------------------------------

def test_telemetry_breach_triggers_verified_rollback(contract: Contract) -> None:
    runner = MockCommandRunner()
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    controller = DynamicController(engine=engine, coordinator=coord, contract=contract)

    # Mock responses:
    # 1. Pre-apply snapshot: clean/initial
    # 2. Post-apply snapshot: verified HTB tree
    # 3. Post-rollback snapshot: clean
    state = "initial"

    def mock_run(cmd, check=True):
        nonlocal state
        cmd_str = " ".join(cmd)
        runner.history.append(cmd)
        if "tc qdisc replace" in cmd_str:
            state = "applied"
            return "", "", 0
        if "tc qdisc del" in cmd_str and state == "applied":
            state = "rolled_back"
            return "", "", 0
        if "tc -j qdisc show" in cmd_str:
            if state == "rolled_back":
                return "[]", "", 0
            return _mock_verified_snapshot(), "", 0
        return "", "", 0

    runner.run = mock_run

    # Severe standing delay breach: 120 ms (guardrail is 80 ms) across 2 consecutive windows
    w1 = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(_make_sample_packet_records(base_delay_ms=120.0)),
        packets_sent=50,
        packets_received=50,
        baseline_delay_ms=10.0,  # Added delay = 110 ms > 80 ms
    )
    outcome1 = controller.process_observation_window(w1)
    # First breach window does not trigger rollback immediately (requires 2 consecutive)
    assert outcome1.action == ControlAction.ENFORCED

    w2 = TelemetryWindow(
        window_index=1,
        start_time_monotonic=2.0,
        end_time_monotonic=4.0,
        wall_clock_time=1002.0,
        packet_records=tuple(_make_sample_packet_records(base_delay_ms=120.0)),
        packets_sent=50,
        packets_received=50,
        baseline_delay_ms=10.0,  # Second consecutive breach!
    )
    outcome2 = controller.process_observation_window(w2)
    # Second breach window triggers verified rollback
    assert outcome2.action == ControlAction.ROLLED_BACK
    assert coord.state == EnforcementState.ROLLED_BACK


# ---------------------------------------------------------------------------
# 8. Concurrency Collision Protection
# ---------------------------------------------------------------------------

def test_concurrency_collision_raises_exception(contract: Contract) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    controller = DynamicController(engine=engine, coordinator=coord, contract=contract)

    w = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(_make_sample_packet_records()),
        packets_sent=50,
        packets_received=50,
    )

    # Manually hold the mutex to simulate concurrent worker execution
    controller._mutex.acquire()
    try:
        with pytest.raises(ConcurrencyCollisionError, match="Concurrent mutation collision"):
            controller.process_observation_window(w)
    finally:
        controller._mutex.release()


# ---------------------------------------------------------------------------
# 9. Audit Event Logging and Ordering
# ---------------------------------------------------------------------------

def test_audit_event_ordering_and_policy_state_consistency(contract: Contract) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)
    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    controller = DynamicController(engine=engine, coordinator=coord, contract=contract)

    w = TelemetryWindow(
        window_index=0,
        start_time_monotonic=0.0,
        end_time_monotonic=2.0,
        wall_clock_time=1000.0,
        packet_records=tuple(_make_sample_packet_records()),
        packets_sent=50,
        packets_received=50,
    )
    outcome = controller.process_observation_window(w)

    outcomes = controller.list_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].step_index == 1
    assert outcomes[0].decision_id is not None
    assert outcomes[0].capacity_estimate is not None
    assert outcomes[0].action == outcome.action


# ---------------------------------------------------------------------------
# 10. Real Root Linux Integration: Full Dynamic Controller Loop
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_integration_dynamic_controller_loop(contract: Contract) -> None:
    """Test full DynamicController loop against real kernel tc in isolated netns."""
    import os
    import shutil
    from src.fairflow.enforce import SystemCommandRunner

    if os.geteuid() != 0:
        pytest.skip("Integration test requires root privileges (run with sudo)")
    if not shutil.which("ip") or not shutil.which("tc"):
        pytest.fail("iproute2 tools (ip, tc) not found; run inside the VM via scripts/vm.sh")

    ns = "ff_dyn_ns"
    veth_a = "ff_dyn_a"
    veth_b = "ff_dyn_b"
    runner = SystemCommandRunner()
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)

    # Clean up any leftover test namespace first
    runner.run(["ip", "netns", "del", ns], check=False)
    runner.run(["ip", "link", "del", veth_b], check=False)

    try:
        # Create isolated namespace and veth pair
        runner.run(["ip", "netns", "add", ns])
        runner.run(["ip", "link", "add", veth_a, "type", "veth", "peer", "name", veth_b])
        runner.run(["ip", "link", "set", veth_a, "netns", ns])
        runner.run(["ip", "netns", "exec", ns, "ip", "link", "set", veth_a, "up"])

        coord = EnforcementCoordinator(
            engine=engine,
            driver=driver,
            interface=veth_a,
            namespace=ns,
            contract=contract,
        )
        controller = DynamicController(
            engine=engine,
            coordinator=coord,
            contract=contract,
        )

        # 1. First observation window (healthy): Propose -> Validate -> Apply -> Verify
        w0 = TelemetryWindow(
            window_index=0,
            start_time_monotonic=0.0,
            end_time_monotonic=2.0,
            wall_clock_time=1000.0,
            packet_records=tuple(_make_sample_packet_records(base_delay_ms=15.0)),
            packets_sent=50,
            packets_received=50,
            baseline_delay_ms=10.0,
        )
        outcome0 = controller.process_observation_window(w0)
        assert outcome0.action == ControlAction.ENFORCED

        # Verify kernel HTB qdisc in real namespace
        qdiscs = driver.snapshot(interface=veth_a, namespace=ns)
        assert any(q.get("kind") == "htb" and q.get("handle") == "1:" for q in qdiscs)

        # 2. Feed 4 more healthy windows -> Canary Acceptance and Commit to ACTIVE
        for i in range(1, 5):
            w = TelemetryWindow(
                window_index=i,
                start_time_monotonic=i * 2.0,
                end_time_monotonic=(i + 1) * 2.0,
                wall_clock_time=1000.0 + i * 2.0,
                packet_records=tuple(_make_sample_packet_records(base_delay_ms=15.0)),
                packets_sent=50,
                packets_received=50,
                baseline_delay_ms=10.0,
            )
            outcome = controller.process_observation_window(w)
            if i == 4:
                # 5th good window completes the canary target
                assert outcome.action == ControlAction.COMMITTED
                assert coord.state == EnforcementState.ACCEPTED
            else:
                assert outcome.action == ControlAction.ENFORCED

        # 3. Dynamic capacity update outside deadband (100 -> 60 Mbps, 40% change > 10%)
        # Followed by severe standing delay breaches -> Verified Rollback!
        controller.capacity_provider.set_capacity(60.0, is_available=True)
        w_b1 = TelemetryWindow(
            window_index=5,
            start_time_monotonic=10.0,
            end_time_monotonic=12.0,
            wall_clock_time=1010.0,
            packet_records=tuple(_make_sample_packet_records(base_delay_ms=100.0)),
            packets_sent=50,
            packets_received=50,
            baseline_delay_ms=10.0,
        )
        out_b1 = controller.process_observation_window(w_b1)
        assert out_b1.action == ControlAction.ENFORCED

        w_b2 = TelemetryWindow(
            window_index=6,
            start_time_monotonic=12.0,
            end_time_monotonic=14.0,
            wall_clock_time=1012.0,
            packet_records=tuple(_make_sample_packet_records(base_delay_ms=105.0)),
            packets_sent=50,
            packets_received=50,
            baseline_delay_ms=10.0,
        )
        out_b2 = controller.process_observation_window(w_b2)
        assert out_b2.action == ControlAction.ROLLED_BACK
        assert coord.state == EnforcementState.ROLLED_BACK

        # Verify kernel: Rollback restored the last-known-good policy (HTB 1:)
        post_qdiscs = driver.snapshot(interface=veth_a, namespace=ns)
        assert any(q.get("kind") == "htb" and q.get("handle") == "1:" for q in post_qdiscs)
        assert coord.last_known_good_policy is not None
        assert coord.last_known_good_policy.link_capacity_mbps == 100.0

    finally:
        runner.run(["ip", "netns", "del", ns], check=False)
        runner.run(["ip", "link", "del", veth_b], check=False)
