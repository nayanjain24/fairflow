"""Policy representation and configuration for FairFlow.

Defines the Policy dataclass representing per-class rate floors, ceilings,
priorities, and leaf qdiscs.
"""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass(frozen=True)
class ClassPolicy:
    """QoS policy settings for a single traffic class.

    Inputs:
        rate_floor_mbps: Minimum guaranteed rate floor (Mbit/s). Must be >= 0.
        rate_ceiling_mbps: Maximum rate ceiling (Mbit/s). Must be >= rate_floor_mbps.
        priority: HTB priority band (1 = highest priority).
        leaf_qdisc: Leaf queue discipline (e.g. 'fq_codel', 'pfifo').

    Failure handling:
        Raises ValueError if rate_floor_mbps < 0 or rate_ceiling_mbps < rate_floor_mbps.
    """

    rate_floor_mbps: float
    rate_ceiling_mbps: float
    priority: int
    leaf_qdisc: str = "fq_codel"

    def __post_init__(self) -> None:
        if self.rate_floor_mbps < 0:
            raise ValueError(f"rate_floor_mbps must be non-negative, got {self.rate_floor_mbps}")
        if self.rate_ceiling_mbps < self.rate_floor_mbps:
            raise ValueError(
                f"rate_ceiling_mbps ({self.rate_ceiling_mbps}) cannot be less than "
                f"rate_floor_mbps ({self.rate_floor_mbps})"
            )
        if self.priority < 0:
            raise ValueError(f"priority must be non-negative, got {self.priority}")


@dataclass(frozen=True)
class Policy:
    """Complete QoS policy applied across traffic classes on an emulated link.

    Inputs:
        link_capacity_mbps: Total shaped link capacity in Mbit/s. Must be > 0.
        classes: Mapping of class name (e.g. 'interactive', 'streaming', 'bulk') to ClassPolicy.

    Failure handling:
        Raises ValueError if link_capacity_mbps <= 0 or if classes dictionary is empty.
    """

    link_capacity_mbps: float
    classes: Dict[str, ClassPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.link_capacity_mbps <= 0:
            raise ValueError(f"link_capacity_mbps must be positive, got {self.link_capacity_mbps}")
        if not self.classes:
            raise ValueError("Policy must contain at least one traffic class")
