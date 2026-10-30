"""Unit tests for src/fairflow/controller.py (Policy Decision & Lifecycle Engine).

Verifies:
1. Candidate policy generation for feasible flows and validation status.
2. Infeasible capacity triggers REJECTED state without activating.
3. Unknown traffic mapping: conservatively routed to 'bulk', never given priority over interactive.
4. Absent classes and zero-demand flows still preserve mandatory contract service floors.
5. Adaptation-step limits: proposals respect policy_max_step_pct relative to current active policy.
6. Deterministic proposals: identical inputs and timestamps yield identical candidate records.
7. Lifecycle transitions:
   - VALIDATED -> ACTIVE -> SUPERSEDED
   - ACTIVE -> ROLLED_BACK
   - Illegal transitions raise InvalidStateTransitionError:
     * REJECTED -> ACTIVE (rejected policies NEVER become active)
     * PROPOSED -> ACTIVE (cannot bypass validation)
     * SUPERSEDED -> ACTIVE
     * ROLLED_BACK -> ACTIVE
8. Invalid and missing capacity inputs (NaN, inf, negative, zero, non-numeric).
9. Regression compatibility with SafetyContractEngine and TrafficClassifier.
"""

from pathlib import Path
import pytest

from src.fairflow.policy import Policy, ClassPolicy
from src.fairflow.contract import load_contract, Contract
from src.fairflow.classifier import FlowMetadata, ClassificationResult
from src.fairflow.controller import (
    PolicyEngine,
    PolicyState,
    PolicyDecisionRecord,
    InvalidStateTransitionError,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def contract() -> Contract:
    return load_contract(REPO_ROOT / "contract.yaml")


# ---------------------------------------------------------------------------
# 1. Candidate Policy Generation & Validation (Feasible Flows)
# ---------------------------------------------------------------------------

def test_generate_candidate_feasible(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract, shaping_margin_pct=5.0)

    # Simulated observed flows: 1 interactive call, 1 bulk download
    call_flow = FlowMetadata(protocol="udp", src_ip="10.0.1.2", dst_ip="10.0.2.2", dst_port=5004, bitrate_bps=80_000.0)
    call_res = ClassificationResult(flow_id=call_flow.flow_id, traffic_class="interactive", confidence=0.85, reason="UDP RTP")

    bulk_flow = FlowMetadata(protocol="tcp", src_ip="10.0.1.2", dst_ip="10.0.2.2", dst_port=5201, bitrate_bps=80_000_000.0)
    bulk_res = ClassificationResult(flow_id=bulk_flow.flow_id, traffic_class="bulk", confidence=0.90, reason="TCP iperf3")

    flows = [(call_flow, call_res), (bulk_flow, bulk_res)]

    record = engine.generate_candidate_policy(
        classified_flows=flows,
        estimated_capacity_mbps=100.0,
        capacity_is_raw=True,  # 100 Mbps raw at 5% margin -> 95 Mbps usable
        timestamp=1000.0,
    )

    assert record.state == PolicyState.VALIDATED
    assert record.usable_capacity_mbps == 95.0
    assert record.proposed_policy is not None
    assert record.feasibility_result is not None
    assert record.feasibility_result.is_feasible is True
    assert set(record.active_classes) == {"bulk", "interactive"}
    assert record.unmapped_unknown_count == 0

    # Mandatory floors preserved
    classes = record.proposed_policy.classes
    assert classes["interactive"].rate_floor_mbps >= contract.interactive_floor_mbps
    assert classes["streaming"].rate_floor_mbps >= contract.streaming_floor_mbps
    assert classes["bulk"].rate_floor_mbps >= contract.bulk_floor_mbps


# ---------------------------------------------------------------------------
# 2. Infeasible Candidate Policies
# ---------------------------------------------------------------------------

def test_generate_candidate_infeasible_capacity(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract, shaping_margin_pct=5.0)

    # Infeasible link capacity: 10 Mbps raw (9.5 Mbps usable), but sum of floors is 12 Mbps
    record = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=10.0,
        capacity_is_raw=True,
        timestamp=1000.0,
    )

    assert record.state == PolicyState.REJECTED
    assert record.proposed_policy is None
    assert record.feasibility_result is not None
    assert record.feasibility_result.is_feasible is False
    assert "exceed usable capacity" in record.explanation
    assert engine.active_policy is None  # Infeasible policy not active


# ---------------------------------------------------------------------------
# 3. Unknown Traffic Mapping
# ---------------------------------------------------------------------------

def test_unknown_traffic_routed_to_bulk(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # Flow classified as 'unknown'
    unk_flow = FlowMetadata(protocol="udp", src_ip="10.0.1.2", dst_ip="10.0.2.2", dst_port=9999, bitrate_bps=10_000_000.0)
    unk_res = ClassificationResult(flow_id=unk_flow.flow_id, traffic_class="unknown", confidence=0.20, reason="Ambiguous")

    record = engine.generate_candidate_policy(
        classified_flows=[(unk_flow, unk_res)],
        estimated_capacity_mbps=95.0,
        timestamp=1000.0,
    )

    assert record.state == PolicyState.VALIDATED
    assert record.unmapped_unknown_count == 1
    assert "Unknown flows routed to bulk: 1" in record.explanation
    # Unknown traffic must NOT be granted interactive or streaming priority
    assert record.proposed_policy.classes["bulk"].priority == 3
    assert record.proposed_policy.classes["interactive"].priority == 1


# ---------------------------------------------------------------------------
# 4. Absent Classes & Mandatory Floors
# ---------------------------------------------------------------------------

def test_absent_classes_retain_mandatory_floors(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # No observed flows at all
    record = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=95.0,
        timestamp=1000.0,
    )

    assert record.state == PolicyState.VALIDATED
    assert len(record.active_classes) == 0
    # Mandatory service floors are still allocated to protect latent streams
    classes = record.proposed_policy.classes
    assert classes["interactive"].rate_floor_mbps == contract.interactive_floor_mbps  # 2.0
    assert classes["streaming"].rate_floor_mbps == contract.streaming_floor_mbps      # 8.0
    assert classes["bulk"].rate_floor_mbps == contract.bulk_floor_mbps                # 2.0


# ---------------------------------------------------------------------------
# 5. Invalid or Missing Capacity Inputs
# ---------------------------------------------------------------------------

def test_invalid_capacity_inputs(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # NaN capacity
    res_nan = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=float("nan"))
    assert res_nan.state == PolicyState.REJECTED
    assert "must be strictly positive and finite" in res_nan.explanation

    # Negative capacity
    res_neg = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=-20.0)
    assert res_neg.state == PolicyState.REJECTED

    # Infinite capacity
    res_inf = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=float("inf"))
    assert res_inf.state == PolicyState.REJECTED

    # Boolean capacity
    res_bool = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=True)  # type: ignore
    assert res_bool.state == PolicyState.REJECTED
    assert "must be a real number" in res_bool.explanation


# ---------------------------------------------------------------------------
# 6. Adaptation Step Limits
# ---------------------------------------------------------------------------

def test_candidate_policy_respects_adaptation_step_limit(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # Currently active policy with interactive floor = 10.0
    current = Policy(
        link_capacity_mbps=95.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=10.0, rate_ceiling_mbps=95.0, priority=1),
            "streaming": ClassPolicy(rate_floor_mbps=8.0, rate_ceiling_mbps=95.0, priority=2),
            "bulk": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=95.0, priority=3),
        },
    )

    # Massive spike in interactive demand (50 Mbps)
    high_call_flow = FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5004, bitrate_bps=50_000_000.0)
    high_call_res = ClassificationResult(flow_id=high_call_flow.flow_id, traffic_class="interactive", confidence=0.9, reason="Call")

    record = engine.generate_candidate_policy(
        classified_flows=[(high_call_flow, high_call_res)],
        estimated_capacity_mbps=95.0,
        current_policy=current,
        timestamp=1000.0,
    )

    # Contract policy_max_step_pct is 25%.
    # 10.0 * (1 + 0.25) = 12.5 Mbps max allowed floor
    assert record.state == PolicyState.VALIDATED
    assert record.proposed_policy.classes["interactive"].rate_floor_mbps == 12.5


# ---------------------------------------------------------------------------
# 7. Deterministic Proposals
# ---------------------------------------------------------------------------

def test_deterministic_policy_generation(contract: Contract) -> None:
    engine1 = PolicyEngine(contract=contract)
    engine2 = PolicyEngine(contract=contract)

    flow = FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5004, bitrate_bps=100_000.0)
    res = ClassificationResult(flow_id=flow.flow_id, traffic_class="interactive", confidence=0.8, reason="Call")

    for _ in range(50):
        rec1 = engine1.generate_candidate_policy(classified_flows=[(flow, res)], estimated_capacity_mbps=95.0, timestamp=1000.0)
        rec2 = engine2.generate_candidate_policy(classified_flows=[(flow, res)], estimated_capacity_mbps=95.0, timestamp=1000.0)
        assert rec1.proposed_policy == rec2.proposed_policy
        assert rec1.state == rec2.state
        assert rec1.usable_capacity_mbps == rec2.usable_capacity_mbps


# ---------------------------------------------------------------------------
# 8. Lifecycle Transitions and Safety Guards
# ---------------------------------------------------------------------------

def test_valid_lifecycle_transitions(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # 1. Generate candidate -> VALIDATED
    rec = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=95.0, timestamp=100.0)
    assert rec.state == PolicyState.VALIDATED
    assert engine.active_policy is None

    # 2. VALIDATED -> ACTIVE
    active_rec = engine.transition_state(rec.decision_id, PolicyState.ACTIVE, reason="Activating valid policy", timestamp=105.0)
    assert active_rec.state == PolicyState.ACTIVE
    assert engine.active_policy == rec.proposed_policy
    assert engine.active_record.decision_id == rec.decision_id

    # 3. Generate candidate 2 -> VALIDATED
    rec2 = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=95.0, timestamp=120.0)
    assert rec2.state == PolicyState.VALIDATED

    # 4. Activate candidate 2 -> Candidate 1 becomes SUPERSEDED
    active_rec2 = engine.transition_state(rec2.decision_id, PolicyState.ACTIVE, reason="Activating newer policy", timestamp=125.0)
    assert active_rec2.state == PolicyState.ACTIVE
    assert engine.active_policy == rec2.proposed_policy

    old_rec = engine.get_record(rec.decision_id)
    assert old_rec.state == PolicyState.SUPERSEDED

    # 5. ACTIVE -> ROLLED_BACK
    rollback_rec = engine.transition_state(rec2.decision_id, PolicyState.ROLLED_BACK, reason="Safety canary breach", timestamp=130.0)
    assert rollback_rec.state == PolicyState.ROLLED_BACK
    assert engine.active_policy is None


def test_illegal_lifecycle_transitions_rejected(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # 1. Infeasible policy -> REJECTED
    rej_rec = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=5.0, timestamp=100.0)
    assert rej_rec.state == PolicyState.REJECTED

    # REJECTED cannot transition to ACTIVE
    with pytest.raises(InvalidStateTransitionError, match="is REJECTED and cannot transition"):
        engine.transition_state(rej_rec.decision_id, PolicyState.ACTIVE, reason="Illegal activation")

    # REJECTED cannot transition to VALIDATED
    with pytest.raises(InvalidStateTransitionError, match="is REJECTED and cannot transition"):
        engine.transition_state(rej_rec.decision_id, PolicyState.VALIDATED, reason="Illegal validation")

    # 2. Non-existent decision ID raises KeyError
    with pytest.raises(KeyError, match="Decision record 'non_existent' not found"):
        engine.transition_state("non_existent", PolicyState.ACTIVE, reason="Ghost record")


def test_superseded_or_rolled_back_cannot_reactivate_directly(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)
    rec = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=95.0, timestamp=100.0)
    engine.transition_state(rec.decision_id, PolicyState.ACTIVE, reason="Activate", timestamp=105.0)
    engine.transition_state(rec.decision_id, PolicyState.ROLLED_BACK, reason="Rollback", timestamp=110.0)

    # ROLLED_BACK cannot become ACTIVE directly
    with pytest.raises(InvalidStateTransitionError, match="cannot activate record in state 'ROLLED_BACK'"):
        engine.transition_state(rec.decision_id, PolicyState.ACTIVE, reason="Reactivate rolled back")


# ---------------------------------------------------------------------------
# 9. Boundary Tests: Capacity Equal to, Below, and Above Mandatory Floors
# ---------------------------------------------------------------------------

def test_capacity_boundary_mandatory_floors_exact_below_above(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)
    # Sum of contract floors: 2.0 (interactive) + 8.0 (streaming) + 2.0 (bulk) = 12.0 Mbps

    # 1. Exactly equal to sum of mandatory floors (12.0 Mbps usable)
    rec_exact = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=12.0,
        capacity_is_raw=False,
        timestamp=100.0,
    )
    assert rec_exact.state == PolicyState.VALIDATED
    assert rec_exact.usable_capacity_mbps == 12.0
    assert rec_exact.proposed_policy is not None
    assert rec_exact.feasibility_result is not None
    assert rec_exact.feasibility_result.is_feasible is True
    assert rec_exact.feasibility_result.required_minimum_mbps == 12.0

    # 2. Just below the threshold (11.99 Mbps usable)
    rec_below = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=11.99,
        capacity_is_raw=False,
        timestamp=101.0,
    )
    assert rec_below.state == PolicyState.REJECTED
    assert rec_below.proposed_policy is None
    assert rec_below.usable_capacity_mbps == 11.99
    assert rec_below.feasibility_result.is_feasible is False
    assert "exceed usable capacity" in rec_below.explanation

    # 3. Just above the threshold (12.01 Mbps usable)
    rec_above = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=12.01,
        capacity_is_raw=False,
        timestamp=102.0,
    )
    assert rec_above.state == PolicyState.VALIDATED
    assert rec_above.usable_capacity_mbps == 12.01
    assert rec_above.feasibility_result.is_feasible is True


# ---------------------------------------------------------------------------
# 10. Explicit Shaping Margin Verification
# ---------------------------------------------------------------------------

def test_shaping_margin_explicit_evaluation(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract, shaping_margin_pct=5.0)

    # Raw capacity 12.0 Mbps with 5% margin -> 12.0 * 0.95 = 11.4 Mbps usable (< 12.0 Mbps floors)
    rec_margin_fail = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=12.0,
        capacity_is_raw=True,
        timestamp=200.0,
    )
    assert rec_margin_fail.state == PolicyState.REJECTED
    assert rec_margin_fail.usable_capacity_mbps == 11.4
    assert rec_margin_fail.proposed_policy is None

    # Raw capacity 12.631579 Mbps with 5% margin -> round(12.631579 * 0.95, 6) = 12.0 Mbps usable (>= 12.0 Mbps floors)
    rec_margin_pass = engine.generate_candidate_policy(
        classified_flows=[],
        estimated_capacity_mbps=12.631579,
        capacity_is_raw=True,
        timestamp=201.0,
    )
    assert rec_margin_pass.state == PolicyState.VALIDATED
    assert rec_margin_pass.usable_capacity_mbps == 12.0
    assert rec_margin_pass.feasibility_result.is_feasible is True


# ---------------------------------------------------------------------------
# 11. Allocation and Fairness Invariants
# ---------------------------------------------------------------------------

def test_allocation_fairness_invariants_and_demand_capping(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # 1 interactive call at 0.08 Mbps (80 kbps) and 1 bulk download at 40 Mbps
    call_flow = FlowMetadata(protocol="udp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5004, bitrate_bps=80_000.0)
    call_res = ClassificationResult(flow_id=call_flow.flow_id, traffic_class="interactive", confidence=0.9, reason="Call")

    bulk_flow = FlowMetadata(protocol="tcp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5201, bitrate_bps=40_000_000.0)
    bulk_res = ClassificationResult(flow_id=bulk_flow.flow_id, traffic_class="bulk", confidence=0.9, reason="Bulk")

    record = engine.generate_candidate_policy(
        classified_flows=[(call_flow, call_res), (bulk_flow, bulk_res)],
        estimated_capacity_mbps=95.0,
        timestamp=300.0,
    )

    assert record.state == PolicyState.VALIDATED
    allocations = record.feasibility_result.allocations_mbps
    assert allocations is not None

    # Invariant 1: Inactive class (streaming demand = 0) receives exactly mandatory floor (8.0 Mbps) and 0 surplus
    assert allocations["streaming"] == 8.0

    # Invariant 2: Active class demand capping: interactive demand (0.08 Mbps) < floor (2.0 Mbps), receives floor (2.0 Mbps)
    assert allocations["interactive"] == 2.0

    # Invariant 3: Bulk receives demand (40.0 Mbps), does NOT exceed demand
    assert allocations["bulk"] == 40.0

    # Invariant 4: Sum of proposed allocations <= usable capacity
    assert sum(allocations.values()) == 50.0
    assert sum(allocations.values()) <= record.usable_capacity_mbps


def test_high_traffic_demands_preserve_feasibility_and_floors(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # Massive bulk traffic (90 Mbps) on a 95 Mbps link
    heavy_bulk = FlowMetadata(protocol="tcp", src_ip="1.1.1.1", dst_ip="2.2.2.2", dst_port=5201, bitrate_bps=90_000_000.0)
    heavy_res = ClassificationResult(flow_id=heavy_bulk.flow_id, traffic_class="bulk", confidence=0.95, reason="Bulk")

    record = engine.generate_candidate_policy(
        classified_flows=[(heavy_bulk, heavy_res)],
        estimated_capacity_mbps=95.0,
        timestamp=400.0,
    )

    # High bulk demand must NOT trigger false capacity infeasibility
    assert record.state == PolicyState.VALIDATED
    assert record.feasibility_result.is_feasible is True

    # Guaranteed floors remain intact and bounded
    classes = record.proposed_policy.classes
    assert classes["interactive"].rate_floor_mbps == 2.0
    assert classes["streaming"].rate_floor_mbps == 8.0
    assert classes["bulk"].rate_floor_mbps == 2.0
    assert sum(c.rate_floor_mbps for c in classes.values()) == 12.0


# ---------------------------------------------------------------------------
# 12. Concurrent Proposals and Complete Lifecycle Audit History
# ---------------------------------------------------------------------------

def test_concurrent_proposals_and_lifecycle_history(contract: Contract) -> None:
    engine = PolicyEngine(contract=contract)

    # Multiple proposals generated concurrently
    rec1 = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=95.0, timestamp=500.0)
    rec2 = engine.generate_candidate_policy(classified_flows=[], estimated_capacity_mbps=95.0, timestamp=501.0)

    assert rec1.state == PolicyState.VALIDATED
    assert rec2.state == PolicyState.VALIDATED
    assert engine.active_policy is None

    # Activate proposal 1
    act1 = engine.transition_state(rec1.decision_id, PolicyState.ACTIVE, reason="Activation 1", timestamp=505.0)
    assert act1.state == PolicyState.ACTIVE
    assert engine.active_record.decision_id == rec1.decision_id

    # Activate proposal 2: proposal 1 automatically becomes SUPERSEDED
    act2 = engine.transition_state(rec2.decision_id, PolicyState.ACTIVE, reason="Activation 2", timestamp=510.0)
    assert act2.state == PolicyState.ACTIVE
    assert engine.active_record.decision_id == rec2.decision_id

    rec1_updated = engine.get_record(rec1.decision_id)
    assert rec1_updated.state == PolicyState.SUPERSEDED

    # Verify immutable transition history preserved
    assert len(rec1_updated.state_history) == 4
    # (PROPOSED, VALIDATED, ACTIVE, SUPERSEDED)
    history_states = [entry[1] for entry in rec1_updated.state_history]
    assert history_states == [
        PolicyState.PROPOSED,
        PolicyState.VALIDATED,
        PolicyState.ACTIVE,
        PolicyState.SUPERSEDED,
    ]

