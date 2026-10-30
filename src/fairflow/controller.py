"""controller.py — Adaptive QoS policy generation and lifecycle engine for FairFlow.

Responsible for:
1. Consuming classified flow metadata and traffic telemetry.
2. Generating candidate QoS policies tailored to active traffic demands and estimated capacity.
3. Mapping 'unknown' or ambiguous traffic to a documented, safe best-effort default ('bulk').
4. Enforcing safety separation: routing every candidate through SafetyContractEngine
   for deterministic feasibility verification prior to validation.
5. Managing an auditable policy lifecycle state machine:
   PROPOSED -> VALIDATED | REJECTED -> ACTIVE -> SUPERSEDED | ROLLED_BACK.
6. Ensuring rejected policies can never become active.

Safety Invariants:
- Strictly side-effect free in Phase 3: no Linux networking, no tc/ip execution,
  no subprocess invocations, and no modification of system network state.
- Enforcement and measurement verification belong strictly to subsequent phases.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, Sequence, Tuple, List, Mapping, Callable

from src.fairflow.policy import Policy, ClassPolicy
from src.fairflow.contract import Contract
from src.fairflow.feasibility import (
    FeasibilityResult,
    SafetyContractEngine,
    compute_usable_capacity,
    evaluate_policy_feasibility,
    max_min_fair_allocation,
)
from src.fairflow.classifier import FlowMetadata, ClassificationResult


class PolicyState(str, Enum):
    """Lifecycle states for candidate and active QoS policies."""

    PROPOSED = "PROPOSED"          # Candidate generated from observations; unverified
    VALIDATED = "VALIDATED"        # Feasibility & safety contract checks passed
    REJECTED = "REJECTED"          # Failed feasibility or contract checks; cannot be applied
    ENFORCED = "ENFORCED"          # Applied to kernel and verified; awaiting canary acceptance
    ACTIVE = "ACTIVE"              # Validated candidate designated as active policy
    SUPERSEDED = "SUPERSEDED"      # Former active policy replaced by a newer validated policy
    ROLLED_BACK = "ROLLED_BACK"    # Active policy rolled back due to safety breach or failure
    FAILED = "FAILED"              # Enforcement, verification, or rollback failed


class InvalidStateTransitionError(Exception):
    """Raised when an illegal policy lifecycle state transition is attempted."""


# Standard FairFlow traffic priority bands and default leaf qdiscs
CLASS_PRIORITIES: Dict[str, int] = {
    "interactive": 1,
    "streaming": 2,
    "bulk": 3,
}

DEFAULT_LEAF_QDISC: str = "fq_codel"


@dataclass(frozen=True)
class PolicyDecisionRecord:
    """Auditable record documenting policy generation, verification, and lifecycle state."""

    decision_id: str
    state: PolicyState
    timestamp: float
    usable_capacity_mbps: float
    proposed_policy: Optional[Policy]
    feasibility_result: Optional[FeasibilityResult]
    active_classes: Tuple[str, ...]
    unmapped_unknown_count: int
    explanation: str
    state_history: Tuple[Tuple[float, PolicyState, str], ...] = field(default_factory=tuple)


class PolicyEngine:
    """Generates candidate QoS policies and governs their lifecycle transitions."""

    def __init__(
        self,
        contract: Optional[Contract] = None,
        shaping_margin_pct: float = 5.0,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.contract: Optional[Contract] = contract
        self.shaping_margin_pct: float = shaping_margin_pct
        self.time_fn: Callable[[], float] = time_fn or time.time
        self.safety_engine = SafetyContractEngine(contract=contract, shaping_margin_pct=shaping_margin_pct)

        # In-memory lifecycle tracking
        self._records: Dict[str, PolicyDecisionRecord] = {}
        self._active_record: Optional[PolicyDecisionRecord] = None
        self._decision_counter: int = 0

    @property
    def active_policy(self) -> Optional[Policy]:
        """Return currently active Policy, or None if no policy is active."""
        if self._active_record and self._active_record.state == PolicyState.ACTIVE:
            return self._active_record.proposed_policy
        return None

    @property
    def active_record(self) -> Optional[PolicyDecisionRecord]:
        """Return currently active decision record, or None."""
        return self._active_record

    def list_records(self) -> List[PolicyDecisionRecord]:
        """Return full history of policy decision records."""
        return list(self._records.values())

    def get_record(self, decision_id: str) -> Optional[PolicyDecisionRecord]:
        """Fetch a specific decision record by ID."""
        return self._records.get(decision_id)

    def generate_candidate_policy(
        self,
        classified_flows: Sequence[Tuple[FlowMetadata, ClassificationResult]],
        estimated_capacity_mbps: float,
        current_policy: Optional[Policy] = None,
        capacity_is_raw: bool = False,
        timestamp: Optional[float] = None,
    ) -> PolicyDecisionRecord:
        """Generate a candidate Policy tailored to observed flows and evaluate feasibility.

        FairFlow Candidate Policy Rules:
        1. 'unknown' traffic is conservatively mapped to the 'bulk' best-effort default.
           It is never granted priority over interactive or streaming traffic.
        2. Minimum guaranteed service floors are initialized to contract floors if a contract exists:
           - 'interactive': max(contract.interactive_floor_mbps, observed_demand)
           - 'streaming': max(contract.streaming_floor_mbps, observed_demand)
           - 'bulk': max(contract.bulk_floor_mbps, observed_demand)
        3. If adaptation limits apply (current_policy present and contract configured):
           Floors are bounded to stay within policy_max_step_pct of current_policy floors.
        4. Every candidate is routed through SafetyContractEngine before being marked VALIDATED.
        5. If feasibility or contract invariants fail, the candidate is marked REJECTED.

        Args:
            classified_flows: Sequence of (FlowMetadata, ClassificationResult) pairs.
            estimated_capacity_mbps: Bottleneck capacity estimate in Mbit/s.
            current_policy: Currently active Policy (uses self.active_policy if None).
            capacity_is_raw: If True, capacity is treated as unshaped bottleneck and reduced
                by shaping_margin_pct (default 5%). If False, treated as usable shaping capacity.
            timestamp: Optional deterministic evaluation timestamp.

        Returns:
            PolicyDecisionRecord in VALIDATED or REJECTED state.
        """
        now = timestamp if timestamp is not None else self.time_fn()
        if isinstance(now, bool) or not isinstance(now, (int, float)):
            raise TypeError(f"timestamp must be a real number, got {type(now).__name__}")
        if math.isnan(now) or math.isinf(now):
            raise ValueError(f"timestamp cannot be NaN or infinite, got {now}")

        self._decision_counter += 1
        decision_id = f"dec_{int(now)}_{self._decision_counter:04d}"

        active_policy_to_use = current_policy if current_policy is not None else self.active_policy

        # 1. Capacity validation and normalization
        if isinstance(estimated_capacity_mbps, bool) or not isinstance(estimated_capacity_mbps, (int, float)):
            record = PolicyDecisionRecord(
                decision_id=decision_id,
                state=PolicyState.REJECTED,
                timestamp=now,
                usable_capacity_mbps=0.0,
                proposed_policy=None,
                feasibility_result=None,
                active_classes=(),
                unmapped_unknown_count=0,
                explanation="Rejected: estimated_capacity_mbps must be a real number",
                state_history=((now, PolicyState.REJECTED, "Invalid capacity type"),),
            )
            self._records[decision_id] = record
            return record

        f_cap = float(estimated_capacity_mbps)
        if math.isnan(f_cap) or math.isinf(f_cap) or f_cap <= 0.0:
            record = PolicyDecisionRecord(
                decision_id=decision_id,
                state=PolicyState.REJECTED,
                timestamp=now,
                usable_capacity_mbps=0.0,
                proposed_policy=None,
                feasibility_result=None,
                active_classes=(),
                unmapped_unknown_count=0,
                explanation=f"Rejected: estimated_capacity_mbps must be strictly positive and finite, got {f_cap}",
                state_history=((now, PolicyState.REJECTED, "Invalid capacity value"),),
            )
            self._records[decision_id] = record
            return record

        usable_cap = compute_usable_capacity(f_cap, self.shaping_margin_pct) if capacity_is_raw else f_cap

        # 2. Flow aggregation and 'unknown' traffic mapping
        class_bitrates_bps: Dict[str, float] = {"interactive": 0.0, "streaming": 0.0, "bulk": 0.0}
        active_classes_detected: set[str] = set()
        unknown_count = 0

        for flow, res in classified_flows:
            cls_target = res.traffic_class
            if cls_target == "unknown":
                unknown_count += 1
                # Conservatively map unknown traffic to the safe bulk best-effort class
                cls_target = "bulk"

            if cls_target in class_bitrates_bps:
                class_bitrates_bps[cls_target] += flow.bitrate_bps
                active_classes_detected.add(cls_target)

        # 3. Construct candidate class policies respecting contract minimum floors
        # Contract floors: interactive=2.0, streaming=8.0, bulk=2.0 (if contract exists)
        min_interactive = self.contract.interactive_floor_mbps if self.contract else 2.0
        min_streaming = self.contract.streaming_floor_mbps if self.contract else 8.0
        min_bulk = self.contract.bulk_floor_mbps if self.contract else 2.0

        base_floors: Dict[str, float] = {
            "interactive": min_interactive,
            "streaming": min_streaming,
            "bulk": min_bulk,
        }

        # Check for immediate capacity infeasibility against mandatory contract floors
        total_mandatory_floors = sum(base_floors.values())
        if usable_cap < total_mandatory_floors or any(usable_cap < f for f in base_floors.values()):
            reasons = (
                f"Capacity infeasibility: required minimum guarantees ({total_mandatory_floors:.3f} Mbps) "
                f"exceed usable capacity ({usable_cap:.3f} Mbps)",
            )
            feasibility_result = FeasibilityResult(
                is_feasible=False,
                reasons=reasons,
                usable_capacity_mbps=usable_cap,
                required_minimum_mbps=round(total_mandatory_floors, 6),
                allocations_mbps=None,
            )
            history = [
                (now, PolicyState.PROPOSED, "Candidate policy generated from flow observations"),
                (now, PolicyState.REJECTED, reasons[0]),
            ]
            record = PolicyDecisionRecord(
                decision_id=decision_id,
                state=PolicyState.REJECTED,
                timestamp=now,
                usable_capacity_mbps=usable_cap,
                proposed_policy=None,
                feasibility_result=feasibility_result,
                active_classes=tuple(sorted(active_classes_detected)),
                unmapped_unknown_count=unknown_count,
                explanation=f"Candidate rejected: {reasons[0]}",
                state_history=tuple(history),
            )
            self._records[decision_id] = record
            return record

        # Traffic demands per class in Mbit/s
        demands_mbps = {cls: bps / 1e6 for cls, bps in class_bitrates_bps.items()}

        # Compute max-min fair allocation using progressive water-filling with mandatory floor reservations
        fair_allocations = max_min_fair_allocation(
            usable_capacity_mbps=usable_cap,
            demands_mbps=demands_mbps,
            floors_mbps=base_floors,
        )

        # Candidate floor settings:
        # If adapting from an existing active policy, step CIR floors toward fair allocations within policy_max_step_pct
        candidate_floors: Dict[str, float] = dict(base_floors)
        if self.contract and active_policy_to_use:
            max_step = self.contract.policy_max_step_pct / 100.0
            for cls_name in candidate_floors:
                if cls_name in active_policy_to_use.classes:
                    curr_floor = active_policy_to_use.classes[cls_name].rate_floor_mbps
                    target = fair_allocations.get(cls_name, base_floors[cls_name])
                    if curr_floor > 0.0:
                        max_allowed_floor = curr_floor * (1.0 + max_step)
                        min_allowed_floor = max(base_floors[cls_name], curr_floor * (1.0 - max_step))
                        candidate_floors[cls_name] = round(
                            min(max_allowed_floor, max(min_allowed_floor, target)), 2
                        )

        # Ensure adapted floors never exceed usable capacity
        if sum(candidate_floors.values()) > usable_cap:
            candidate_floors = dict(base_floors)

        # Build candidate Policy object
        candidate_classes = {
            "interactive": ClassPolicy(
                rate_floor_mbps=candidate_floors["interactive"],
                rate_ceiling_mbps=usable_cap,
                priority=CLASS_PRIORITIES["interactive"],
                leaf_qdisc=DEFAULT_LEAF_QDISC,
            ),
            "streaming": ClassPolicy(
                rate_floor_mbps=candidate_floors["streaming"],
                rate_ceiling_mbps=usable_cap,
                priority=CLASS_PRIORITIES["streaming"],
                leaf_qdisc=DEFAULT_LEAF_QDISC,
            ),
            "bulk": ClassPolicy(
                rate_floor_mbps=candidate_floors["bulk"],
                rate_ceiling_mbps=usable_cap,
                priority=CLASS_PRIORITIES["bulk"],
                leaf_qdisc=DEFAULT_LEAF_QDISC,
            ),
        }

        candidate_policy = Policy(link_capacity_mbps=usable_cap, classes=candidate_classes)

        # 4. Route candidate through SafetyContractEngine
        feasibility_result = evaluate_policy_feasibility(
            policy=candidate_policy,
            estimated_capacity_mbps=usable_cap,
            contract=self.contract,
            current_policy=active_policy_to_use,
            traffic_demands_mbps=demands_mbps,
            capacity_is_raw=False,
        )

        history: List[Tuple[float, PolicyState, str]] = [
            (now, PolicyState.PROPOSED, "Candidate policy generated from flow observations")
        ]

        if feasibility_result.is_feasible:
            state = PolicyState.VALIDATED
            explanation = (
                f"Candidate validated: feasible on {usable_cap:.2f} Mbps capacity. "
                f"Floors: {candidate_floors}. Active classes: {sorted(active_classes_detected)}. "
                f"Unknown flows routed to bulk: {unknown_count}."
            )
            history.append((now, PolicyState.VALIDATED, "Passed safety contract feasibility checks"))
        else:
            state = PolicyState.REJECTED
            reasons_str = "; ".join(feasibility_result.reasons)
            explanation = f"Candidate rejected by safety contract: {reasons_str}"
            history.append((now, PolicyState.REJECTED, reasons_str))

        record = PolicyDecisionRecord(
            decision_id=decision_id,
            state=state,
            timestamp=now,
            usable_capacity_mbps=usable_cap,
            proposed_policy=candidate_policy,
            feasibility_result=feasibility_result,
            active_classes=tuple(sorted(active_classes_detected)),
            unmapped_unknown_count=unknown_count,
            explanation=explanation,
            state_history=tuple(history),
        )

        self._records[decision_id] = record
        return record

    def transition_state(
        self,
        decision_id: str,
        target_state: PolicyState,
        reason: str,
        timestamp: Optional[float] = None,
    ) -> PolicyDecisionRecord:
        """Perform a validated lifecycle state transition on a policy decision record.

        Allowed Transitions:
        - PROPOSED -> VALIDATED (when feasibility verification succeeds)
        - PROPOSED -> REJECTED (when feasibility verification fails)
        - VALIDATED -> ACTIVE (when validated policy is designated active)
        - VALIDATED -> REJECTED (if invalidated prior to activation)
        - ACTIVE -> SUPERSEDED (when superseded by a newer ACTIVE policy)
        - ACTIVE -> ROLLED_BACK (when safety monitor triggers rollback)

        Disallowed Transitions (raise InvalidStateTransitionError):
        - REJECTED -> any state (rejected policies can NEVER become active)
        - PROPOSED -> ACTIVE (cannot bypass validation)
        - SUPERSEDED -> ACTIVE (cannot re-activate without new proposal)
        - ROLLED_BACK -> ACTIVE (cannot re-activate without new proposal)
        """
        record = self._records.get(decision_id)
        if not record:
            raise KeyError(f"Decision record '{decision_id}' not found")

        now = timestamp if timestamp is not None else self.time_fn()
        current_state = record.state

        # Validate transition matrix
        if current_state in (PolicyState.REJECTED, PolicyState.FAILED):
            raise InvalidStateTransitionError(
                f"Illegal transition: record '{decision_id}' is {current_state.value} and cannot transition to {target_state.value}"
            )

        if target_state == PolicyState.ENFORCED:
            if current_state != PolicyState.VALIDATED:
                raise InvalidStateTransitionError(
                    f"Illegal transition: cannot mark record in state '{current_state.value}' as ENFORCED; "
                    "policy must be VALIDATED first"
                )

        if target_state == PolicyState.ACTIVE:
            if current_state not in (PolicyState.VALIDATED, PolicyState.ENFORCED):
                raise InvalidStateTransitionError(
                    f"Illegal transition: cannot activate record in state '{current_state.value}'; "
                    "policy must be VALIDATED or ENFORCED first"
                )

        if target_state == PolicyState.SUPERSEDED and current_state not in (PolicyState.ACTIVE, PolicyState.ENFORCED):
            raise InvalidStateTransitionError(
                f"Illegal transition: only ACTIVE or ENFORCED policies can be SUPERSEDED, got {current_state.value}"
            )

        if target_state == PolicyState.ROLLED_BACK and current_state not in (PolicyState.ACTIVE, PolicyState.ENFORCED):
            raise InvalidStateTransitionError(
                f"Illegal transition: only ACTIVE or ENFORCED policies can be ROLLED_BACK, got {current_state.value}"
            )

        if target_state == PolicyState.FAILED and current_state not in (
            PolicyState.PROPOSED,
            PolicyState.VALIDATED,
            PolicyState.ENFORCED,
            PolicyState.ACTIVE,
        ):
            raise InvalidStateTransitionError(
                f"Illegal transition: cannot fail record in state {current_state.value}"
            )

        # If activating this policy, supersede the existing active policy
        if target_state == PolicyState.ACTIVE:
            if self._active_record and self._active_record.decision_id != decision_id:
                prev_id = self._active_record.decision_id
                self.transition_state(
                    decision_id=prev_id,
                    target_state=PolicyState.SUPERSEDED,
                    reason=f"Superseded by new active policy '{decision_id}'",
                    timestamp=now,
                )

        new_history = record.state_history + ((now, target_state, reason),)
        new_record = PolicyDecisionRecord(
            decision_id=record.decision_id,
            state=target_state,
            timestamp=now,
            usable_capacity_mbps=record.usable_capacity_mbps,
            proposed_policy=record.proposed_policy,
            feasibility_result=record.feasibility_result,
            active_classes=record.active_classes,
            unmapped_unknown_count=record.unmapped_unknown_count,
            explanation=f"State changed to {target_state.value}: {reason}",
            state_history=new_history,
        )

        self._records[decision_id] = new_record
        if target_state == PolicyState.ACTIVE:
            self._active_record = new_record
        elif current_state == PolicyState.ACTIVE and target_state != PolicyState.ACTIVE:
            self._active_record = None

        return new_record
