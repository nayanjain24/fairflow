"""feasibility.py — Deterministic safety-contract and feasibility engine for FairFlow.

This module provides a pure, deterministic, side-effect-free evaluation engine
governing adaptive QoS policy proposals. It verifies that a proposed Policy:
1. Is structurally sound and free from malformed, negative, NaN, or infinite values.
2. Complies with safety contract floor mandates and adaptation step limits.
3. Is feasible given estimated link capacity (guarantees <= usable capacity).
4. Produces a mathematically rigorous max-min fair rate allocation across active demands.

Safety Invariants:
- Strictly side-effect free: no subprocess calls, no network namespace operations,
  no tc/ip invocations, and no modification of system or persistent state.
- Purely deterministic: identical inputs produce identical, immutable FeasibilityResult outputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, Mapping

from src.fairflow.policy import Policy, ClassPolicy, SUPPORTED_LEAF_QDISCS, VALID_CLASS_NAME_PATTERN
from src.fairflow.contract import Contract


@dataclass(frozen=True)
class FeasibilityResult:
    """Immutable result contract of a policy safety and feasibility evaluation.

    Attributes:
        is_feasible: True if the policy satisfies all validation, safety, and capacity checks.
        reasons: Tuple of human-readable, deterministic rejection reasons (empty if feasible).
        usable_capacity_mbps: The usable shaping capacity (Mbit/s) evaluated against.
        required_minimum_mbps: Sum of minimum guaranteed rate floors (Mbit/s).
        allocations_mbps: Max-min fair rate allocations per class if feasible, or None if rejected.
        policy_summary: Diagnostic metadata summarizing the evaluated policy configuration.
    """

    is_feasible: bool
    reasons: Tuple[str, ...] = field(default_factory=tuple)
    usable_capacity_mbps: float = 0.0
    required_minimum_mbps: float = 0.0
    allocations_mbps: Optional[Dict[str, float]] = None
    policy_summary: Dict[str, Any] = field(default_factory=dict)


def compute_usable_capacity(raw_capacity_mbps: float, shaping_margin_pct: float = 5.0) -> float:
    """Compute usable shaping capacity from raw estimated bottleneck capacity.

    In home broadband QoS, shaping to 95% (shaping_margin_pct=5.0) of bottleneck capacity
    is standard practice to ensure the standing queue collapses into the local router rather
    than buffering in the unmanaged upstream ISP modem.

    Args:
        raw_capacity_mbps: Raw estimated bottleneck link capacity in Mbit/s.
        shaping_margin_pct: Percentage headroom deducted for router shaping (default: 5.0%).

    Returns:
        Usable capacity in Mbit/s.

    Raises:
        TypeError: If inputs are not real numbers or are boolean.
        ValueError: If raw_capacity_mbps <= 0, or shaping_margin_pct not in [0.0, 100.0).
    """
    if isinstance(raw_capacity_mbps, bool) or not isinstance(raw_capacity_mbps, (int, float)):
        raise TypeError(f"raw_capacity_mbps must be a real number, got {type(raw_capacity_mbps).__name__}")
    if isinstance(shaping_margin_pct, bool) or not isinstance(shaping_margin_pct, (int, float)):
        raise TypeError(f"shaping_margin_pct must be a real number, got {type(shaping_margin_pct).__name__}")

    raw_cap = float(raw_capacity_mbps)
    margin = float(shaping_margin_pct)

    if math.isnan(raw_cap) or math.isinf(raw_cap):
        raise ValueError(f"raw_capacity_mbps cannot be NaN or infinite, got {raw_cap}")
    if raw_cap <= 0.0:
        raise ValueError(f"raw_capacity_mbps must be strictly positive, got {raw_cap}")

    if math.isnan(margin) or math.isinf(margin):
        raise ValueError(f"shaping_margin_pct cannot be NaN or infinite, got {margin}")
    if not (0.0 <= margin < 100.0):
        raise ValueError(f"shaping_margin_pct must be in [0.0, 100.0), got {margin}")

    fraction = (100.0 - margin) / 100.0
    return round(raw_cap * fraction, 6)


def max_min_fair_allocation(
    usable_capacity_mbps: float,
    demands_mbps: Mapping[str, float],
    floors_mbps: Optional[Mapping[str, float]] = None,
) -> Dict[str, float]:
    """Compute progressive water-filling max-min fair allocation with minimum guarantees.

    Fairness and Allocation Semantics:
    1. Demands represent upper bounds on bandwidth consumption for active traffic classes.
    2. Minimum guaranteed rate floors (floors_mbps) are satisfied first: each class i receives
       an initial reservation of a_i = floor_i.
    3. Feasibility prerequisite: sum(floors) <= usable_capacity_mbps. If floors exceed capacity,
       an explicit ValueError is raised indicating the infeasible guarantee conflict.
    4. Surplus capacity C_rem = usable_capacity_mbps - sum(floors) is allocated according to
       standard max-min fair progressive filling (water-filling) across remaining unsatisfied
       excess demands e_i = max(0, demand_i - floor_i).
    5. At each stage with active unsatisfied classes S, the equal fair share is delta = C_rem / |S|.
       Any class whose excess demand e_i <= delta is fully satisfied, removed from S, and C_rem
       is reduced by e_i. Remaining capacity is iteratively distributed to the remaining classes.
    6. If total demand is less than usable capacity, every class receives its full demand; surplus
       remains unallocated.

    Args:
        usable_capacity_mbps: Total usable capacity available for allocation.
        demands_mbps: Mapping of class identifier to demanded bandwidth in Mbit/s.
        floors_mbps: Optional mapping of class identifier to minimum rate floor in Mbit/s.

    Returns:
        Dictionary mapping each class identifier to its allocated rate in Mbit/s.

    Raises:
        TypeError: If inputs are invalid types.
        ValueError: If capacity is negative/NaN/inf, demands are invalid, or floors exceed capacity.
    """
    if isinstance(usable_capacity_mbps, bool) or not isinstance(usable_capacity_mbps, (int, float)):
        raise TypeError(f"usable_capacity_mbps must be a real number, got {type(usable_capacity_mbps).__name__}")
    c_usable = float(usable_capacity_mbps)
    if math.isnan(c_usable) or math.isinf(c_usable) or c_usable < 0.0:
        raise ValueError(f"usable_capacity_mbps must be a non-negative finite real number, got {c_usable}")

    if not isinstance(demands_mbps, Mapping) or not demands_mbps:
        raise ValueError("demands_mbps must be a non-empty mapping of class name to demanded rate")

    validated_demands: Dict[str, float] = {}
    for cls_name, d_val in demands_mbps.items():
        if not isinstance(cls_name, str) or not VALID_CLASS_NAME_PATTERN.match(cls_name):
            raise ValueError(f"Invalid class identifier '{cls_name}' in demands_mbps")
        if isinstance(d_val, bool) or not isinstance(d_val, (int, float)):
            raise TypeError(f"Demand for '{cls_name}' must be a real number, got {type(d_val).__name__}")
        d_float = float(d_val)
        if math.isnan(d_float) or math.isinf(d_float) or d_float < 0.0:
            raise ValueError(f"Demand for '{cls_name}' must be finite and non-negative, got {d_float}")
        validated_demands[cls_name] = d_float

    validated_floors: Dict[str, float] = {}
    if floors_mbps:
        if not isinstance(floors_mbps, Mapping):
            raise TypeError(f"floors_mbps must be a mapping, got {type(floors_mbps).__name__}")
        for cls_name, f_val in floors_mbps.items():
            if cls_name not in validated_demands:
                raise ValueError(f"Floor specified for unknown class '{cls_name}' not present in demands")
            if isinstance(f_val, bool) or not isinstance(f_val, (int, float)):
                raise TypeError(f"Floor for '{cls_name}' must be a real number, got {type(f_val).__name__}")
            f_float = float(f_val)
            if math.isnan(f_float) or math.isinf(f_float) or f_float < 0.0:
                raise ValueError(f"Floor for '{cls_name}' must be finite and non-negative, got {f_float}")
            validated_floors[cls_name] = f_float

    for cls_name in validated_demands:
        if cls_name not in validated_floors:
            validated_floors[cls_name] = 0.0

    total_floors = sum(validated_floors.values())
    if total_floors > c_usable:
        raise ValueError(
            f"Infeasible guarantees: sum of minimum floors ({total_floors:.3f} Mbps) "
            f"exceeds usable capacity ({c_usable:.3f} Mbps)"
        )

    # Initial allocation reserves each class's guaranteed floor
    allocations: Dict[str, float] = {cls_name: validated_floors[cls_name] for cls_name in validated_demands}
    c_rem = c_usable - total_floors

    # Excess demand beyond floor
    excess_demands: Dict[str, float] = {
        cls_name: max(0.0, validated_demands[cls_name] - validated_floors[cls_name])
        for cls_name in validated_demands
    }

    # Progressive filling across active classes needing additional capacity
    active = {cls_name for cls_name, e in excess_demands.items() if e > 1e-9}

    while active and c_rem > 1e-9:
        fair_share = c_rem / len(active)
        satisfied = [cls_name for cls_name in active if excess_demands[cls_name] <= fair_share]

        if satisfied:
            for cls_name in satisfied:
                alloc = excess_demands[cls_name]
                allocations[cls_name] += alloc
                c_rem -= alloc
                active.remove(cls_name)
        else:
            # All remaining active classes demand more than the fair share; divide remaining equally
            for cls_name in active:
                allocations[cls_name] += fair_share
            c_rem = 0.0
            break

    return {cls_name: round(alloc, 6) for cls_name, alloc in allocations.items()}


def evaluate_policy_feasibility(
    policy: Policy,
    estimated_capacity_mbps: float,
    contract: Optional[Contract] = None,
    current_policy: Optional[Policy] = None,
    traffic_demands_mbps: Optional[Mapping[str, float]] = None,
    capacity_is_raw: bool = False,
    shaping_margin_pct: float = 5.0,
) -> FeasibilityResult:
    """Evaluate structural validity, contract safety, and capacity feasibility of a proposed Policy.

    This function is strictly deterministic and side-effect free. It never invokes tc, ip,
    subprocesses, or kernel commands.

    Args:
        policy: Proposed QoS Policy to evaluate.
        estimated_capacity_mbps: Estimated bottleneck link capacity in Mbit/s.
        contract: Optional loaded Contract object specifying floor requirements and step bounds.
        current_policy: Optional active Policy object to evaluate adaptation step limits against.
        traffic_demands_mbps: Optional traffic demands per class in Mbit/s for max-min allocation.
        capacity_is_raw: If True, estimated_capacity_mbps is treated as raw unshaped bottleneck
            capacity and reduced by shaping_margin_pct. If False, treated directly as usable capacity.
        shaping_margin_pct: Safety margin percentage to apply when capacity_is_raw=True (default: 5.0%).

    Returns:
        FeasibilityResult with explicit reasons if rejected, or valid max-min allocation if feasible.
    """
    reasons: list[str] = []

    # 1. Validate policy parameter types and structure
    if not isinstance(policy, Policy):
        reasons.append(f"Proposed policy must be an instance of Policy, got {type(policy).__name__}")
        return FeasibilityResult(is_feasible=False, reasons=tuple(reasons))

    # 2. Validate capacity inputs
    usable_cap: float = 0.0
    if isinstance(estimated_capacity_mbps, bool) or not isinstance(estimated_capacity_mbps, (int, float)):
        reasons.append(f"estimated_capacity_mbps must be a real number, got {type(estimated_capacity_mbps).__name__}")
    else:
        f_cap = float(estimated_capacity_mbps)
        if math.isnan(f_cap) or math.isinf(f_cap):
            reasons.append(f"estimated_capacity_mbps cannot be NaN or infinite, got {f_cap}")
        elif f_cap <= 0.0:
            reasons.append(f"estimated_capacity_mbps must be strictly positive, got {f_cap}")
        else:
            if capacity_is_raw:
                try:
                    usable_cap = compute_usable_capacity(f_cap, shaping_margin_pct)
                except (TypeError, ValueError) as exc:
                    reasons.append(f"Failed to compute usable capacity: {exc}")
            else:
                usable_cap = f_cap

    # 3. Validate class policies within the policy object
    required_minimum_mbps: float = 0.0
    for cls_name, cp in policy.classes.items():
        if not isinstance(cp, ClassPolicy):
            reasons.append(f"Class '{cls_name}' configuration must be a ClassPolicy, got {type(cp).__name__}")
            continue
        required_minimum_mbps += cp.rate_floor_mbps
        if cp.leaf_qdisc not in SUPPORTED_LEAF_QDISCS:
            reasons.append(f"Class '{cls_name}' uses unsupported leaf_qdisc '{cp.leaf_qdisc}'")

    # 4. Validate capacity feasibility (guarantees <= usable capacity)
    if usable_cap > 0.0:
        if required_minimum_mbps > usable_cap:
            reasons.append(
                f"Capacity infeasibility: required minimum guarantees ({required_minimum_mbps:.3f} Mbps) "
                f"exceed usable capacity ({usable_cap:.3f} Mbps)"
            )

    # 5. Validate Safety Contract compliance (if contract provided)
    if contract is not None:
        if not isinstance(contract, Contract):
            reasons.append(f"contract must be a Contract instance, got {type(contract).__name__}")
        else:
            # Check mandatory floor minimums for standard classes
            if "interactive" in policy.classes:
                actual_floor = policy.classes["interactive"].rate_floor_mbps
                target_floor = contract.interactive_floor_mbps
                if actual_floor < target_floor:
                    reasons.append(
                        f"Safety contract violation: 'interactive' floor ({actual_floor:.2f} Mbps) "
                        f"is below contract floor ({target_floor:.2f} Mbps)"
                    )

            if "streaming" in policy.classes:
                actual_floor = policy.classes["streaming"].rate_floor_mbps
                target_floor = contract.streaming_floor_mbps
                if actual_floor < target_floor:
                    reasons.append(
                        f"Safety contract violation: 'streaming' floor ({actual_floor:.2f} Mbps) "
                        f"is below contract floor ({target_floor:.2f} Mbps)"
                    )

            if "bulk" in policy.classes:
                actual_floor = policy.classes["bulk"].rate_floor_mbps
                target_floor = contract.bulk_floor_mbps
                if actual_floor < target_floor:
                    reasons.append(
                        f"Safety contract violation: 'bulk' floor ({actual_floor:.2f} Mbps) "
                        f"is below contract floor ({target_floor:.2f} Mbps)"
                    )

            # Check adaptation step limit relative to current_policy
            if current_policy is not None:
                if not isinstance(current_policy, Policy):
                    reasons.append(
                        f"current_policy must be a Policy instance, got {type(current_policy).__name__}"
                    )
                else:
                    max_step_pct = contract.policy_max_step_pct
                    for cls_name, prop_cp in policy.classes.items():
                        if cls_name in current_policy.classes:
                            curr_cp = current_policy.classes[cls_name]
                            if curr_cp.rate_floor_mbps > 0.0:
                                step_floor = (
                                    abs(prop_cp.rate_floor_mbps - curr_cp.rate_floor_mbps)
                                    / curr_cp.rate_floor_mbps
                                    * 100.0
                                )
                                if step_floor > max_step_pct:
                                    reasons.append(
                                        f"Adaptation step violation: class '{cls_name}' rate floor change "
                                        f"({step_floor:.1f}%) exceeds contract max_step_pct ({max_step_pct:.1f}%)"
                                    )

    # 6. Validate traffic demands (if provided)
    demands_to_use: Dict[str, float] = {}
    if traffic_demands_mbps is not None:
        if not isinstance(traffic_demands_mbps, Mapping):
            reasons.append(f"traffic_demands_mbps must be a mapping, got {type(traffic_demands_mbps).__name__}")
        else:
            for cls_name, dem in traffic_demands_mbps.items():
                if cls_name not in policy.classes:
                    reasons.append(f"traffic_demands_mbps specifies unknown class '{cls_name}'")
                elif isinstance(dem, bool) or not isinstance(dem, (int, float)):
                    reasons.append(f"Demand for '{cls_name}' must be a real number, got {type(dem).__name__}")
                else:
                    dem_f = float(dem)
                    if math.isnan(dem_f) or math.isinf(dem_f) or dem_f < 0.0:
                        reasons.append(f"Demand for '{cls_name}' must be finite and non-negative, got {dem_f}")
                    else:
                        demands_to_use[cls_name] = dem_f

    # Default missing demands to class ceiling
    for cls_name, cp in policy.classes.items():
        if cls_name not in demands_to_use:
            demands_to_use[cls_name] = cp.rate_ceiling_mbps

    policy_summary = {
        "link_capacity_mbps": policy.link_capacity_mbps,
        "classes": {
            cls_name: {
                "rate_floor_mbps": cp.rate_floor_mbps,
                "rate_ceiling_mbps": cp.rate_ceiling_mbps,
                "priority": cp.priority,
                "leaf_qdisc": cp.leaf_qdisc,
            }
            for cls_name, cp in policy.classes.items()
        },
        "usable_capacity_mbps": usable_cap,
        "required_minimum_mbps": required_minimum_mbps,
        "capacity_is_raw": capacity_is_raw,
        "shaping_margin_pct": shaping_margin_pct if capacity_is_raw else 0.0,
    }

    # If any rejections occurred, return an explicit infeasible result
    if reasons:
        return FeasibilityResult(
            is_feasible=False,
            reasons=tuple(reasons),
            usable_capacity_mbps=usable_cap,
            required_minimum_mbps=round(required_minimum_mbps, 6),
            allocations_mbps=None,
            policy_summary=policy_summary,
        )

    # 7. Compute max-min fair allocation across classes
    floors = {cls_name: cp.rate_floor_mbps for cls_name, cp in policy.classes.items()}
    try:
        allocations = max_min_fair_allocation(
            usable_capacity_mbps=usable_cap,
            demands_mbps=demands_to_use,
            floors_mbps=floors,
        )
    except Exception as exc:
        return FeasibilityResult(
            is_feasible=False,
            reasons=(f"Fairness allocation error: {exc}",),
            usable_capacity_mbps=usable_cap,
            required_minimum_mbps=round(required_minimum_mbps, 6),
            allocations_mbps=None,
            policy_summary=policy_summary,
        )

    return FeasibilityResult(
        is_feasible=True,
        reasons=(),
        usable_capacity_mbps=usable_cap,
        required_minimum_mbps=round(required_minimum_mbps, 6),
        allocations_mbps=allocations,
        policy_summary=policy_summary,
    )


class SafetyContractEngine:
    """State-free engine providing a structured facade for policy safety evaluation."""

    def __init__(self, contract: Optional[Contract] = None, shaping_margin_pct: float = 5.0) -> None:
        self.contract = contract
        self.shaping_margin_pct = shaping_margin_pct

    def evaluate(
        self,
        policy: Policy,
        estimated_capacity_mbps: float,
        current_policy: Optional[Policy] = None,
        traffic_demands_mbps: Optional[Mapping[str, float]] = None,
        capacity_is_raw: bool = False,
    ) -> FeasibilityResult:
        """Evaluate a proposed policy with the engine's configured contract and shaping margin."""
        return evaluate_policy_feasibility(
            policy=policy,
            estimated_capacity_mbps=estimated_capacity_mbps,
            contract=self.contract,
            current_policy=current_policy,
            traffic_demands_mbps=traffic_demands_mbps,
            capacity_is_raw=capacity_is_raw,
            shaping_margin_pct=self.shaping_margin_pct,
        )
