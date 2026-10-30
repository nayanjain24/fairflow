"""classifier.py — Metadata-only traffic observation and classification for FairFlow.

Classifies network flows into QoS categories ('interactive', 'streaming', 'bulk', 'unknown')
using metadata-only evidence:
- Layer 3/4 headers (protocols, source/destination IP and ports, DSCP marks).
- Statistical traffic metrics (packet rate, bitrate, mean packet size).
- Configurable port heuristics (explicitly treated as heuristics, never universal truths).
- User intent overrides with explicit expiration timestamps and injectable clocks.

Safety and Privacy Invariants:
- Strictly metadata-only: zero payload inspection, zero decryption, zero access to application secrets.
- Deterministic evaluation: identical flow metadata and clock input yield identical ClassificationResult.
- Injectable clock: all time-dependent logic accepts an explicit timestamp or injectable time_fn
  for deterministic testing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Set, List, Callable, Mapping

VALID_TRAFFIC_CLASSES: Set[str] = {"interactive", "streaming", "bulk", "unknown"}

# Standard DSCP definitions (RFC 2597, RFC 3246)
DSCP_EF: int = 46       # Expedited Forwarding (VoIP / Interactive)
DSCP_CS5: int = 40      # Class Selector 5 (Call signaling / Gaming)
DSCP_AF41: int = 34     # Assured Forwarding 41 (Interactive Video)
DSCP_AF31: int = 26     # Assured Forwarding 31 (Streaming Video)
DSCP_CS0: int = 0       # Best Effort (Default bulk)
DSCP_CS1: int = 8       # Scavenger / Low Priority Bulk


@dataclass(frozen=True)
class FlowMetadata:
    """Metadata-only summary of an observed network flow.

    Contains only transport, network, and statistical characteristics.
    No packet payload content is ever captured or processed.
    """

    protocol: str                       # 'udp', 'tcp', 'icmp', etc.
    src_ip: str
    dst_ip: str
    src_port: Optional[int] = None
    dst_port: Optional[int] = None
    packet_count: int = 0
    byte_count: int = 0
    packet_rate_pps: float = 0.0        # Packets per second
    bitrate_bps: float = 0.0            # Bits per second
    mean_packet_size_bytes: float = 0.0
    dscp: Optional[int] = None          # Differentiated Services Code Point (0-63)
    last_seen_timestamp: float = 0.0

    @property
    def flow_id(self) -> str:
        """Construct canonical 5-tuple flow identifier."""
        p = self.protocol.lower()
        sp = self.src_port if self.src_port is not None else 0
        dp = self.dst_port if self.dst_port is not None else 0
        return f"{p}:{self.src_ip}:{sp}->{self.dst_ip}:{dp}"

    def __post_init__(self) -> None:
        import math
        if not isinstance(self.protocol, str) or not self.protocol:
            raise ValueError(f"protocol must be a non-empty string, got {self.protocol!r}")
        for name, val in [
            ("packet_rate_pps", self.packet_rate_pps),
            ("bitrate_bps", self.bitrate_bps),
            ("mean_packet_size_bytes", self.mean_packet_size_bytes),
            ("last_seen_timestamp", self.last_seen_timestamp),
        ]:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be a real number, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} cannot be NaN or infinite")
            if val < 0.0:
                raise ValueError(f"{name} must be non-negative, got {val}")
        for name, val in [("packet_count", self.packet_count), ("byte_count", self.byte_count)]:
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{name} must be an integer, got {type(val).__name__}")
            if val < 0:
                raise ValueError(f"{name} must be non-negative, got {val}")
        if self.src_port is not None and not (0 <= self.src_port <= 65535):
            raise ValueError(f"src_port must be in [0, 65535], got {self.src_port}")
        if self.dst_port is not None and not (0 <= self.dst_port <= 65535):
            raise ValueError(f"dst_port must be in [0, 65535], got {self.dst_port}")
        if self.dscp is not None and not (0 <= self.dscp <= 63):
            raise ValueError(f"dscp must be in [0, 63], got {self.dscp}")


@dataclass(frozen=True)
class ClassificationResult:
    """Immutable outcome of a traffic classification decision."""

    flow_id: str
    traffic_class: str                  # One of 'interactive', 'streaming', 'bulk', 'unknown'
    confidence: float                   # 0.0 (uncertain) to 1.0 (certain / user intent)
    reason: str                         # Transparent rationale explaining the decision
    is_override: bool = False           # True if decision originates from an active user intent
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.traffic_class not in VALID_TRAFFIC_CLASSES:
            raise ValueError(f"Invalid traffic_class '{self.traffic_class}'; must be in {VALID_TRAFFIC_CLASSES}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")


@dataclass(frozen=True)
class UserIntent:
    """User-specified classification override with mandatory expiration."""

    intent_id: str
    target_class: str                   # 'interactive', 'streaming', 'bulk'
    created_at: float                   # Monotonic or UNIX timestamp
    expires_at: float                   # Strict expiration timestamp
    description: str = ""
    protocol: Optional[str] = None      # e.g., 'udp', 'tcp', or None for all
    src_ip: Optional[str] = None
    dst_ip: Optional[str] = None
    src_port: Optional[int] = None
    dst_port: Optional[int] = None

    def __post_init__(self) -> None:
        import math
        if self.target_class not in {"interactive", "streaming", "bulk"}:
            raise ValueError(f"target_class must be 'interactive', 'streaming', or 'bulk', got '{self.target_class}'")
        for name, val in [("created_at", self.created_at), ("expires_at", self.expires_at)]:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be a real number, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} cannot be NaN or infinite")
        if self.created_at < 0:
            raise ValueError(f"created_at must be non-negative, got {self.created_at}")
        if self.expires_at <= self.created_at:
            raise ValueError(
                f"expires_at ({self.expires_at}) must be strictly greater than created_at ({self.created_at})"
            )
        # Require at least one filter criterion to prevent unbounded wildcard overrides
        if all(f is None for f in (self.protocol, self.src_ip, self.dst_ip, self.src_port, self.dst_port)):
            raise ValueError(
                "UserIntent must specify at least one filter criterion (protocol, src_ip, dst_ip, src_port, or dst_port) "
                "to prevent unbounded wildcard overrides of unrelated traffic."
            )

    def is_active(self, current_time: float) -> bool:
        """Return True if intent is active at current_time."""
        return self.created_at <= current_time < self.expires_at

    def matches(self, flow: FlowMetadata) -> bool:
        """Check if this intent matches the given flow's metadata."""
        if self.protocol is not None and self.protocol.lower() != flow.protocol.lower():
            return False
        if self.src_ip is not None and self.src_ip != flow.src_ip:
            return False
        if self.dst_ip is not None and self.dst_ip != flow.dst_ip:
            return False
        if self.src_port is not None and self.src_port != flow.src_port:
            return False
        if self.dst_port is not None and self.dst_port != flow.dst_port:
            return False
        return True


class UserIntentRegistry:
    """Manages active user intents, expiration pruning, and matching."""

    def __init__(self) -> None:
        self._intents: Dict[str, UserIntent] = {}

    def add_intent(self, intent: UserIntent) -> None:
        """Register or replace a user intent."""
        if not isinstance(intent, UserIntent):
            raise TypeError(f"intent must be UserIntent, got {type(intent).__name__}")
        self._intents[intent.intent_id] = intent

    def remove_intent(self, intent_id: str) -> bool:
        """Remove intent by ID; returns True if found and removed."""
        return self._intents.pop(intent_id, None) is not None

    def get_intent(self, intent_id: str) -> Optional[UserIntent]:
        """Fetch intent by ID."""
        return self._intents.get(intent_id)

    def prune_expired(self, current_time: float) -> int:
        """Remove all expired intents. Returns count of pruned intents."""
        expired = [iid for iid, it in self._intents.items() if not it.is_active(current_time)]
        for iid in expired:
            del self._intents[iid]
        return len(expired)

    def find_matching_intent(self, flow: FlowMetadata, current_time: float) -> Optional[UserIntent]:
        """Return the newest active intent matching the flow, or None."""
        matching: List[UserIntent] = []
        for it in self._intents.values():
            if it.is_active(current_time) and it.matches(flow):
                matching.append(it)
        if not matching:
            return None
        # Deterministic sort: newest created_at first, tie-break by intent_id
        matching.sort(key=lambda it: (it.created_at, it.intent_id), reverse=True)
        return matching[0]

    def list_active(self, current_time: float) -> List[UserIntent]:
        """Return list of all currently active intents."""
        return [it for it in self._intents.values() if it.is_active(current_time)]

    def clear(self) -> int:
        """Remove all registered user intents."""
        count = len(self._intents)
        self._intents.clear()
        return count


class TrafficClassifier:
    """Metadata-based traffic classifier with heuristic scoring and intent overrides."""

    # Default heuristic ports (clearly documented as project heuristics, not universal truths)
    DEFAULT_HEURISTIC_PORTS: Dict[str, Set[int]] = {
        "interactive": {5004, 5060, 3478, 27015},      # RTP, SIP, STUN, Steam gaming
        "streaming": {1935, 554, 8080},                 # RTMP, RTSP, HTTP alternate video
        "bulk": {5201, 20, 21, 22, 80, 443},            # iperf3, FTP, SSH, Web download
    }

    def __init__(
        self,
        intent_registry: Optional[UserIntentRegistry] = None,
        time_fn: Optional[Callable[[], float]] = None,
        heuristic_ports: Optional[Mapping[str, Set[int]]] = None,
    ) -> None:
        self.intent_registry: UserIntentRegistry = intent_registry or UserIntentRegistry()
        self.time_fn: Callable[[], float] = time_fn or time.time
        self.heuristic_ports: Dict[str, Set[int]] = {
            cls_name: set(ports)
            for cls_name, ports in (heuristic_ports or self.DEFAULT_HEURISTIC_PORTS).items()
        }

    def classify(
        self,
        flow: FlowMetadata,
        current_time: Optional[float] = None,
    ) -> ClassificationResult:
        """Classify a flow using user intents first, then metadata heuristics.

        Args:
            flow: FlowMetadata containing header and traffic rate properties.
            current_time: Optional explicit timestamp (uses self.time_fn if omitted).

        Returns:
            ClassificationResult with class, confidence, explicit reasoning, and override status.
        """
        now = current_time if current_time is not None else self.time_fn()
        import math
        if isinstance(now, bool) or not isinstance(now, (int, float)):
            raise TypeError(f"current_time must be a real number, got {type(now).__name__}")
        if math.isnan(now) or math.isinf(now):
            raise ValueError(f"current_time cannot be NaN or infinite, got {now}")

        # 1. User Intent Check (highest precedence)
        matching_intent = self.intent_registry.find_matching_intent(flow, now)
        if matching_intent is not None:
            rem_s = matching_intent.expires_at - now
            return ClassificationResult(
                flow_id=flow.flow_id,
                traffic_class=matching_intent.target_class,
                confidence=1.0,
                reason=(
                    f"User intent '{matching_intent.intent_id}' override "
                    f"(target: {matching_intent.target_class}, expires in {rem_s:.1f}s, "
                    f"desc: '{matching_intent.description}')"
                ),
                is_override=True,
                timestamp=now,
            )

        # 2. Metadata Heuristic Scoring
        scores: Dict[str, float] = {"interactive": 0.0, "streaming": 0.0, "bulk": 0.0}
        reasons_list: List[str] = []

        proto = flow.protocol.lower()
        dst_port = flow.dst_port
        src_port = flow.src_port
        dscp = flow.dscp

        # Heuristic Signal A: DSCP DiffServ Code Point
        if dscp is not None:
            if dscp in (DSCP_EF, DSCP_CS5, DSCP_AF41):
                scores["interactive"] += 0.45
                reasons_list.append(f"DSCP {dscp} matches interactive priority")
            elif dscp in (DSCP_AF31, 28, 30):  # AF31, AF32, AF33
                scores["streaming"] += 0.40
                reasons_list.append(f"DSCP {dscp} matches streaming priority")
            elif dscp in (DSCP_CS0, DSCP_CS1):
                scores["bulk"] += 0.15
                reasons_list.append(f"DSCP {dscp} matches best-effort/bulk")

        # Heuristic Signal B: Destination / Source Ports (project heuristics)
        for check_port in (dst_port, src_port):
            if check_port is None:
                continue
            if check_port in self.heuristic_ports.get("interactive", set()):
                scores["interactive"] += 0.40
                reasons_list.append(f"Port {check_port} in interactive heuristic list")
                break
            elif check_port in self.heuristic_ports.get("streaming", set()):
                scores["streaming"] += 0.35
                reasons_list.append(f"Port {check_port} in streaming heuristic list")
                break
            elif check_port in self.heuristic_ports.get("bulk", set()):
                scores["bulk"] += 0.30
                reasons_list.append(f"Port {check_port} in bulk heuristic list")
                break

        # Heuristic Signal C: Traffic Pacing and Packet Size Characteristics
        # VoIP / Real-time interactive: typically small packets (<= 300 bytes), steady rate
        if proto == "udp":
            if 0 < flow.mean_packet_size_bytes <= 300 and flow.packet_rate_pps >= 10:
                scores["interactive"] += 0.35
                reasons_list.append(
                    f"UDP small packets ({flow.mean_packet_size_bytes:.0f}B) at {flow.packet_rate_pps:.0f}pps "
                    "matches interactive pacing"
                )
            elif flow.mean_packet_size_bytes > 800 and flow.bitrate_bps > 5_000_000:
                # High-rate UDP could be QUIC bulk or fast streaming
                scores["streaming"] += 0.20
                scores["bulk"] += 0.20
                reasons_list.append("High-rate UDP with large packets (candidate streaming/bulk)")

        # TCP Traffic:
        if proto == "tcp":
            if flow.mean_packet_size_bytes >= 1000 and flow.bitrate_bps >= 5_000_000:
                scores["bulk"] += 0.45
                reasons_list.append(
                    f"TCP MTU-sized packets ({flow.mean_packet_size_bytes:.0f}B) and high throughput "
                    f"({flow.bitrate_bps / 1e6:.1f} Mbps) matches bulk transfer"
                )
            elif 400 < flow.mean_packet_size_bytes < 1000 and 1_000_000 <= flow.bitrate_bps < 15_000_000:
                scores["streaming"] += 0.30
                reasons_list.append(
                    f"TCP moderate packet size ({flow.mean_packet_size_bytes:.0f}B) and rate "
                    f"({flow.bitrate_bps / 1e6:.1f} Mbps) matches streaming"
                )

        # 3. Decision Resolution
        sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_class, best_score = sorted_scores[0]
        second_score = sorted_scores[1][1]

        # Require a minimum score threshold and sufficient margin to declare certainty
        CONFIDENCE_THRESHOLD = 0.40
        if best_score < CONFIDENCE_THRESHOLD or (best_score - second_score < 0.05 and best_score < 0.60):
            reason_str = (
                "Ambiguous traffic signals; insufficient confidence to classify definitively. "
                f"Scores: {scores}. Reasons: {'; '.join(reasons_list) if reasons_list else 'No strong signatures'}"
            )
            return ClassificationResult(
                flow_id=flow.flow_id,
                traffic_class="unknown",
                confidence=round(min(0.35, best_score), 2),
                reason=reason_str,
                is_override=False,
                timestamp=now,
            )

        # Normalization of heuristic confidence into [0.45, 0.95] (1.0 reserved for user overrides)
        raw_conf = min(0.95, 0.50 + best_score * 0.45)
        conf = round(raw_conf, 2)
        reason_str = f"Heuristic classification: {'; '.join(reasons_list)}"

        return ClassificationResult(
            flow_id=flow.flow_id,
            traffic_class=best_class,
            confidence=conf,
            reason=reason_str,
            is_override=False,
            timestamp=now,
        )
