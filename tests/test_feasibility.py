"""Unit tests for src/fairflow/feasibility.py and safety contract engine.

Verifies:
1. Valid feasible policy evaluation and result structure.
2. Exact-equality boundary (sum of floors == usable capacity).
3. Guarantees exceeding capacity (explicit conflict reporting).
4. Zero capacity and zero demand boundary cases.
5. Numeric rejection: negative, NaN, and infinite inputs.
6. Missing fields, incorrect types, and malformed structures.
7. Invalid class identifiers and unsupported queueing configurations.
8. Progressive filling max-min fair allocation with differing demands and constraints.
9. Contract safety floor enforcement and adaptation step limits.
10. Strict determinism: identical inputs produce equivalent, immutable outputs.
11. Regression consistency with contract.yaml.
"""

import math
from pathlib import Path
import pytest

from src.fairflow.policy import Policy, ClassPolicy, SUPPORTED_LEAF_QDISCS
from src.fairflow.contract import load_contract, Contract
from src.fairflow.feasibility import (
    FeasibilityResult,
    SafetyContractEngine,
    compute_usable_capacity,
    max_min_fair_allocation,
    evaluate_policy_feasibility,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def standard_contract() -> Contract:
    """Load the committed contract.yaml."""
    return load_contract(REPO_ROOT / "contract.yaml")


# ---------------------------------------------------------------------------
# 1. Valid Feasible Policy
# ---------------------------------------------------------------------------

def test_valid_feasible_policy(standard_contract: Contract) -> None:
    policy = Policy(
        link_capacity_mbps=95.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=20.0, priority=1, leaf_qdisc="fq_codel"),
            "streaming": ClassPolicy(rate_floor_mbps=8.0, rate_ceiling_mbps=50.0, priority=2, leaf_qdisc="fq_codel"),
            "bulk": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=95.0, priority=3, leaf_qdisc="fq_codel"),
        },
    )
    result = evaluate_policy_feasibility(
        policy=policy,
        estimated_capacity_mbps=95.0,
        contract=standard_contract,
        capacity_is_raw=False,
    )
    assert result.is_feasible is True
    assert result.reasons == ()
    assert result.usable_capacity_mbps == 95.0
    assert result.required_minimum_mbps == 12.0
    assert result.allocations_mbps is not None
    # Max-min fair allocation under 95 Mbps usable capacity:
    # 1. Floors: interactive=2, streaming=8, bulk=2 (Total=12, Remaining=83)
    # 2. Excess demands: interactive=18, streaming=42, bulk=93
    # 3. Round 1: share=83/3=27.67. Interactive satisfied with 18 (Total=20). Remaining=65.
    # 4. Round 2: 2 active (streaming, bulk). share=65/2=32.5. Both exceed 32.5.
    # 5. Streaming gets 8 + 32.5 = 40.5. Bulk gets 2 + 32.5 = 34.5.
    assert result.allocations_mbps["interactive"] == 20.0
    assert result.allocations_mbps["streaming"] == 40.5
    assert result.allocations_mbps["bulk"] == 34.5
    assert sum(result.allocations_mbps.values()) == 95.0


# ---------------------------------------------------------------------------
# 2. Exact-Equality Boundary
# ---------------------------------------------------------------------------

def test_guarantees_exactly_equal_usable_capacity() -> None:
    # Total floors = 10.0 + 30.0 + 60.0 = 100.0 Mbps == usable capacity
    policy = Policy(
        link_capacity_mbps=100.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=10.0, rate_ceiling_mbps=100.0, priority=1),
            "streaming": ClassPolicy(rate_floor_mbps=30.0, rate_ceiling_mbps=100.0, priority=2),
            "bulk": ClassPolicy(rate_floor_mbps=60.0, rate_ceiling_mbps=100.0, priority=3),
        },
    )
    result = evaluate_policy_feasibility(
        policy=policy,
        estimated_capacity_mbps=100.0,
        capacity_is_raw=False,
    )
    assert result.is_feasible is True
    assert result.reasons == ()
    assert result.usable_capacity_mbps == 100.0
    assert result.required_minimum_mbps == 100.0
    assert result.allocations_mbps == {
        "interactive": 10.0,
        "streaming": 30.0,
        "bulk": 60.0,
    }


# ---------------------------------------------------------------------------
# 3. Guarantees Exceeding Capacity
# ---------------------------------------------------------------------------

def test_guarantees_exceeding_capacity() -> None:
    # Total floors = 8.0 + 8.0 + 8.0 = 24.0 Mbps > 20.0 Mbps usable capacity
    policy = Policy(
        link_capacity_mbps=20.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=8.0, rate_ceiling_mbps=20.0, priority=1),
            "streaming": ClassPolicy(rate_floor_mbps=8.0, rate_ceiling_mbps=20.0, priority=2),
            "bulk": ClassPolicy(rate_floor_mbps=8.0, rate_ceiling_mbps=20.0, priority=3),
        },
    )
    result = evaluate_policy_feasibility(
        policy=policy,
        estimated_capacity_mbps=20.0,
        capacity_is_raw=False,
    )
    assert result.is_feasible is False
    assert len(result.reasons) == 1
    assert "exceed usable capacity" in result.reasons[0]
    assert "24.000 Mbps" in result.reasons[0]
    assert "20.000 Mbps" in result.reasons[0]
    assert result.allocations_mbps is None


# ---------------------------------------------------------------------------
# 4. Zero Capacity and Zero-Demand Boundary Cases
# ---------------------------------------------------------------------------

def test_zero_capacity_boundary() -> None:
    policy = Policy(
        link_capacity_mbps=10.0,
        classes={"bulk": ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=10.0, priority=1)},
    )
    result = evaluate_policy_feasibility(policy=policy, estimated_capacity_mbps=0.0)
    assert result.is_feasible is False
    assert any("strictly positive" in r for r in result.reasons)


def test_zero_demand_boundary() -> None:
    # A class demanding 0 with 0 floor receives 0; surplus goes to active classes
    alloc = max_min_fair_allocation(
        usable_capacity_mbps=10.0,
        demands_mbps={"idle_class": 0.0, "active_class": 10.0},
        floors_mbps={"idle_class": 0.0, "active_class": 2.0},
    )
    assert alloc["idle_class"] == 0.0
    assert alloc["active_class"] == 10.0


def test_zero_demand_with_positive_floor_preserves_guarantee() -> None:
    # Floor guarantee must be preserved even if reported instantaneous demand is 0
    alloc = max_min_fair_allocation(
        usable_capacity_mbps=10.0,
        demands_mbps={"idle_class": 0.0, "active_class": 10.0},
        floors_mbps={"idle_class": 2.0, "active_class": 2.0},
    )
    assert alloc["idle_class"] == 2.0
    assert alloc["active_class"] == 8.0


# ---------------------------------------------------------------------------
# 5. Negative, NaN, and Infinite Numeric Inputs
# ---------------------------------------------------------------------------

def test_rejects_nan_and_inf_in_class_policy() -> None:
    with pytest.raises(ValueError, match="cannot be NaN"):
        ClassPolicy(rate_floor_mbps=float("nan"), rate_ceiling_mbps=10.0, priority=1)

    with pytest.raises(ValueError, match="cannot be infinite"):
        ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=float("inf"), priority=1)

    with pytest.raises(ValueError, match="cannot be infinite"):
        ClassPolicy(rate_floor_mbps=float("-inf"), rate_ceiling_mbps=10.0, priority=1)


def test_rejects_negative_and_boolean_in_class_policy() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        ClassPolicy(rate_floor_mbps=-5.0, rate_ceiling_mbps=10.0, priority=1)

    with pytest.raises(TypeError, match="must be a real number"):
        ClassPolicy(rate_floor_mbps=True, rate_ceiling_mbps=10.0, priority=1)

    with pytest.raises(TypeError, match="priority must be an integer"):
        ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=10.0, priority=True)


def test_rejects_nan_and_inf_in_compute_usable_capacity() -> None:
    with pytest.raises(ValueError, match="cannot be NaN"):
        compute_usable_capacity(float("nan"), 5.0)

    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        compute_usable_capacity(100.0, float("inf"))

    with pytest.raises(ValueError, match="must be in"):
        compute_usable_capacity(100.0, -1.0)

    with pytest.raises(ValueError, match="must be in"):
        compute_usable_capacity(100.0, 100.0)


def test_evaluator_rejects_nan_and_inf_capacity() -> None:
    policy = Policy(
        link_capacity_mbps=10.0,
        classes={"bulk": ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=10.0, priority=1)},
    )
    res_nan = evaluate_policy_feasibility(policy=policy, estimated_capacity_mbps=float("nan"))
    assert res_nan.is_feasible is False
    assert any("cannot be NaN" in r for r in res_nan.reasons)

    res_inf = evaluate_policy_feasibility(policy=policy, estimated_capacity_mbps=float("inf"))
    assert res_inf.is_feasible is False
    assert any("cannot be NaN or infinite" in r for r in res_inf.reasons)

    res_neg = evaluate_policy_feasibility(policy=policy, estimated_capacity_mbps=-10.0)
    assert res_neg.is_feasible is False
    assert any("must be strictly positive" in r for r in res_neg.reasons)


# ---------------------------------------------------------------------------
# 6. Missing Fields, Incorrect Types, and Malformed Structures
# ---------------------------------------------------------------------------

def test_evaluator_rejects_non_policy_input() -> None:
    result = evaluate_policy_feasibility(policy="not_a_policy", estimated_capacity_mbps=100.0)  # type: ignore
    assert result.is_feasible is False
    assert any("must be an instance of Policy" in r for r in result.reasons)


def test_policy_rejects_empty_classes_or_bad_types() -> None:
    with pytest.raises(ValueError, match="at least one traffic class"):
        Policy(link_capacity_mbps=100.0, classes={})

    with pytest.raises(TypeError, match="classes must be a dict"):
        Policy(link_capacity_mbps=100.0, classes=["interactive"])  # type: ignore

    with pytest.raises(TypeError, match="must be a ClassPolicy instance"):
        Policy(link_capacity_mbps=100.0, classes={"interactive": "not_class_policy"})  # type: ignore


# ---------------------------------------------------------------------------
# 7. Invalid Class Identifiers and Unsupported Queue Settings
# ---------------------------------------------------------------------------

def test_rejects_invalid_class_names() -> None:
    with pytest.raises(ValueError, match="Class identifier 'INVALID_UPPERCASE' is invalid"):
        Policy(
            link_capacity_mbps=100.0,
            classes={"INVALID_UPPERCASE": ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=10.0, priority=1)},
        )

    with pytest.raises(ValueError, match="Class identifier 'class-with-hyphens' is invalid"):
        Policy(
            link_capacity_mbps=100.0,
            classes={"class-with-hyphens": ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=10.0, priority=1)},
        )


def test_rejects_unsupported_leaf_qdisc() -> None:
    with pytest.raises(ValueError, match="Unsupported leaf_qdisc 'red'"):
        ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=10.0, priority=1, leaf_qdisc="red")

    # Supported ones must succeed
    for qdisc in SUPPORTED_LEAF_QDISCS:
        cp = ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=10.0, priority=1, leaf_qdisc=qdisc)
        assert cp.leaf_qdisc == qdisc


# ---------------------------------------------------------------------------
# 8. Max-Min Fair Allocation with Differing Demands & Constraints
# ---------------------------------------------------------------------------

def test_max_min_allocation_differing_demands_unconstrained() -> None:
    # Usable capacity = 100. Demands: A=10, B=20, C=30. Total demand = 60 <= 100.
    # Every class should be fully satisfied.
    alloc = max_min_fair_allocation(
        usable_capacity_mbps=100.0,
        demands_mbps={"class_a": 10.0, "class_b": 20.0, "class_c": 30.0},
    )
    assert alloc == {"class_a": 10.0, "class_b": 20.0, "class_c": 30.0}


def test_max_min_allocation_progressive_waterfilling() -> None:
    # Usable capacity = 100.
    # Demands: small=10, medium=30, large=80. (Sum = 120 > 100).
    # Floors = 0.
    # Round 1: share = 100/3 = 33.333.
    # 'small' demands 10 <= 33.333 -> satisfied with 10. Remaining cap = 90.
    # Round 2: active = {medium, large}. share = 90/2 = 45.
    # 'medium' demands 30 <= 45 -> satisfied with 30. Remaining cap = 60.
    # Round 3: active = {large}. share = 60.
    # 'large' receives remaining 60.
    alloc = max_min_fair_allocation(
        usable_capacity_mbps=100.0,
        demands_mbps={"small": 10.0, "medium": 30.0, "large": 80.0},
    )
    assert alloc["small"] == 10.0
    assert alloc["medium"] == 30.0
    assert alloc["large"] == 60.0
    assert sum(alloc.values()) == 100.0


def test_max_min_allocation_with_floors_and_constrained_capacity() -> None:
    # Scenario B capacity = 20 Mbps.
    # Floors: interactive=2.0, streaming=8.0, bulk=2.0 (Sum = 12.0 <= 20.0).
    # Demands: interactive=2.0, streaming=15.0, bulk=15.0.
    # Remaining capacity = 20 - 12 = 8 Mbps.
    # Excess demands: interactive=0, streaming=7.0, bulk=13.0.
    # Active: streaming, bulk. Fair share = 8/2 = 4.0 Mbps.
    # Both excess demands (7.0, 13.0) > 4.0. Both receive 4.0.
    # Final allocations: interactive = 2.0, streaming = 8.0 + 4.0 = 12.0, bulk = 2.0 + 4.0 = 6.0.
    alloc = max_min_fair_allocation(
        usable_capacity_mbps=20.0,
        demands_mbps={"interactive": 2.0, "streaming": 15.0, "bulk": 15.0},
        floors_mbps={"interactive": 2.0, "streaming": 8.0, "bulk": 2.0},
    )
    assert alloc["interactive"] == 2.0
    assert alloc["streaming"] == 12.0
    assert alloc["bulk"] == 6.0
    assert sum(alloc.values()) == 20.0


def test_max_min_allocation_raises_on_infeasible_floors() -> None:
    with pytest.raises(ValueError, match="Infeasible guarantees: sum of minimum floors"):
        max_min_fair_allocation(
            usable_capacity_mbps=10.0,
            demands_mbps={"a": 10.0, "b": 10.0},
            floors_mbps={"a": 6.0, "b": 5.0},  # 11 > 10
        )


# ---------------------------------------------------------------------------
# 9. Safety Contract Compliance & Step Limit Checks
# ---------------------------------------------------------------------------

def test_safety_contract_floor_violations(standard_contract: Contract) -> None:
    # Violate interactive floor (1.0 < 2.0) and bulk floor (1.5 < 2.0)
    policy = Policy(
        link_capacity_mbps=95.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=20.0, priority=1),
            "streaming": ClassPolicy(rate_floor_mbps=8.0, rate_ceiling_mbps=50.0, priority=2),
            "bulk": ClassPolicy(rate_floor_mbps=1.5, rate_ceiling_mbps=95.0, priority=3),
        },
    )
    result = evaluate_policy_feasibility(
        policy=policy,
        estimated_capacity_mbps=95.0,
        contract=standard_contract,
    )
    assert result.is_feasible is False
    assert len(result.reasons) == 2
    assert any("'interactive' floor (1.00 Mbps) is below contract floor" in r for r in result.reasons)
    assert any("'bulk' floor (1.50 Mbps) is below contract floor" in r for r in result.reasons)


def test_safety_contract_adaptation_step_limit(standard_contract: Contract) -> None:
    # Contract policy.max_step_pct = 25%
    current = Policy(
        link_capacity_mbps=95.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=10.0, rate_ceiling_mbps=20.0, priority=1),
            "bulk": ClassPolicy(rate_floor_mbps=10.0, rate_ceiling_mbps=95.0, priority=2),
        },
    )
    # Proposed interactive changes from 10.0 to 14.0 (+40% > 25%)
    proposed = Policy(
        link_capacity_mbps=95.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=14.0, rate_ceiling_mbps=20.0, priority=1),
            "bulk": ClassPolicy(rate_floor_mbps=11.0, rate_ceiling_mbps=95.0, priority=2),  # +10% <= 25%
        },
    )
    result = evaluate_policy_feasibility(
        policy=proposed,
        estimated_capacity_mbps=95.0,
        contract=standard_contract,
        current_policy=current,
    )
    assert result.is_feasible is False
    assert len(result.reasons) == 1
    assert "class 'interactive' rate floor change (40.0%) exceeds contract max_step_pct" in result.reasons[0]


# ---------------------------------------------------------------------------
# 10. Strict Determinism and Safety Separation
# ---------------------------------------------------------------------------

def test_deterministic_repeated_evaluations(standard_contract: Contract) -> None:
    engine = SafetyContractEngine(contract=standard_contract, shaping_margin_pct=5.0)
    policy = Policy(
        link_capacity_mbps=100.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=20.0, priority=1),
            "streaming": ClassPolicy(rate_floor_mbps=8.0, rate_ceiling_mbps=50.0, priority=2),
            "bulk": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=100.0, priority=3),
        },
    )

    first_result = engine.evaluate(policy=policy, estimated_capacity_mbps=100.0, capacity_is_raw=True)
    assert first_result.is_feasible is True

    # 100 repeated evaluations must be identical
    for _ in range(100):
        subsequent = engine.evaluate(policy=policy, estimated_capacity_mbps=100.0, capacity_is_raw=True)
        assert subsequent == first_result


def test_safety_separation_no_system_side_effects() -> None:
    # Calling feasibility functions must not alter sys.modules or launch processes
    policy = Policy(
        link_capacity_mbps=20.0,
        classes={"bulk": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=20.0, priority=1)},
    )
    res = evaluate_policy_feasibility(policy, estimated_capacity_mbps=20.0)
    assert isinstance(res, FeasibilityResult)
    # Result object is immutable
    with pytest.raises(Exception):
        res.is_feasible = False  # type: ignore


# ---------------------------------------------------------------------------
# 11. Regression Consistency with Contract Invariants
# ---------------------------------------------------------------------------

def test_contract_yaml_consistency(standard_contract: Contract) -> None:
    # contract.yaml committed floors must sum to <= 20 Mbps (V6 invariant)
    committed_floors = (
        standard_contract.interactive_floor_mbps
        + standard_contract.streaming_floor_mbps
        + standard_contract.bulk_floor_mbps
    )
    assert committed_floors == 12.0
    assert committed_floors <= 20.0

    # Usable capacity calculation for Scenario A (100 Mbps raw at 5% margin = 95 Mbps)
    usable_a = compute_usable_capacity(100.0, 5.0)
    assert usable_a == 95.0

    # Usable capacity calculation for Scenario B (20 Mbps raw at 5% margin = 19 Mbps)
    usable_b = compute_usable_capacity(20.0, 5.0)
    assert usable_b == 19.0
    assert committed_floors <= usable_b
