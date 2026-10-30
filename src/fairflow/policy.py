"""Policy representation and configuration for FairFlow.

Defines the Policy dataclass representing per-class rate floors, ceilings,
priorities, and leaf qdiscs with strict numeric and structure validation.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Tuple

SUPPORTED_LEAF_QDISCS: Tuple[str, ...] = ("fq_codel", "pfifo", "cake")
VALID_CLASS_NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")


def _validate_numeric(val: Any, name: str, min_val: float = 0.0) -> float:
    """Validate that val is a finite real number >= min_val (rejecting bool, NaN, inf)."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise TypeError(f"{name} must be a real number, got {type(val).__name__} ({val!r})")
    f_val = float(val)
    if math.isnan(f_val):
        raise ValueError(f"{name} cannot be NaN")
    if math.isinf(f_val):
        raise ValueError(f"{name} cannot be infinite")
    if f_val < min_val:
        raise ValueError(f"{name} must be >= {min_val}, got {f_val}")
    return f_val


@dataclass(frozen=True)
class ClassPolicy:
    """QoS policy settings for a single traffic class.

    Inputs:
        rate_floor_mbps: Minimum guaranteed rate floor (Mbit/s). Must be >= 0.
        rate_ceiling_mbps: Maximum rate ceiling (Mbit/s). Must be >= rate_floor_mbps.
        priority: HTB priority band (1 = highest priority). Must be an integer >= 0.
        leaf_qdisc: Leaf queue discipline (one of 'fq_codel', 'pfifo', 'cake').

    Failure handling:
        Raises TypeError on non-numeric types.
        Raises ValueError if rate_floor_mbps < 0, rate_ceiling_mbps < rate_floor_mbps,
        priority < 0, or unsupported leaf_qdisc.
    """

    rate_floor_mbps: float
    rate_ceiling_mbps: float
    priority: int
    leaf_qdisc: str = "fq_codel"

    def __post_init__(self) -> None:
        floor = _validate_numeric(self.rate_floor_mbps, "rate_floor_mbps", min_val=0.0)
        ceil = _validate_numeric(self.rate_ceiling_mbps, "rate_ceiling_mbps", min_val=0.0)

        if ceil < floor:
            raise ValueError(
                f"rate_ceiling_mbps ({ceil}) cannot be less than rate_floor_mbps ({floor})"
            )

        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError(f"priority must be an integer, got {type(self.priority).__name__} ({self.priority!r})")
        if self.priority < 0:
            raise ValueError(f"priority must be non-negative, got {self.priority}")

        if not isinstance(self.leaf_qdisc, str):
            raise TypeError(f"leaf_qdisc must be a string, got {type(self.leaf_qdisc).__name__}")
        if self.leaf_qdisc not in SUPPORTED_LEAF_QDISCS:
            raise ValueError(
                f"Unsupported leaf_qdisc '{self.leaf_qdisc}'; must be one of {SUPPORTED_LEAF_QDISCS}"
            )


@dataclass(frozen=True)
class Policy:
    """Complete QoS policy applied across traffic classes on an emulated link.

    Inputs:
        link_capacity_mbps: Total shaped link capacity in Mbit/s. Must be > 0.
        classes: Mapping of class name (e.g. 'interactive', 'streaming', 'bulk') to ClassPolicy.

    Failure handling:
        Raises TypeError on non-numeric capacity or invalid classes mapping.
        Raises ValueError if link_capacity_mbps <= 0, classes is empty, or class names are invalid.
    """

    link_capacity_mbps: float
    classes: Dict[str, ClassPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        cap = _validate_numeric(self.link_capacity_mbps, "link_capacity_mbps", min_val=0.0)
        if cap <= 0.0:
            raise ValueError(f"link_capacity_mbps must be strictly positive, got {cap}")

        if not isinstance(self.classes, dict):
            raise TypeError(f"classes must be a dict, got {type(self.classes).__name__}")
        if not self.classes:
            raise ValueError("Policy must contain at least one traffic class")

        for class_name, cp in self.classes.items():
            if not isinstance(class_name, str):
                raise TypeError(f"Class identifier must be a string, got {type(class_name).__name__}")
            if not VALID_CLASS_NAME_PATTERN.match(class_name):
                raise ValueError(
                    f"Class identifier '{class_name}' is invalid; must match pattern '^[a-z0-9_]{{1,32}}$'"
                )
            if not isinstance(cp, ClassPolicy):
                raise TypeError(
                    f"Class '{class_name}' policy must be a ClassPolicy instance, got {type(cp).__name__}"
                )
