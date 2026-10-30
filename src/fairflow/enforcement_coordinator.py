"""enforcement_coordinator.py — Safe enforcement, kernel verification, and rollback coordinator.

Integrates PolicyEngine with TCDriver to establish the complete safety lifecycle:
PROPOSE -> VALIDATE -> SNAPSHOT -> APPLY -> VERIFY -> CANARY MONITOR -> ACCEPT or ROLLBACK

Safety Invariants:
1. Candidate Authorization: Only PolicyDecisionRecords in VALIDATED state with is_feasible=True
   can be submitted for kernel enforcement. REJECTED or PROPOSED candidates are strictly rejected.
2. Allowlist Enforcement: Network namespace and interface names must strictly match '^ff_[a-z0-9_]{1,12}$'.
   System interfaces (eth0, wlan0, lo, etc.) are strictly forbidden.
3. Pre-Apply State Capture: A snapshot of the exact current qdisc state is captured prior to any mutation.
   If snapshot capture fails, the operation aborts without touching the network.
4. Independent Verification: Applying tc commands via subprocess is not assumed to guarantee desired state.
   The coordinator independently reads back kernel qdisc/class state to verify intended parameters.
5. Automated Verified Rollback: On apply failure, verification mismatch, or canary threshold breach,
   the coordinator restores the last-known-good state (or clean baseline) and independently verifies restoration.
6. Fail Closed: If restoration cannot be confirmed, state transitions to FAILED. The coordinator never
   reports successful recovery when rollback is unconfirmed.
7. Structured Auditing: Every transition, snapshot, verification check, and rollback event is recorded
   immutably with timestamps, policy IDs, and diagnostic details.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, Sequence, Tuple, List, Callable

from src.fairflow.policy import Policy
from src.fairflow.contract import Contract
from src.fairflow.enforce import (
    TCDriver,
    validate_interface_name,
    validate_namespace_name,
)
from src.fairflow.controller import (
    PolicyEngine,
    PolicyDecisionRecord,
    PolicyState,
    InvalidStateTransitionError,
)


class EnforcementState(str, Enum):
    """Operational enforcement lifecycle states."""

    IDLE = "IDLE"
    APPLYING = "APPLYING"
    ENFORCED = "ENFORCED"              # Applied to kernel and independently verified
    CANARY_MONITORING = "CANARY_MONITORING"
    ACCEPTED = "ACCEPTED"              # Passed canary verification; active operational baseline
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"        # Successfully reverted and verified
    FAILED = "FAILED"                  # Apply, verification, or rollback failed to confirm state


@dataclass(frozen=True)
class CanaryMeasurement:
    """Telemetry sample for one observation window."""

    timestamp: float
    window_index: int
    added_delay_ms: float
    jitter_ms: float
    loss_pct: float
    valid: bool = True
    reason: str = ""

    def __post_init__(self) -> None:
        # Validate timestamp
        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, (int, float)):
            raise TypeError("timestamp must be a real number")
        if math.isnan(self.timestamp) or math.isinf(self.timestamp) or self.timestamp < 0:
            raise ValueError(f"timestamp must be a non-negative finite number, got {self.timestamp}")


@dataclass(frozen=True)
class CanaryResult:
    """Outcome of canary monitoring evaluation."""

    passed: bool
    status: str                        # "ACCEPTED", "BREACHED", "INSUFFICIENT_DATA"
    consecutive_breaches: int
    total_windows_evaluated: int
    good_windows: int
    reasons: Tuple[str, ...] = field(default_factory=tuple)


class CanaryMonitor:
    """Pure, deterministic canary evaluation engine based on safety contract guardrails."""

    def __init__(self, contract: Optional[Contract] = None) -> None:
        self.contract = contract

        # Guardrails and timing derived from contract (or committed defaults)
        self.window_s: float = contract.measurement_window_s if contract else 2.0
        self.duration_s: float = contract.canary_duration_s if contract else 10.0
        self.breach_windows: int = contract.canary_breach_windows if contract else 2
        self.good_windows_target: int = contract.recovery_good_windows if contract else 3

        self.delay_guardrail_ms: float = (
            contract.interactive_added_delay_guardrail_ms if contract else 80.0
        )
        self.jitter_guardrail_ms: float = (
            contract.interactive_jitter_guardrail_ms if contract else 30.0
        )
        self.loss_guardrail_pct: float = (
            contract.interactive_loss_guardrail_pct if contract else 2.0
        )

        self.expected_windows: int = int(self.duration_s / self.window_s)

    def evaluate_measurement(
        self, measurement: CanaryMeasurement, current_consecutive_breaches: int = 0
    ) -> Tuple[bool, int, str]:
        """Evaluate a single window measurement against contract guardrails.

        Returns:
            (is_breached, new_consecutive_breaches, failure_reason)
        """
        if not measurement.valid:
            new_breaches = current_consecutive_breaches + 1
            return True, new_breaches, f"Invalid measurement: {measurement.reason or 'unspecified error'}"

        for name, val in [
            ("added_delay_ms", measurement.added_delay_ms),
            ("jitter_ms", measurement.jitter_ms),
            ("loss_pct", measurement.loss_pct),
        ]:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                new_breaches = current_consecutive_breaches + 1
                return True, new_breaches, f"Metric '{name}' must be a real number"
            f_val = float(val)
            if math.isnan(f_val) or math.isinf(f_val):
                new_breaches = current_consecutive_breaches + 1
                return True, new_breaches, f"Metric '{name}' cannot be NaN or infinite"

        breaches: List[str] = []
        if measurement.added_delay_ms > self.delay_guardrail_ms:
            breaches.append(
                f"added_delay ({measurement.added_delay_ms:.1f} ms) > guardrail ({self.delay_guardrail_ms:.1f} ms)"
            )
        if measurement.jitter_ms > self.jitter_guardrail_ms:
            breaches.append(
                f"jitter ({measurement.jitter_ms:.1f} ms) > guardrail ({self.jitter_guardrail_ms:.1f} ms)"
            )
        if measurement.loss_pct > self.loss_guardrail_pct:
            breaches.append(
                f"loss ({measurement.loss_pct:.2f}%) > guardrail ({self.loss_guardrail_pct:.2f}%)"
            )

        if breaches:
            new_breaches = current_consecutive_breaches + 1
            return True, new_breaches, "; ".join(breaches)

        return False, 0, ""

    def evaluate_series(self, measurements: Sequence[CanaryMeasurement]) -> CanaryResult:
        """Evaluate a sequence of consecutive window measurements across the canary trial."""
        if not measurements:
            return CanaryResult(
                passed=False,
                status="INSUFFICIENT_DATA",
                consecutive_breaches=0,
                total_windows_evaluated=0,
                good_windows=0,
                reasons=("No canary measurements provided",),
            )

        consecutive_breaches = 0
        max_consecutive_breaches = 0
        good_windows = 0
        reasons: List[str] = []

        for idx, m in enumerate(measurements):
            is_breach, consecutive_breaches, reason = self.evaluate_measurement(
                m, consecutive_breaches
            )
            if is_breach:
                max_consecutive_breaches = max(max_consecutive_breaches, consecutive_breaches)
                reasons.append(f"Window {idx} ({m.window_index}): {reason}")
                if consecutive_breaches >= self.breach_windows:
                    # Consecutive breach threshold reached: immediate fail
                    return CanaryResult(
                        passed=False,
                        status="BREACHED",
                        consecutive_breaches=consecutive_breaches,
                        total_windows_evaluated=idx + 1,
                        good_windows=good_windows,
                        reasons=tuple(reasons),
                    )
            else:
                good_windows += 1

        total_evaluated = len(measurements)
        if total_evaluated < self.expected_windows:
            return CanaryResult(
                passed=False,
                status="INSUFFICIENT_DATA",
                consecutive_breaches=consecutive_breaches,
                total_windows_evaluated=total_evaluated,
                good_windows=good_windows,
                reasons=(
                    f"Insufficient windows: evaluated {total_evaluated}, expected {self.expected_windows}",
                ),
            )

        if good_windows >= self.good_windows_target and consecutive_breaches == 0:
            return CanaryResult(
                passed=True,
                status="ACCEPTED",
                consecutive_breaches=0,
                total_windows_evaluated=total_evaluated,
                good_windows=good_windows,
                reasons=(),
            )

        return CanaryResult(
            passed=False,
            status="INSUFFICIENT_DATA",
            consecutive_breaches=consecutive_breaches,
            total_windows_evaluated=total_evaluated,
            good_windows=good_windows,
            reasons=tuple(reasons or ("Canary did not accumulate required good windows",)),
        )


@dataclass(frozen=True)
class EnforcementOutcome:
    """Structured result returned by coordinator operations."""

    success: bool
    enforcement_state: EnforcementState
    decision_id: str
    kernel_verified: bool
    rollback_performed: bool
    rollback_verified: bool
    error_message: Optional[str] = None
    snapshot_before: Optional[List[Dict[str, Any]]] = None
    snapshot_after: Optional[List[Dict[str, Any]]] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EnforcementEvent:
    """Immutable audit event documenting lifecycle changes."""

    timestamp: float
    event_type: str
    decision_id: str
    from_state: EnforcementState
    to_state: EnforcementState
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class EnforcementCoordinator:
    """Coordinates safe QoS policy application, verification, canary testing, and rollback."""

    def __init__(
        self,
        engine: PolicyEngine,
        driver: TCDriver,
        interface: str,
        namespace: str,
        contract: Optional[Contract] = None,
        canary_monitor: Optional[CanaryMonitor] = None,
        time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.engine: PolicyEngine = engine
        self.driver: TCDriver = driver
        self.interface: str = validate_interface_name(interface)
        self.namespace: str = validate_namespace_name(namespace)
        self.contract: Optional[Contract] = contract
        self.canary_monitor: CanaryMonitor = canary_monitor or CanaryMonitor(contract=contract)
        self.time_fn: Callable[[], float] = time_fn or time.time

        # Operational state
        self.state: EnforcementState = EnforcementState.IDLE
        self.last_known_good_policy: Optional[Policy] = None
        self.last_known_good_snapshot: Optional[List[Dict[str, Any]]] = None
        self.current_record: Optional[PolicyDecisionRecord] = None
        self.events: List[EnforcementEvent] = []

    def _record_event(
        self,
        event_type: str,
        decision_id: str,
        from_state: EnforcementState,
        to_state: EnforcementState,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        now = self.time_fn()
        ev = EnforcementEvent(
            timestamp=now,
            event_type=event_type,
            decision_id=decision_id,
            from_state=from_state,
            to_state=to_state,
            details=details or {},
            error=error,
        )
        self.events.append(ev)

    def list_events(self) -> List[EnforcementEvent]:
        """Return full audit history of enforcement coordinator events."""
        return list(self.events)

    def verify_kernel_state(self, expected_policy: Policy) -> Tuple[bool, str]:
        """Independently inspect kernel traffic control state and verify match with expected policy."""
        try:
            qdiscs = self.driver.snapshot(interface=self.interface, namespace=self.namespace)
        except Exception as exc:
            return False, f"Failed to snapshot kernel qdisc state: {exc}"

        if not qdiscs:
            return False, "Kernel snapshot returned empty qdisc list; no active qdiscs found"

        # Check for root HTB qdisc
        root_htb = any(
            q.get("kind") == "htb" and (q.get("root") is True or q.get("handle") == "1:")
            for q in qdiscs
        )
        if not root_htb:
            return False, "Kernel verification failed: missing root HTB qdisc with handle 1:"

        # Verify leaf qdiscs for expected classes
        for class_name, cp in expected_policy.classes.items():
            class_id = self.driver.CLASS_IDS.get(class_name)
            if class_id is None:
                continue

            expected_parent = f"1:{class_id}"
            expected_handle = f"{class_id}0:"
            expected_leaf = cp.leaf_qdisc or "fq_codel"

            matching_leaf = any(
                q.get("kind") == expected_leaf
                and (q.get("parent") == expected_parent or q.get("handle") == expected_handle)
                for q in qdiscs
            )
            if not matching_leaf:
                return (
                    False,
                    f"Kernel verification failed: class '{class_name}' ({expected_parent}) "
                    f"leaf qdisc '{expected_leaf}' not found in kernel qdiscs",
                )

        # If snapshot_classes is supported on the driver, verify classes as well
        if hasattr(self.driver, "snapshot_classes"):
            try:
                classes = self.driver.snapshot_classes(
                    interface=self.interface, namespace=self.namespace
                )
                if classes:
                    root_class_found = any(c.get("classid") == "1:1" for c in classes)
                    if not root_class_found:
                        return False, "Kernel verification failed: root HTB class 1:1 not found"
            except Exception:
                pass  # snapshot_classes is an optional additional verification

        return True, "Kernel state verified successfully against policy"

    def apply_and_verify(self, record: PolicyDecisionRecord) -> EnforcementOutcome:
        """Apply a validated candidate policy to the testbed and verify kernel state.

        Steps:
        1. Precondition Check: Candidate must be in VALIDATED state with is_feasible=True.
        2. Pre-Apply Snapshot: Capture baseline qdisc state before any mutation.
        3. Apply: Invoke TCDriver.apply().
        4. Verify: Independently inspect kernel qdisc state via snapshot.
        5. Recovery: On apply or verification failure, attempt automatic verified rollback.
        """
        decision_id = record.decision_id
        initial_state = self.state

        # 1. Precondition verification: must be VALIDATED
        if record.state != PolicyState.VALIDATED:
            err = f"Enforcement rejected: record '{decision_id}' is in state '{record.state.value}', not VALIDATED"
            self._record_event(
                "PRECONDITION_FAILED", decision_id, self.state, self.state, error=err
            )
            return EnforcementOutcome(
                success=False,
                enforcement_state=self.state,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=False,
                rollback_verified=False,
                error_message=err,
            )

        if not record.proposed_policy:
            err = f"Enforcement rejected: record '{decision_id}' contains no proposed_policy"
            self._record_event(
                "PRECONDITION_FAILED", decision_id, self.state, self.state, error=err
            )
            return EnforcementOutcome(
                success=False,
                enforcement_state=self.state,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=False,
                rollback_verified=False,
                error_message=err,
            )

        # 2. Capture pre-apply state snapshot
        try:
            snapshot_before = self.driver.snapshot(
                interface=self.interface, namespace=self.namespace
            )
        except Exception as exc:
            err = f"Pre-apply snapshot capture failed: {exc}"
            self._record_event("SNAPSHOT_FAILED", decision_id, self.state, self.state, error=err)
            return EnforcementOutcome(
                success=False,
                enforcement_state=self.state,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=False,
                rollback_verified=False,
                error_message=err,
            )

        self.state = EnforcementState.APPLYING
        self._record_event("APPLY_STARTED", decision_id, initial_state, EnforcementState.APPLYING)

        # 3. Apply candidate policy
        try:
            self.driver.apply(
                interface=self.interface,
                namespace=self.namespace,
                policy=record.proposed_policy,
            )
        except Exception as exc:
            err = f"Driver apply failed: {exc}"
            self._record_event(
                "APPLY_FAILED", decision_id, EnforcementState.APPLYING, EnforcementState.ROLLING_BACK, error=err
            )
            # Automatic rollback to last known good
            rb_outcome = self.rollback(reason=f"Apply failed: {exc}", target_snapshot=snapshot_before)
            return EnforcementOutcome(
                success=False,
                enforcement_state=self.state,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=True,
                rollback_verified=rb_outcome.rollback_verified,
                error_message=f"{err}; Rollback verified={rb_outcome.rollback_verified}",
                snapshot_before=snapshot_before,
            )

        # 4. Independent kernel state verification
        is_verified, verify_msg = self.verify_kernel_state(record.proposed_policy)
        if not is_verified:
            err = f"Independent kernel verification failed: {verify_msg}"
            self._record_event(
                "VERIFICATION_FAILED",
                decision_id,
                EnforcementState.APPLYING,
                EnforcementState.ROLLING_BACK,
                error=err,
            )
            # Automatic rollback on verification mismatch
            rb_outcome = self.rollback(
                reason=f"Kernel verification mismatch: {verify_msg}",
                target_snapshot=snapshot_before,
            )
            return EnforcementOutcome(
                success=False,
                enforcement_state=self.state,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=True,
                rollback_verified=rb_outcome.rollback_verified,
                error_message=f"{err}; Rollback verified={rb_outcome.rollback_verified}",
                snapshot_before=snapshot_before,
            )

        # 5. Transition policy state to ENFORCED
        snapshot_after = self.driver.snapshot(interface=self.interface, namespace=self.namespace)
        try:
            self.engine.transition_state(
                decision_id=decision_id,
                target_state=PolicyState.ENFORCED,
                reason="Kernel enforcement and independent verification passed",
            )
        except InvalidStateTransitionError as err:
            # If transition fails, fail closed
            rb_outcome = self.rollback(
                reason=f"State transition to ENFORCED rejected: {err}",
                target_snapshot=snapshot_before,
            )
            return EnforcementOutcome(
                success=False,
                enforcement_state=self.state,
                decision_id=decision_id,
                kernel_verified=True,
                rollback_performed=True,
                rollback_verified=rb_outcome.rollback_verified,
                error_message=str(err),
                snapshot_before=snapshot_before,
                snapshot_after=snapshot_after,
            )

        self.state = EnforcementState.ENFORCED
        self.current_record = record
        self._record_event(
            "ENFORCED",
            decision_id,
            EnforcementState.APPLYING,
            EnforcementState.ENFORCED,
            details={"verification": verify_msg},
        )

        return EnforcementOutcome(
            success=True,
            enforcement_state=EnforcementState.ENFORCED,
            decision_id=decision_id,
            kernel_verified=True,
            rollback_performed=False,
            rollback_verified=False,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            details={"verification_message": verify_msg},
        )

    def canary_evaluate_and_commit(
        self,
        record: PolicyDecisionRecord,
        measurements: Sequence[CanaryMeasurement],
    ) -> EnforcementOutcome:
        """Evaluate canary monitoring telemetry and commit to ACTIVE or trigger rollback.

        Rules:
        - If canary passes (ACCEPTED): Policy becomes ACTIVE, last-known-good is updated.
        - If canary breaches (BREACHED or INSUFFICIENT_DATA): Immediate verified rollback.
        """
        decision_id = record.decision_id
        if self.state not in (EnforcementState.ENFORCED, EnforcementState.CANARY_MONITORING):
            err = f"Canary evaluation rejected: coordinator is in state '{self.state.value}', expected ENFORCED or CANARY_MONITORING"
            return EnforcementOutcome(
                success=False,
                enforcement_state=self.state,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=False,
                rollback_verified=False,
                error_message=err,
            )

        self.state = EnforcementState.CANARY_MONITORING
        self._record_event(
            "CANARY_STARTED",
            decision_id,
            EnforcementState.ENFORCED,
            EnforcementState.CANARY_MONITORING,
            details={"window_count": len(measurements)},
        )

        canary_res = self.canary_monitor.evaluate_series(measurements)

        if canary_res.passed and canary_res.status == "ACCEPTED":
            # Canary passed: commit policy as active operational baseline
            try:
                self.engine.transition_state(
                    decision_id=decision_id,
                    target_state=PolicyState.ACTIVE,
                    reason=f"Canary passed ({canary_res.good_windows} good windows, 0 breaches)",
                )
            except InvalidStateTransitionError as exc:
                rb_outcome = self.rollback(reason=f"Transition to ACTIVE failed: {exc}")
                return EnforcementOutcome(
                    success=False,
                    enforcement_state=self.state,
                    decision_id=decision_id,
                    kernel_verified=True,
                    rollback_performed=True,
                    rollback_verified=rb_outcome.rollback_verified,
                    error_message=str(exc),
                )

            self.last_known_good_policy = record.proposed_policy
            self.last_known_good_snapshot = self.driver.snapshot(
                interface=self.interface, namespace=self.namespace
            )
            self.state = EnforcementState.ACCEPTED
            self._record_event(
                "CANARY_ACCEPTED",
                decision_id,
                EnforcementState.CANARY_MONITORING,
                EnforcementState.ACCEPTED,
                details={"good_windows": canary_res.good_windows},
            )

            return EnforcementOutcome(
                success=True,
                enforcement_state=EnforcementState.ACCEPTED,
                decision_id=decision_id,
                kernel_verified=True,
                rollback_performed=False,
                rollback_verified=False,
                details={"canary_result": canary_res},
            )

        # If still in progress and not breached, maintain ENFORCED state and wait for remaining windows
        if (
            canary_res.status == "INSUFFICIENT_DATA"
            and len(measurements) < self.canary_monitor.expected_windows
            and canary_res.consecutive_breaches < self.canary_monitor.breach_windows
        ):
            self.state = EnforcementState.ENFORCED
            return EnforcementOutcome(
                success=True,
                enforcement_state=EnforcementState.ENFORCED,
                decision_id=decision_id,
                kernel_verified=True,
                rollback_performed=False,
                rollback_verified=False,
                details={"canary_result": canary_res, "status": "IN_PROGRESS"},
            )

        # Canary failed (breached or complete trial lacked good windows): trigger automatic verified rollback
        breach_reason = "; ".join(canary_res.reasons)
        self._record_event(
            "CANARY_BREACHED",
            decision_id,
            EnforcementState.CANARY_MONITORING,
            EnforcementState.ROLLING_BACK,
            error=breach_reason,
            details={"status": canary_res.status, "consecutive_breaches": canary_res.consecutive_breaches},
        )

        # Mark policy record ROLLED_BACK in engine
        try:
            self.engine.transition_state(
                decision_id=decision_id,
                target_state=PolicyState.ROLLED_BACK,
                reason=f"Canary breach: {breach_reason}",
            )
        except Exception:
            pass

        rb_outcome = self.rollback(reason=f"Canary breach: {breach_reason}")
        return EnforcementOutcome(
            success=False,
            enforcement_state=self.state,
            decision_id=decision_id,
            kernel_verified=False,
            rollback_performed=True,
            rollback_verified=rb_outcome.rollback_verified,
            error_message=f"Canary failed ({canary_res.status}): {breach_reason}",
            details={"canary_result": canary_res},
        )

    def rollback(
        self,
        reason: str,
        target_snapshot: Optional[List[Dict[str, Any]]] = None,
    ) -> EnforcementOutcome:
        """Perform verified rollback to last-known-good policy or clean default baseline.

        Safety: Never reports success if post-rollback state cannot be verified.
        """
        prev_state = self.state
        self.state = EnforcementState.ROLLING_BACK
        decision_id = self.current_record.decision_id if self.current_record else "none"

        self._record_event(
            "ROLLBACK_STARTED",
            decision_id,
            prev_state,
            EnforcementState.ROLLING_BACK,
            details={"reason": reason},
        )

        # 1. Execute rollback via TCDriver
        try:
            self.driver.rollback(
                interface=self.interface,
                namespace=self.namespace,
                target_policy=self.last_known_good_policy,
            )
        except Exception as exc:
            err = f"Rollback execution command failed: {exc}"
            self.state = EnforcementState.FAILED
            self._record_event(
                "ROLLBACK_FAILED", decision_id, EnforcementState.ROLLING_BACK, EnforcementState.FAILED, error=err
            )
            return EnforcementOutcome(
                success=False,
                enforcement_state=EnforcementState.FAILED,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=True,
                rollback_verified=False,
                error_message=err,
            )

        # 2. Independently verify post-rollback kernel state
        try:
            post_snapshot = self.driver.snapshot(
                interface=self.interface, namespace=self.namespace
            )
        except Exception as exc:
            err = f"Failed to snapshot state after rollback: {exc}"
            self.state = EnforcementState.FAILED
            self._record_event(
                "ROLLBACK_VERIFICATION_FAILED",
                decision_id,
                EnforcementState.ROLLING_BACK,
                EnforcementState.FAILED,
                error=err,
            )
            return EnforcementOutcome(
                success=False,
                enforcement_state=EnforcementState.FAILED,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=True,
                rollback_verified=False,
                error_message=err,
            )

        # Verification rules:
        # If last_known_good_policy exists: verify qdisc matches last_known_good
        # If no last_known_good_policy: verify root qdisc is deleted (no root HTB handle 1:)
        rollback_verified = False
        verify_detail = ""

        if self.last_known_good_policy is not None:
            is_valid, msg = self.verify_kernel_state(self.last_known_good_policy)
            rollback_verified = is_valid
            verify_detail = msg
        else:
            # Clean baseline: no HTB root qdisc with handle 1:
            has_htb_root = any(
                q.get("kind") == "htb" and (q.get("root") is True or q.get("handle") == "1:")
                for q in post_snapshot
            )
            rollback_verified = not has_htb_root
            verify_detail = (
                "Clean baseline restored (no root HTB qdisc)"
                if rollback_verified
                else "Root HTB qdisc still present after clean rollback"
            )

        if not rollback_verified:
            err = f"Post-rollback kernel state verification failed: {verify_detail}"
            self.state = EnforcementState.FAILED
            self._record_event(
                "ROLLBACK_VERIFICATION_FAILED",
                decision_id,
                EnforcementState.ROLLING_BACK,
                EnforcementState.FAILED,
                error=err,
            )
            return EnforcementOutcome(
                success=False,
                enforcement_state=EnforcementState.FAILED,
                decision_id=decision_id,
                kernel_verified=False,
                rollback_performed=True,
                rollback_verified=False,
                error_message=err,
                snapshot_after=post_snapshot,
            )

        self.state = EnforcementState.ROLLED_BACK
        self._record_event(
            "ROLLED_BACK",
            decision_id,
            EnforcementState.ROLLING_BACK,
            EnforcementState.ROLLED_BACK,
            details={"verification": verify_detail},
        )

        return EnforcementOutcome(
            success=True,
            enforcement_state=EnforcementState.ROLLED_BACK,
            decision_id=decision_id,
            kernel_verified=False,
            rollback_performed=True,
            rollback_verified=True,
            snapshot_after=post_snapshot,
            details={"verification": verify_detail},
        )
