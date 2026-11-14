"""dynamic_controller.py — End-to-end adaptive QoS control loop for FairFlow.

Orchestrates the complete FairFlow lifecycle:
OBSERVE -> CLASSIFY -> ESTIMATE CAPACITY -> PROPOSE -> VALIDATE -> APPLY -> VERIFY -> MONITOR -> ACCEPT OR ROLLBACK

Safety Invariants:
1. Pure Separation of Concerns: Observation ingestion, classification, capacity estimation,
   policy generation, enforcement, and canary monitoring are distinct and independently testable.
2. Allowlist and Namespace Safety: All interface and namespace operations are strictly restricted
   to '^ff_[a-z0-9_]{1,12}$'.
3. Concurrency Protection: Explicit per-interface mutex locks prevent concurrent mutation attempts.
4. Telemetry Integrity: Uses monotonic clocks for sequencing and duration, preserves separate wall-clock
   audit timestamps, rejects stale or out-of-order windows, and preserves raw unclipped signed delay values.
5. Provable Feasibility: Every candidate policy is verified against contract minimum floors and adaptation
   step limits via SafetyContractEngine before submission to the enforcer.
6. Verified Enforcement and Rollback: Applied policies are independently verified in the Linux kernel.
   Canary monitoring guardrail breaches trigger automated verified rollback to the last-known-good baseline.
7. Deadband Hysteresis: Changes within policy_deadband_pct (10%) are suppressed to prevent qdisc churn.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, Sequence, Tuple, List, Callable, Protocol

try:
    import resource as _resource
except ImportError:  # pragma: no cover - non-POSIX platforms
    _resource = None

from src.fairflow.policy import Policy
from src.fairflow.contract import Contract
from src.fairflow.traffic import PacketRecord
from src.fairflow.stats import percentile, compute_rfc3550_jitter
from src.fairflow.classifier import TrafficClassifier, FlowMetadata, ClassificationResult, UserIntent
from src.fairflow.controller import PolicyEngine, PolicyDecisionRecord, PolicyState
from src.fairflow.enforcement_coordinator import (
    EnforcementCoordinator,
    EnforcementState,
    CanaryMonitor,
    CanaryMeasurement,
    CanaryResult,
    EnforcementOutcome,
)


class ConcurrencyCollisionError(Exception):
    """Raised when concurrent operations attempt to mutate the same interface/namespace."""


@dataclass(frozen=True)
class TelemetryWindow:
    """Timestamped observation window containing network packet records and active flows."""

    window_index: int
    start_time_monotonic: float
    end_time_monotonic: float
    wall_clock_time: float
    packet_records: Tuple[PacketRecord, ...]
    packets_sent: int
    packets_received: int
    flows: Tuple[FlowMetadata, ...] = field(default_factory=tuple)
    baseline_delay_ms: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.window_index, bool) or not isinstance(self.window_index, int) or self.window_index < 0:
            raise ValueError(f"window_index must be a non-negative integer, got {self.window_index}")
        if self.start_time_monotonic > self.end_time_monotonic:
            raise ValueError(
                f"start_time_monotonic ({self.start_time_monotonic}) cannot be > end_time_monotonic ({self.end_time_monotonic})"
            )
        if self.packets_sent < 0 or self.packets_received < 0:
            raise ValueError("packets_sent and packets_received must be non-negative")
        if self.packets_received > self.packets_sent:
            raise ValueError(
                f"packets_received ({self.packets_received}) cannot exceed packets_sent ({self.packets_sent})"
            )


@dataclass(frozen=True)
class CapacityEstimate:
    """Estimated link bottleneck capacity with source and confidence metadata."""

    capacity_mbps: float
    timestamp_monotonic: float
    wall_clock_time: float
    source: str                        # "static_configured", "injected_test", "bottleneck_calibrated"
    is_available: bool = True
    confidence: float = 1.0            # 0.0 to 1.0
    uncertainty_mbps: float = 0.0
    estimation_error_mbps: Optional[float] = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.is_available:
            if isinstance(self.capacity_mbps, bool) or not isinstance(self.capacity_mbps, (int, float)):
                raise TypeError(f"capacity_mbps must be a real number, got {type(self.capacity_mbps).__name__}")
            f_cap = float(self.capacity_mbps)
            if math.isnan(f_cap) or math.isinf(f_cap) or f_cap <= 0.0:
                raise ValueError(f"capacity_mbps must be strictly positive and finite, got {f_cap}")


class CapacityProvider(Protocol):
    """Protocol for link capacity estimation providers."""

    def get_capacity_estimate(self, now_monotonic: float) -> CapacityEstimate:
        """Return capacity estimate for the current timestamp."""
        ...


class StaticCapacityProvider:
    """Deterministic capacity provider with fixed or manually updated capacity."""

    def __init__(
        self,
        capacity_mbps: float = 100.0,
        source: str = "static_configured",
        is_available: bool = True,
        confidence: float = 1.0,
        time_fn: Optional[Callable[[], float]] = None,
        wall_time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.capacity_mbps = capacity_mbps
        self.source = source
        self.is_available = is_available
        self.confidence = confidence
        self.time_fn = time_fn or time.monotonic
        self.wall_time_fn = wall_time_fn or time.time

    def set_capacity(self, capacity_mbps: float, is_available: bool = True) -> None:
        self.capacity_mbps = capacity_mbps
        self.is_available = is_available

    def get_capacity_estimate(self, now_monotonic: float) -> CapacityEstimate:
        return CapacityEstimate(
            capacity_mbps=self.capacity_mbps,
            timestamp_monotonic=now_monotonic,
            wall_clock_time=self.wall_time_fn(),
            source=self.source,
            is_available=self.is_available,
            confidence=self.confidence,
        )


class AdaptiveCapacityEstimator:
    """Real-life congestion-aware passive & active link capacity estimator (CAKE/BBR-inspired).

    Observes goodput, added delay (standing queue), packet loss, and qdisc drops across
    measurement windows:
    - When standing queue delay exceeds delay_target_ms or packet loss exceeds loss_target_pct,
      infers that bottleneck capacity is near or below current delivery rate and steps down
      capacity_mbps via EWMA smoothing.
    - When delay remains well below target (< 0.5 * delay_target_ms) and loss is 0 for
      recovery_good_windows consecutive windows under high utilization, probes upward
      within max_step_pct toward nominal_capacity_mbps.
    """

    def __init__(
        self,
        nominal_capacity_mbps: float = 100.0,
        min_capacity_mbps: float = 5.0,
        delay_target_ms: float = 30.0,
        loss_target_pct: float = 0.5,
        max_step_pct: float = 25.0,
        recovery_good_windows: int = 3,
        ewma_alpha: float = 0.35,
        time_fn: Optional[Callable[[], float]] = None,
        wall_time_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self.nominal_capacity_mbps = nominal_capacity_mbps
        self.capacity_mbps = nominal_capacity_mbps
        self.min_capacity_mbps = min_capacity_mbps
        self.delay_target_ms = delay_target_ms
        self.loss_target_pct = loss_target_pct
        self.max_step_pct = max_step_pct
        self.recovery_good_windows = recovery_good_windows
        self.ewma_alpha = ewma_alpha
        self.is_available: bool = True
        self.confidence: float = 0.96
        self.uncertainty_mbps: float = 2.0
        self.source: str = "adaptive_telemetry_estimator"
        self.reason: str = "Operating at calibrated nominal bottleneck capacity"
        self.time_fn = time_fn or time.monotonic
        self.wall_time_fn = wall_time_fn or time.time
        self._consecutive_good_windows: int = 0
        self._manual_override: bool = False
        self._ground_truth_errors_mbps: List[float] = []
        self._last_ground_truth_mbps: Optional[float] = None

    def record_ground_truth(self, true_capacity_mbps: float) -> float:
        """Record a known ground-truth capacity sample to track estimator absolute error."""
        true_val = max(0.1, float(true_capacity_mbps))
        self._last_ground_truth_mbps = true_val
        err = abs(self.capacity_mbps - true_val)
        self._ground_truth_errors_mbps.append(err)
        if len(self._ground_truth_errors_mbps) > 100:
            self._ground_truth_errors_mbps.pop(0)
        return round(err, 3)

    @property
    def mean_abs_error_mbps(self) -> Optional[float]:
        """Return empirical MAE against recorded ground truth, or None if unavailable."""
        if not self._ground_truth_errors_mbps:
            return None
        return round(sum(self._ground_truth_errors_mbps) / len(self._ground_truth_errors_mbps), 3)

    def set_capacity(self, capacity_mbps: float, is_available: bool = True) -> None:
        """Explicitly set capacity estimate (e.g. from test harness or manual capacity drop test)."""
        self.capacity_mbps = max(1.0, float(capacity_mbps))
        self.is_available = is_available
        self.confidence = 0.98
        self.uncertainty_mbps = round(self.capacity_mbps * 0.02, 2)
        self.source = "manual_or_calibrated"
        self.reason = f"Explicitly set to {self.capacity_mbps:.1f} Mbps"
        self._manual_override = True

    def observe_telemetry(
        self,
        throughput_mbps: Optional[float],
        added_delay_ms: float,
        loss_pct: float,
        qdisc_drops: int = 0,
    ) -> CapacityEstimate:
        """Update capacity estimate based on a completed telemetry window."""
        now_mono = self.time_fn()
        if not self.is_available:
            return self.get_capacity_estimate(now_mono)

        tput = float(throughput_mbps or 0.0)
        is_congested = added_delay_ms > self.delay_target_ms or loss_pct > self.loss_target_pct

        if is_congested and tput > 0.0:
            self._consecutive_good_windows = 0
            # Infer true bottleneck rate from observed throughput under standing queue
            inferred_raw = max(self.min_capacity_mbps, min(self.nominal_capacity_mbps, tput / 0.95))
            # Bound downward step by max_step_pct per window
            min_allowed = self.capacity_mbps * (1.0 - self.max_step_pct / 100.0)
            target_cap = max(min_allowed, inferred_raw)
            self.capacity_mbps = round(
                (1.0 - self.ewma_alpha) * self.capacity_mbps + self.ewma_alpha * target_cap, 2
            )
            self.confidence = round(max(0.70, 0.95 - (added_delay_ms / 500.0)), 2)
            self.uncertainty_mbps = round(abs(self.capacity_mbps - inferred_raw), 2)
            self.source = "congestion_inferred"
            self.reason = (
                f"Standing queue detected (added_delay={added_delay_ms:.1f}ms, loss={loss_pct:.2f}%); "
                f"inferred bottleneck {self.capacity_mbps:.1f} Mbps"
            )
        else:
            if added_delay_ms <= self.delay_target_ms * 0.5 and loss_pct <= 0.1:
                self._consecutive_good_windows += 1
            else:
                self._consecutive_good_windows = 0

            # If not manually locked down, gently probe back toward nominal after good windows
            if (
                not self._manual_override
                and self._consecutive_good_windows >= self.recovery_good_windows
                and self.capacity_mbps < self.nominal_capacity_mbps
                and tput >= self.capacity_mbps * 0.70
            ):
                step_up = min(
                    self.nominal_capacity_mbps,
                    self.capacity_mbps * (1.0 + (self.max_step_pct * 0.5) / 100.0),
                )
                self.capacity_mbps = round(step_up, 2)
                self.confidence = min(0.98, round(self.confidence + 0.03, 2))
                self.uncertainty_mbps = max(1.0, round(self.uncertainty_mbps * 0.85, 2))
                self.reason = (
                    f"Recovered after {self._consecutive_good_windows} clean windows; "
                    f"probing capacity to {self.capacity_mbps:.1f} Mbps"
                )

        return self.get_capacity_estimate(now_mono)

    def get_capacity_estimate(self, now_monotonic: float) -> CapacityEstimate:
        return CapacityEstimate(
            capacity_mbps=self.capacity_mbps,
            timestamp_monotonic=now_monotonic,
            wall_clock_time=self.wall_time_fn(),
            source=self.source,
            is_available=self.is_available,
            confidence=self.confidence,
            uncertainty_mbps=self.uncertainty_mbps,
            reason=self.reason,
        )


class ControlAction(str, Enum):
    """Actions resulting from a control loop step."""

    NOOP_DEADBAND = "NOOP_DEADBAND"      # Proposed changes within deadband hysteresis; apply suppressed
    NOOP_CAPACITY_UNAVAILABLE = "NOOP_CAPACITY_UNAVAILABLE" # Capacity estimate missing; safe hold
    ENFORCED = "ENFORCED"                # New policy applied and kernel verified
    COMMITTED = "COMMITTED"              # Passed canary monitoring and active baseline updated
    ROLLED_BACK = "ROLLED_BACK"          # Safeguard triggered rollback
    REJECTED = "REJECTED"                # Policy proposal infeasible or contract violation
    FAILED = "FAILED"                    # Fatal enforcement, verification, or rollback failure


@dataclass(frozen=True)
class ControlStepOutcome:
    """Detailed record of a single dynamic controller execution step."""

    step_index: int
    action: ControlAction
    timestamp_monotonic: float
    wall_clock_time: float
    decision_id: Optional[str]
    capacity_estimate: Optional[CapacityEstimate]
    classified_flow_count: int
    policy_proposed: Optional[Policy]
    enforcement_outcome: Optional[EnforcementOutcome]
    canary_result: Optional[CanaryResult]
    explanation: str
    details: Dict[str, Any] = field(default_factory=dict)


class DynamicController:
    """Coordinates observation, classification, capacity tracking, policy decisions, and enforcement."""

    def __init__(
        self,
        engine: PolicyEngine,
        coordinator: EnforcementCoordinator,
        classifier: Optional[TrafficClassifier] = None,
        capacity_provider: Optional[CapacityProvider] = None,
        contract: Optional[Contract] = None,
        clock: Optional[Callable[[], float]] = None,
        wall_clock: Optional[Callable[[], float]] = None,
        deadband_pct: Optional[float] = None,
    ) -> None:
        self.engine: PolicyEngine = engine
        self.coordinator: EnforcementCoordinator = coordinator
        self.classifier: TrafficClassifier = classifier or TrafficClassifier()
        self.contract: Optional[Contract] = contract
        self.capacity_provider: CapacityProvider = capacity_provider or StaticCapacityProvider(
            capacity_mbps=contract.link_default_capacity_mbps if contract else 100.0
        )
        self.clock: Callable[[], float] = clock or time.monotonic
        self.wall_clock: Callable[[], float] = wall_clock or time.time
        self.deadband_pct: float = (
            deadband_pct
            if deadband_pct is not None
            else (contract.policy_deadband_pct if contract else 10.0)
        )

        # Operational state and concurrency protection
        self._mutex = threading.Lock()
        self._step_counter: int = 0
        self._last_window_end_time: float = -1.0
        self._outcomes: List[ControlStepOutcome] = []
        self._canary_measurements: List[CanaryMeasurement] = []

        # Controller computational overhead and safety decision counters
        self._overhead_lock = threading.Lock()
        self._steps_evaluated: int = 0
        self._total_wall_ms: float = 0.0
        self._total_cpu_ms: float = 0.0
        self._last_step_wall_ms: float = 0.0
        self._last_step_cpu_ms: float = 0.0
        self._max_step_wall_ms: float = 0.0
        self._gate_rejections: int = 0
        self._deadband_suppressions: int = 0
        self._canary_rollbacks: int = 0
        self._commits: int = 0

    def _record_overhead(self, outcome_tag: str, wall_ms: float, cpu_ms: float) -> None:
        """Update per-step execution timing and decision counters safely."""
        w_ms = max(0.0, float(wall_ms))
        c_ms = max(0.0, float(cpu_ms))
        tag = str(outcome_tag).upper()
        with self._overhead_lock:
            self._steps_evaluated += 1
            self._total_wall_ms += w_ms
            self._total_cpu_ms += c_ms
            self._last_step_wall_ms = w_ms
            self._last_step_cpu_ms = c_ms
            self._max_step_wall_ms = max(self._max_step_wall_ms, w_ms)
            if "REJECTED" in tag:
                self._gate_rejections += 1
            elif "DEADBAND" in tag:
                self._deadband_suppressions += 1
            elif "ROLLED_BACK" in tag or "ROLLBACK" in tag:
                self._canary_rollbacks += 1
            elif "COMMITTED" in tag or "ACCEPTED" in tag:
                self._commits += 1

    def record_external_decision(self, verdict: str, wall_ms: float = 0.0, cpu_ms: float = 0.0) -> None:
        """Record overhead and verdict counts for policies proposed through REST endpoints."""
        self._record_overhead(verdict, wall_ms, cpu_ms)

    @staticmethod
    def _read_process_rss_mb() -> float:
        """Read current resident memory footprint in MiB using OS-appropriate units."""
        if _resource is None:
            return 0.0
        rss_raw = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
        # macOS reports ru_maxrss in bytes; Linux reports kilobytes.
        divisor = (1024.0 * 1024.0) if sys.platform == "darwin" else 1024.0
        return round(rss_raw / divisor, 2)

    def get_overhead_metrics(self) -> Dict[str, Any]:
        """Return controller execution latency, CPU, RSS memory, and estimator accuracy telemetry."""
        cap_est = self.capacity_provider.get_capacity_estimate(self.clock())
        est_mae = getattr(self.capacity_provider, "mean_abs_error_mbps", None)
        with self._overhead_lock:
            steps = self._steps_evaluated
            avg_wall = round(self._total_wall_ms / steps, 4) if steps > 0 else 0.0
            avg_cpu = round(self._total_cpu_ms / steps, 4) if steps > 0 else 0.0
            return {
                "steps_evaluated": steps,
                "last_step_wall_ms": round(self._last_step_wall_ms, 4),
                "avg_step_wall_ms": avg_wall,
                "max_step_wall_ms": round(self._max_step_wall_ms, 4),
                "last_step_cpu_ms": round(self._last_step_cpu_ms, 4),
                "avg_step_cpu_ms": avg_cpu,
                "process_rss_mb": self._read_process_rss_mb(),
                "gate_rejections": self._gate_rejections,
                "deadband_suppressions": self._deadband_suppressions,
                "canary_rollbacks": self._canary_rollbacks,
                "commits": self._commits,
                "estimator": {
                    "capacity_mbps": cap_est.capacity_mbps if cap_est.is_available else None,
                    "source": cap_est.source,
                    "confidence": round(float(cap_est.confidence), 3),
                    "uncertainty_mbps": round(float(cap_est.uncertainty_mbps), 3),
                    "mae_mbps": est_mae,
                    "reason": cap_est.reason,
                },
            }

    @property
    def interface(self) -> str:
        return self.coordinator.interface

    @property
    def namespace(self) -> str:
        return self.coordinator.namespace

    def list_outcomes(self) -> List[ControlStepOutcome]:
        return list(self._outcomes)

    def is_within_deadband(self, candidate: Policy, current: Optional[Policy]) -> Tuple[bool, float]:
        """Check if candidate policy rates differ by less than deadband_pct from current active policy.

        Returns:
            (is_deadband, max_change_pct)
        """
        if current is None:
            return False, 100.0

        max_change = 0.0
        # Check capacity change
        if current.link_capacity_mbps > 0:
            cap_diff = (
                abs(candidate.link_capacity_mbps - current.link_capacity_mbps)
                / current.link_capacity_mbps
                * 100.0
            )
            max_change = max(max_change, cap_diff)

        # Check floor changes
        for cls_name, cand_cp in candidate.classes.items():
            if cls_name in current.classes:
                curr_cp = current.classes[cls_name]
                if curr_cp.rate_floor_mbps > 0:
                    floor_diff = (
                        abs(cand_cp.rate_floor_mbps - curr_cp.rate_floor_mbps)
                        / curr_cp.rate_floor_mbps
                        * 100.0
                    )
                    max_change = max(max_change, floor_diff)
            else:
                return False, 100.0

        return max_change <= self.deadband_pct, round(max_change, 2)

    def process_observation_window(
        self,
        telemetry: TelemetryWindow,
        active_intents: Optional[Sequence[UserIntent]] = None,
    ) -> ControlStepOutcome:
        """Execute one complete control loop iteration for an incoming observation window.

        Pipeline:
        1. Acquire concurrency lock (fails closed on race).
        2. Validate telemetry freshness, monotonic ordering, and numeric consistency.
        3. Classify flows using metadata.
        4. Query capacity provider.
        5. Propose candidate policy via PolicyEngine.
        6. Check deadband hysteresis; suppress redundant changes.
        7. Apply candidate through EnforcementCoordinator and verify in kernel.
        8. Feed canary measurements and commit operational baseline or rollback.
        """
        acquired = self._mutex.acquire(blocking=False)
        if not acquired:
            raise ConcurrencyCollisionError(
                f"Concurrent mutation collision on interface '{self.interface}' in namespace '{self.namespace}'"
            )

        t_wall_start = time.perf_counter()
        t_cpu_start = time.process_time()
        try:
            outcome = self._process_observation_window_unlocked(telemetry, active_intents=active_intents)
            wall_ms = (time.perf_counter() - t_wall_start) * 1000.0
            cpu_ms = (time.process_time() - t_cpu_start) * 1000.0
            action_tag = outcome.action.value if hasattr(outcome.action, "value") else str(outcome.action)
            self._record_overhead(action_tag, wall_ms, cpu_ms)
            return outcome
        finally:
            self._mutex.release()

    def _process_observation_window_unlocked(
        self,
        telemetry: TelemetryWindow,
        active_intents: Optional[Sequence[UserIntent]] = None,
    ) -> ControlStepOutcome:
        """Internal step execution called with self._mutex already held."""
        now_mono = self.clock()
        now_wall = self.wall_clock()
        self._step_counter += 1
        step_idx = self._step_counter

        # 1. Telemetry validation and freshness check
        if telemetry.end_time_monotonic < self._last_window_end_time:
            err = (
                f"Out-of-order telemetry: window end ({telemetry.end_time_monotonic}) "
                f"< previous window end ({self._last_window_end_time})"
            )
            outcome = ControlStepOutcome(
                step_index=step_idx,
                action=ControlAction.FAILED,
                timestamp_monotonic=now_mono,
                wall_clock_time=now_wall,
                decision_id=None,
                capacity_estimate=None,
                classified_flow_count=0,
                policy_proposed=None,
                enforcement_outcome=None,
                canary_result=None,
                explanation=f"Telemetry rejected: {err}",
            )
            self._outcomes.append(outcome)
            return outcome

        self._last_window_end_time = telemetry.end_time_monotonic

        # 2. Flow classification
        classified_flows: List[Tuple[FlowMetadata, ClassificationResult]] = []
        for flow in telemetry.flows:
            res = self.classifier.classify(flow, current_time=now_mono)
            classified_flows.append((flow, res))

        # 3. Capacity estimation
        cap_estimate = self.capacity_provider.get_capacity_estimate(now_mono)
        if not cap_estimate.is_available:
            outcome = ControlStepOutcome(
                step_index=step_idx,
                action=ControlAction.NOOP_CAPACITY_UNAVAILABLE,
                timestamp_monotonic=now_mono,
                wall_clock_time=now_wall,
                decision_id=None,
                capacity_estimate=cap_estimate,
                classified_flow_count=len(classified_flows),
                policy_proposed=None,
                enforcement_outcome=None,
                canary_result=None,
                explanation="Capacity estimate unavailable; holding existing operational policy",
            )
            self._outcomes.append(outcome)
            return outcome

        # 4. Propose candidate policy
        decision_record = self.engine.generate_candidate_policy(
            classified_flows=classified_flows,
            estimated_capacity_mbps=cap_estimate.capacity_mbps,
            timestamp=now_mono,
        )

        if decision_record.state != PolicyState.VALIDATED or not decision_record.proposed_policy:
            outcome = ControlStepOutcome(
                step_index=step_idx,
                action=ControlAction.REJECTED,
                timestamp_monotonic=now_mono,
                wall_clock_time=now_wall,
                decision_id=decision_record.decision_id,
                capacity_estimate=cap_estimate,
                classified_flow_count=len(classified_flows),
                policy_proposed=None,
                enforcement_outcome=None,
                canary_result=None,
                explanation=f"Policy candidate rejected by safety contract: {decision_record.explanation}",
            )
            self._outcomes.append(outcome)
            return outcome

        candidate_policy = decision_record.proposed_policy

        # 5. Check deadband hysteresis
        is_deadband, max_change = self.is_within_deadband(
            candidate=candidate_policy, current=self.coordinator.last_known_good_policy
        )
        if is_deadband:
            outcome = ControlStepOutcome(
                step_index=step_idx,
                action=ControlAction.NOOP_DEADBAND,
                timestamp_monotonic=now_mono,
                wall_clock_time=now_wall,
                decision_id=decision_record.decision_id,
                capacity_estimate=cap_estimate,
                classified_flow_count=len(classified_flows),
                policy_proposed=candidate_policy,
                enforcement_outcome=None,
                canary_result=None,
                explanation=f"Change ({max_change}%) <= deadband threshold ({self.deadband_pct}%); apply suppressed",
                details={"max_change_pct": max_change},
            )
            self._outcomes.append(outcome)
            return outcome

        # 6. Enforcement and kernel verification
        active_record = decision_record
        enf_outcome = None

        already_enforcing = (
            self.coordinator.state in (EnforcementState.ENFORCED, EnforcementState.CANARY_MONITORING)
            and self.coordinator.current_record is not None
            and self.coordinator.current_record.proposed_policy == candidate_policy
        )

        if already_enforcing:
            # Policy is already active in kernel and undergoing canary monitoring;
            # avoid redundant tc re-application during the canary window evaluation
            active_record = self.coordinator.current_record
        else:
            self._canary_measurements = []
            enf_outcome = self.coordinator.apply_and_verify(decision_record)
            if not enf_outcome.success:
                outcome = ControlStepOutcome(
                    step_index=step_idx,
                    action=ControlAction.FAILED if enf_outcome.enforcement_state == EnforcementState.FAILED else ControlAction.ROLLED_BACK,
                    timestamp_monotonic=now_mono,
                    wall_clock_time=now_wall,
                    decision_id=decision_record.decision_id,
                    capacity_estimate=cap_estimate,
                    classified_flow_count=len(classified_flows),
                    policy_proposed=candidate_policy,
                    enforcement_outcome=enf_outcome,
                    canary_result=None,
                    explanation=f"Enforcement failed: {enf_outcome.error_message}",
                )
                self._outcomes.append(outcome)
                return outcome

        # 7. Compute canary measurement from window packet telemetry
        # Calculate raw, unclipped added delay, jitter, and loss
        packet_records = list(telemetry.packet_records)
        loss_pct = (
            (telemetry.packets_sent - telemetry.packets_received) / telemetry.packets_sent * 100.0
            if telemetry.packets_sent > 0
            else 0.0
        )

        if packet_records:
            delays = [r.one_way_delay_ms for r in packet_records]
            p95_delay = percentile(delays, 95.0)
            # Raw, unclipped signed added delay
            added_delay_ms = p95_delay - telemetry.baseline_delay_ms
            jitter_ms = compute_rfc3550_jitter(packet_records)
            canary_meas = CanaryMeasurement(
                timestamp=telemetry.end_time_monotonic,
                window_index=telemetry.window_index,
                added_delay_ms=added_delay_ms,
                jitter_ms=jitter_ms,
                loss_pct=loss_pct,
                valid=True,
            )
        else:
            # Missing packet telemetry
            canary_meas = CanaryMeasurement(
                timestamp=telemetry.end_time_monotonic,
                window_index=telemetry.window_index,
                added_delay_ms=0.0,
                jitter_ms=0.0,
                loss_pct=loss_pct,
                valid=False,
                reason="No packet records received in window",
            )

        # 8. Evaluate canary and commit baseline or rollback
        self._canary_measurements.append(canary_meas)
        canary_outcome = self.coordinator.canary_evaluate_and_commit(
            active_record, self._canary_measurements
        )

        if canary_outcome.enforcement_state == EnforcementState.ACCEPTED or canary_outcome.rollback_performed:
            self._canary_measurements = []

        if canary_outcome.success and canary_outcome.enforcement_state == EnforcementState.ACCEPTED:
            action = ControlAction.COMMITTED
        elif canary_outcome.rollback_performed and canary_outcome.rollback_verified:
            action = ControlAction.ROLLED_BACK
        elif canary_outcome.enforcement_state in (EnforcementState.ENFORCED, EnforcementState.CANARY_MONITORING):
            action = ControlAction.ENFORCED
        else:
            action = ControlAction.FAILED

        canary_res = canary_outcome.details.get("canary_result")
        outcome = ControlStepOutcome(
            step_index=step_idx,
            action=action,
            timestamp_monotonic=now_mono,
            wall_clock_time=now_wall,
            decision_id=active_record.decision_id,
            capacity_estimate=cap_estimate,
            classified_flow_count=len(classified_flows),
            policy_proposed=candidate_policy,
            enforcement_outcome=canary_outcome,
            canary_result=canary_res,
            explanation=f"Control step completed with action {action.value}",
            details={"added_delay_ms": canary_meas.added_delay_ms, "loss_pct": loss_pct},
        )
        self._outcomes.append(outcome)
        return outcome
