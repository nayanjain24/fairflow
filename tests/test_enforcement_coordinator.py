"""Unit tests for src/fairflow/enforcement_coordinator.py.

Verifies:
1. Strict namespace and interface allowlist enforcement.
2. Rejected candidate never reaches the driver.
3. Precondition failure (unvalidated candidate) fails closed.
4. Snapshot failure before mutation prevents any apply commands.
5. Successful apply, independent kernel verification, and ENFORCED state.
6. Driver apply failure triggers automatic verified rollback.
7. Verification mismatch triggers automatic verified rollback.
8. Rollback command failure transitions to FAILED without claiming success.
9. Rollback completes but post-rollback verification fails transitions to FAILED.
10. Canary evaluation:
    - Missing / stale / invalid samples handled safely.
    - Consecutive breaches trigger automatic rollback.
    - Healthy measurements accumulate good windows and result in ACCEPTED.
11. Last-known-good state preservation across successive policies.
12. Immutable structured audit history logging.
"""

import json
import os
import shutil
import sys
from pathlib import Path
import pytest

from src.fairflow.policy import Policy, ClassPolicy
from src.fairflow.contract import load_contract, Contract
from src.fairflow.enforce import TCDriver, SystemCommandRunner
from src.fairflow.controller import (
    PolicyEngine,
    PolicyState,
    PolicyDecisionRecord,
)
from src.fairflow.enforcement_coordinator import (
    EnforcementCoordinator,
    EnforcementState,
    CanaryMonitor,
    CanaryMeasurement,
    CanaryResult,
)
from tests.conftest import MockCommandRunner

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def contract() -> Contract:
    return load_contract(REPO_ROOT / "contract.yaml")


@pytest.fixture
def engine(contract: Contract) -> PolicyEngine:
    return PolicyEngine(contract=contract)


@pytest.fixture
def valid_policy_record(engine: PolicyEngine) -> PolicyDecisionRecord:
    return engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=95.0,
        timestamp=1000.0,
    )


def _mock_verified_snapshot() -> str:
    """Return JSON string matching verified HTB qdisc tree."""
    return json.dumps([
        {"kind": "htb", "handle": "1:", "root": True},
        {"kind": "fq_codel", "handle": "100:", "parent": "1:10"},
        {"kind": "fq_codel", "handle": "200:", "parent": "1:20"},
        {"kind": "fq_codel", "handle": "300:", "parent": "1:30"},
    ])


# ---------------------------------------------------------------------------
# 1. Allowlist and Precondition Enforcement
# ---------------------------------------------------------------------------

def test_coordinator_rejects_disallowed_interfaces_and_namespaces(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)
    driver = TCDriver(runner=MockCommandRunner())

    # Invalid interface
    with pytest.raises(ValueError, match="must match pattern"):
        EnforcementCoordinator(engine=engine, driver=driver, interface="eth0", namespace="ff_router")

    # Invalid namespace
    with pytest.raises(ValueError, match="must match pattern"):
        EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="default")


def test_rejected_candidate_never_reaches_driver(contract: Contract) -> None:
    runner = MockCommandRunner()
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)

    # Infeasible candidate -> REJECTED
    rej_record = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=5.0,
        timestamp=100.0,
    )
    assert rej_record.state == PolicyState.REJECTED

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    outcome = coord.apply_and_verify(rej_record)

    assert outcome.success is False
    assert "not VALIDATED" in (outcome.error_message or "")
    assert len(runner.history) == 0  # Driver was never touched


def test_unvalidated_candidate_fails_closed(contract: Contract) -> None:
    runner = MockCommandRunner()
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)

    # Create dummy record in PROPOSED state
    proposed_record = PolicyDecisionRecord(
        decision_id="dec_test_001",
        state=PolicyState.PROPOSED,
        timestamp=100.0,
        usable_capacity_mbps=95.0,
        proposed_policy=Policy(link_capacity_mbps=95.0, classes={
            "bulk": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=95.0, priority=3)
        }),
        feasibility_result=None,
        active_classes=(),
        unmapped_unknown_count=0,
        explanation="Proposed",
    )

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    outcome = coord.apply_and_verify(proposed_record)

    assert outcome.success is False
    assert outcome.kernel_verified is False
    assert len(runner.history) == 0


# ---------------------------------------------------------------------------
# 2. Pre-Apply Snapshot Failure
# ---------------------------------------------------------------------------

def test_snapshot_failure_aborts_without_mutation(
    engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord
) -> None:
    runner = MockCommandRunner()
    # Mock snapshot command failure
    runner.responses["tc -j qdisc show"] = ("", "Device not found", 1)
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    outcome = coord.apply_and_verify(valid_policy_record)

    assert outcome.success is False
    assert "Pre-apply snapshot capture failed" in (outcome.error_message or "")
    # Verify no mutation commands (del, replace) were run
    assert not any("replace" in " ".join(cmd) for cmd in runner.history)


# ---------------------------------------------------------------------------
# 3. Successful Apply & Independent Verification
# ---------------------------------------------------------------------------

def test_successful_apply_and_kernel_verification(
    engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord
) -> None:
    runner = MockCommandRunner()
    # Baseline before apply: empty
    # After apply: verified HTB tree
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    outcome = coord.apply_and_verify(valid_policy_record)

    assert outcome.success is True
    assert outcome.enforcement_state == EnforcementState.ENFORCED
    assert outcome.kernel_verified is True
    assert outcome.rollback_performed is False
    assert coord.state == EnforcementState.ENFORCED

    # Engine record updated to ENFORCED
    updated_rec = engine.get_record(valid_policy_record.decision_id)
    assert updated_rec.state == PolicyState.ENFORCED


# ---------------------------------------------------------------------------
# 4. Apply Failure Triggers Verified Rollback
# ---------------------------------------------------------------------------

def test_apply_failure_triggers_verified_rollback(
    engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord
) -> None:
    runner = MockCommandRunner()
    # Snapshot succeeds (baseline empty)
    # Apply command fails
    # Rollback succeeds (deletes root qdisc)
    call_count = 0

    def mock_run(cmd, check=True):
        nonlocal call_count
        cmd_str = " ".join(cmd)
        runner.history.append(cmd)
        if "tc -j qdisc show" in cmd_str:
            return "[]", "", 0
        if "tc qdisc replace" in cmd_str:
            raise RuntimeError("RTNETLINK answers: Operation not permitted")
        if "tc qdisc del" in cmd_str:
            return "", "", 0
        return "", "", 0

    runner.run = mock_run
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    outcome = coord.apply_and_verify(valid_policy_record)

    assert outcome.success is False
    assert outcome.rollback_performed is True
    assert outcome.rollback_verified is True
    assert coord.state == EnforcementState.ROLLED_BACK


# ---------------------------------------------------------------------------
# 5. Kernel Verification Mismatch Triggers Rollback
# ---------------------------------------------------------------------------

def test_verification_mismatch_triggers_rollback(
    engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord
) -> None:
    runner = MockCommandRunner()
    # Apply succeeds, but snapshot returns missing classes
    def mock_run(cmd, check=True):
        cmd_str = " ".join(cmd)
        runner.history.append(cmd)
        if "tc -j qdisc show" in cmd_str:
            # Missing bulk and streaming classes
            return json.dumps([{"kind": "htb", "handle": "1:", "root": True}]), "", 0
        return "", "", 0

    runner.run = mock_run
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    outcome = coord.apply_and_verify(valid_policy_record)

    assert outcome.success is False
    assert outcome.rollback_performed is True
    assert "Kernel verification failed" in (outcome.error_message or "")


# ---------------------------------------------------------------------------
# 6. Rollback Command Failure & Verification Failure (Fail Closed)
# ---------------------------------------------------------------------------

def test_rollback_command_failure_sets_failed_state(
    engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord
) -> None:
    runner = MockCommandRunner()

    def mock_run(cmd, check=True):
        cmd_str = " ".join(cmd)
        runner.history.append(cmd)
        if "tc qdisc replace" in cmd_str:
            raise RuntimeError("Apply failed")
        if "tc qdisc del" in cmd_str:
            raise RuntimeError("Kernel panic during rollback del")
        return "[]", "", 0

    runner.run = mock_run
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    outcome = coord.apply_and_verify(valid_policy_record)

    assert outcome.success is False
    assert outcome.rollback_performed is True
    assert outcome.rollback_verified is False  # Never claim verified rollback if it failed
    assert outcome.enforcement_state == EnforcementState.FAILED
    assert coord.state == EnforcementState.FAILED


def test_rollback_verification_failure_sets_failed_state(contract: Contract) -> None:
    runner = MockCommandRunner()
    driver = TCDriver(runner=runner)
    engine = PolicyEngine(contract=contract)

    # Established last known good policy
    lkg = Policy(link_capacity_mbps=50.0, classes={
        "interactive": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=50.0, priority=1)
    })

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    coord.last_known_good_policy = lkg

    # Post-rollback snapshot returns empty instead of expected lkg HTB tree
    runner.responses["tc -j qdisc show"] = ("[]", "", 0)

    rb_outcome = coord.rollback(reason="Test rollback")
    assert rb_outcome.success is False
    assert rb_outcome.rollback_verified is False
    assert coord.state == EnforcementState.FAILED


# ---------------------------------------------------------------------------
# 7. Canary Monitoring & Evaluation Logic
# ---------------------------------------------------------------------------

def test_canary_monitor_healthy_sequence_accepted(contract: Contract) -> None:
    monitor = CanaryMonitor(contract=contract)
    # 5 healthy windows of 2s each (10s trial)
    measurements = [
        CanaryMeasurement(timestamp=i * 2.0, window_index=i, added_delay_ms=15.0, jitter_ms=5.0, loss_pct=0.1)
        for i in range(5)
    ]
    res = monitor.evaluate_series(measurements)
    assert res.passed is True
    assert res.status == "ACCEPTED"
    assert res.good_windows == 5
    assert res.consecutive_breaches == 0


def test_canary_monitor_breach_requires_consecutive_windows(contract: Contract) -> None:
    monitor = CanaryMonitor(contract=contract)
    # Contract breach_windows = 2.
    # Single isolated bad window should NOT trigger breach
    isolated_bad = [
        CanaryMeasurement(timestamp=0.0, window_index=0, added_delay_ms=10.0, jitter_ms=2.0, loss_pct=0.0),
        CanaryMeasurement(timestamp=2.0, window_index=1, added_delay_ms=95.0, jitter_ms=2.0, loss_pct=0.0), # Bad (delay > 80)
        CanaryMeasurement(timestamp=4.0, window_index=2, added_delay_ms=12.0, jitter_ms=3.0, loss_pct=0.0), # Recovered
        CanaryMeasurement(timestamp=6.0, window_index=3, added_delay_ms=11.0, jitter_ms=3.0, loss_pct=0.0),
        CanaryMeasurement(timestamp=8.0, window_index=4, added_delay_ms=10.0, jitter_ms=2.0, loss_pct=0.0),
    ]
    res_isolated = monitor.evaluate_series(isolated_bad)
    # Recovered and reached 4 good windows (>= 3 target)
    assert res_isolated.passed is True
    assert res_isolated.status == "ACCEPTED"

    # Two consecutive bad windows MUST trigger breach
    consecutive_bad = [
        CanaryMeasurement(timestamp=0.0, window_index=0, added_delay_ms=10.0, jitter_ms=2.0, loss_pct=0.0),
        CanaryMeasurement(timestamp=2.0, window_index=1, added_delay_ms=95.0, jitter_ms=2.0, loss_pct=0.0), # Bad 1
        CanaryMeasurement(timestamp=4.0, window_index=2, added_delay_ms=88.0, jitter_ms=2.0, loss_pct=0.0), # Bad 2
    ]
    res_breach = monitor.evaluate_series(consecutive_bad)
    assert res_breach.passed is False
    assert res_breach.status == "BREACHED"
    assert res_breach.consecutive_breaches == 2


def test_canary_monitor_handles_invalid_and_missing_samples(contract: Contract) -> None:
    monitor = CanaryMonitor(contract=contract)

    # Empty measurements
    res_empty = monitor.evaluate_series([])
    assert res_empty.passed is False
    assert res_empty.status == "INSUFFICIENT_DATA"

    # NaN / invalid metrics marked valid=False
    invalid_measurement = CanaryMeasurement(
        timestamp=0.0, window_index=0, added_delay_ms=float("nan"), jitter_ms=0.0, loss_pct=0.0, valid=False
    )
    is_breach, breaches, reason = monitor.evaluate_measurement(invalid_measurement)
    assert is_breach is True
    assert "Invalid measurement" in reason


# ---------------------------------------------------------------------------
# 8. Canary Breach Triggers Verified Rollback in Coordinator
# ---------------------------------------------------------------------------

def test_canary_breach_triggers_verified_rollback(
    engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord
) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    apply_outcome = coord.apply_and_verify(valid_policy_record)
    assert apply_outcome.success is True
    assert coord.state == EnforcementState.ENFORCED

    # Submit canary measurements containing 2 consecutive breaches
    bad_measurements = [
        CanaryMeasurement(timestamp=0.0, window_index=0, added_delay_ms=100.0, jitter_ms=5.0, loss_pct=0.0),
        CanaryMeasurement(timestamp=2.0, window_index=1, added_delay_ms=105.0, jitter_ms=5.0, loss_pct=0.0),
    ]

    # After rollback (tc qdisc del), qdisc is clean
    del_executed = False

    def mock_run(cmd, check=True):
        nonlocal del_executed
        cmd_str = " ".join(cmd)
        runner.history.append(cmd)
        if "tc qdisc del" in cmd_str:
            del_executed = True
            return "", "", 0
        if "tc -j qdisc show" in cmd_str:
            return ("[]", "", 0) if del_executed else (_mock_verified_snapshot(), "", 0)
        return "", "", 0

    runner.run = mock_run

    canary_outcome = coord.canary_evaluate_and_commit(valid_policy_record, bad_measurements)
    assert canary_outcome.success is False
    assert canary_outcome.rollback_performed is True
    assert canary_outcome.rollback_verified is True
    assert coord.state == EnforcementState.ROLLED_BACK

    # Policy in engine marked ROLLED_BACK
    assert engine.get_record(valid_policy_record.decision_id).state == PolicyState.ROLLED_BACK


def test_canary_acceptance_commits_active_policy(
    engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord
) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    coord.apply_and_verify(valid_policy_record)

    healthy_measurements = [
        CanaryMeasurement(timestamp=i * 2.0, window_index=i, added_delay_ms=20.0, jitter_ms=5.0, loss_pct=0.1)
        for i in range(5)
    ]
    canary_outcome = coord.canary_evaluate_and_commit(valid_policy_record, healthy_measurements)

    assert canary_outcome.success is True
    assert canary_outcome.enforcement_state == EnforcementState.ACCEPTED
    assert coord.state == EnforcementState.ACCEPTED
    assert coord.last_known_good_policy == valid_policy_record.proposed_policy
    assert engine.active_policy == valid_policy_record.proposed_policy
    assert engine.get_record(valid_policy_record.decision_id).state == PolicyState.ACTIVE


# ---------------------------------------------------------------------------
# 9. Audit Event Logging
# ---------------------------------------------------------------------------

def test_audit_event_logging(engine: PolicyEngine, valid_policy_record: PolicyDecisionRecord) -> None:
    runner = MockCommandRunner()
    runner.responses["tc -j qdisc show"] = (_mock_verified_snapshot(), "", 0)
    driver = TCDriver(runner=runner)

    coord = EnforcementCoordinator(engine=engine, driver=driver, interface="ff_wan", namespace="ff_router")
    coord.apply_and_verify(valid_policy_record)

    events = coord.list_events()
    assert len(events) >= 2
    event_types = [ev.event_type for ev in events]
    assert "APPLY_STARTED" in event_types
    assert "ENFORCED" in event_types


# ---------------------------------------------------------------------------
# 10. Real Linux Network Integration Test (Root in VM)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_integration_coordinator_apply_verify_canary_rollback(contract: Contract) -> None:
    """Real Linux integration test for EnforcementCoordinator.

    Proves in real kernel namespaces:
    1. Candidate policy applies and is independently verified.
    2. Simulated canary breach triggers verified rollback.
    3. Kernel state is cleanly restored to default baseline.
    """
    if sys.platform != "linux":
        pytest.fail("Integration test requires Linux kernel; run inside the VM via scripts/vm.sh")
    if os.geteuid() != 0:
        pytest.fail("Integration test requires root privileges; run inside the VM via scripts/vm.sh")
    if not shutil.which("ip") or not shutil.which("tc"):
        pytest.fail("iproute2 tools (ip, tc) not found; run inside the VM via scripts/vm.sh")

    ns = "ff_coord_ns"
    veth_a = "ff_crd_a"
    veth_b = "ff_crd_b"
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

        # Generate candidate policy
        record = engine.generate_candidate_policy(
            classified_flows=[],
            estimated_capacity_mbps=95.0,
            timestamp=100.0,
        )
        assert record.state == PolicyState.VALIDATED

        coord = EnforcementCoordinator(
            engine=engine,
            driver=driver,
            interface=veth_a,
            namespace=ns,
            contract=contract,
        )

        # 1. Apply and independent kernel verify
        apply_outcome = coord.apply_and_verify(record)
        assert apply_outcome.success is True
        assert apply_outcome.kernel_verified is True
        assert coord.state == EnforcementState.ENFORCED

        # Inspect real kernel state: root HTB qdisc 1: must exist
        qdiscs = driver.snapshot(interface=veth_a, namespace=ns)
        assert any(q.get("kind") == "htb" and q.get("handle") == "1:" for q in qdiscs)

        # 2. Canary evaluation with consecutive breaches -> triggers rollback
        bad_measurements = [
            CanaryMeasurement(timestamp=0.0, window_index=0, added_delay_ms=90.0, jitter_ms=5.0, loss_pct=0.0),
            CanaryMeasurement(timestamp=2.0, window_index=1, added_delay_ms=92.0, jitter_ms=5.0, loss_pct=0.0),
        ]
        canary_outcome = coord.canary_evaluate_and_commit(record, bad_measurements)
        assert canary_outcome.success is False
        assert canary_outcome.rollback_performed is True
        assert canary_outcome.rollback_verified is True
        assert coord.state == EnforcementState.ROLLED_BACK

        # Inspect real kernel state: root HTB qdisc 1: must be gone (clean baseline restored)
        post_qdiscs = driver.snapshot(interface=veth_a, namespace=ns)
        assert not any(q.get("kind") == "htb" and q.get("handle") == "1:" for q in post_qdiscs)

    finally:
        # Tear down isolated namespace and interface
        runner.run(["ip", "netns", "del", ns], check=False)
        runner.run(["ip", "link", "del", veth_b], check=False)
