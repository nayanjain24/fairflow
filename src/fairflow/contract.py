"""contract.py — FairFlow contract loader and validator.

Loads contract.yaml and enforces four structural invariants before any
other module reads the values.  The coding agent must never edit contract.yaml;
only this loader validates it.

Validations (all checked on every load):
  V1  guardrail > target  for every metric that has both.
  V2  sum of floor_mbps (interactive + streaming + bulk) <= link.default_capacity_mbps.
  V3  canary.breach_windows * measurement.window_s < canary.duration_s
       (at least one non-breaching window must be possible inside the canary).
  V4  every required value is present and strictly positive (> 0).

Usage:
    from fairflow.contract import load_contract, Contract

    c = load_contract("contract.yaml")   # raises ContractError on violation
    print(c.interactive_added_delay_guardrail_ms)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ContractError(Exception):
    """Raised when contract.yaml is missing a required key or violates an invariant."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require(mapping: dict, *keys: str, parent: str = "") -> Any:
    """Return mapping[keys[0]][keys[1]]... or raise ContractError with a clear path."""
    node = mapping
    path = parent
    for key in keys:
        path = f"{path}.{key}" if path else key
        if not isinstance(node, dict) or key not in node:
            raise ContractError(f"Required key '{path}' is missing from contract.yaml")
        node = node[key]
    return node


def _positive(value: Any, key: str) -> float:
    """Return float(value) or raise ContractError if not a positive number."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ContractError(f"contract.yaml key '{key}' must be a number, got {value!r}")
    if f <= 0:
        raise ContractError(f"contract.yaml key '{key}' must be > 0, got {f}")
    return f


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Contract:
    """Validated, typed view of contract.yaml.

    All numeric fields are stored as float.  The object is immutable (frozen)
    so downstream modules cannot accidentally mutate it.
    """

    # measurement
    measurement_window_s: float

    # interactive
    interactive_added_delay_target_ms: float
    interactive_added_delay_guardrail_ms: float
    interactive_jitter_target_ms: float
    interactive_jitter_guardrail_ms: float
    interactive_loss_target_pct: float
    interactive_loss_guardrail_pct: float
    interactive_floor_mbps: float

    # streaming
    streaming_floor_mbps: float
    streaming_added_delay_guardrail_ms: float

    # bulk
    bulk_floor_mbps: float

    # canary
    canary_duration_s: float
    canary_breach_windows: float

    # recovery
    recovery_good_windows: float

    # policy
    policy_max_step_pct: float
    policy_min_interval_s: float
    policy_deadband_pct: float

    # link
    link_default_capacity_mbps: float


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_contract(path: str | Path) -> Contract:
    """Load, validate, and return a Contract from *path*.

    Raises:
        FileNotFoundError: if the file does not exist.
        ContractError: if any required key is missing, non-positive, or if
            a structural invariant (V1–V3) is violated.
    """
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ContractError("pyyaml must be installed to load contract.yaml") from exc

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"contract.yaml not found at {p.resolve()}")

    with p.open(encoding="utf-8") as fh:
        raw: dict = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ContractError("contract.yaml must be a YAML mapping at the top level")

    # -----------------------------------------------------------------------
    # V4: All required keys present and positive
    # -----------------------------------------------------------------------
    def get(section: str, key: str) -> float:
        val = _require(raw, section, key)
        return _positive(val, f"{section}.{key}")

    measurement_window_s                   = get("measurement", "window_s")

    interactive_added_delay_target_ms      = get("interactive", "added_delay_target_ms")
    interactive_added_delay_guardrail_ms   = get("interactive", "added_delay_guardrail_ms")
    interactive_jitter_target_ms           = get("interactive", "jitter_target_ms")
    interactive_jitter_guardrail_ms        = get("interactive", "jitter_guardrail_ms")
    interactive_loss_target_pct            = get("interactive", "loss_target_pct")
    interactive_loss_guardrail_pct         = get("interactive", "loss_guardrail_pct")
    interactive_floor_mbps                 = get("interactive", "floor_mbps")

    streaming_floor_mbps                   = get("streaming", "floor_mbps")
    streaming_added_delay_guardrail_ms     = get("streaming", "added_delay_guardrail_ms")

    bulk_floor_mbps                        = get("bulk", "floor_mbps")

    canary_duration_s                      = get("canary", "duration_s")
    canary_breach_windows                  = get("canary", "breach_windows")

    recovery_good_windows                  = get("recovery", "good_windows")

    policy_max_step_pct                    = get("policy", "max_step_pct")
    policy_min_interval_s                  = get("policy", "min_interval_s")
    policy_deadband_pct                    = get("policy", "deadband_pct")

    link_default_capacity_mbps             = get("link", "default_capacity_mbps")

    # -----------------------------------------------------------------------
    # V1: guardrail > target for every metric that has both
    # -----------------------------------------------------------------------
    checks = [
        ("interactive.added_delay_guardrail_ms", interactive_added_delay_guardrail_ms,
         "interactive.added_delay_target_ms",    interactive_added_delay_target_ms),
        ("interactive.jitter_guardrail_ms",      interactive_jitter_guardrail_ms,
         "interactive.jitter_target_ms",         interactive_jitter_target_ms),
        ("interactive.loss_guardrail_pct",       interactive_loss_guardrail_pct,
         "interactive.loss_target_pct",          interactive_loss_target_pct),
    ]
    for g_key, g_val, t_key, t_val in checks:
        if g_val <= t_val:
            raise ContractError(
                f"V1 violated: {g_key} ({g_val}) must be > {t_key} ({t_val})"
            )

    # -----------------------------------------------------------------------
    # V2: sum of service floors <= link capacity
    # -----------------------------------------------------------------------
    total_floors = interactive_floor_mbps + streaming_floor_mbps + bulk_floor_mbps
    if total_floors > link_default_capacity_mbps:
        raise ContractError(
            f"V2 violated: sum of floor_mbps "
            f"({interactive_floor_mbps} + {streaming_floor_mbps} + {bulk_floor_mbps} "
            f"= {total_floors}) exceeds link.default_capacity_mbps ({link_default_capacity_mbps})"
        )

    # -----------------------------------------------------------------------
    # V3: breach_windows * window_s < canary.duration_s
    # -----------------------------------------------------------------------
    breach_time = canary_breach_windows * measurement_window_s
    if breach_time >= canary_duration_s:
        raise ContractError(
            f"V3 violated: canary.breach_windows ({canary_breach_windows}) * "
            f"measurement.window_s ({measurement_window_s}) = {breach_time} "
            f">= canary.duration_s ({canary_duration_s}); "
            "at least one non-breaching window must fit inside the canary"
        )

    return Contract(
        measurement_window_s=measurement_window_s,
        interactive_added_delay_target_ms=interactive_added_delay_target_ms,
        interactive_added_delay_guardrail_ms=interactive_added_delay_guardrail_ms,
        interactive_jitter_target_ms=interactive_jitter_target_ms,
        interactive_jitter_guardrail_ms=interactive_jitter_guardrail_ms,
        interactive_loss_target_pct=interactive_loss_target_pct,
        interactive_loss_guardrail_pct=interactive_loss_guardrail_pct,
        interactive_floor_mbps=interactive_floor_mbps,
        streaming_floor_mbps=streaming_floor_mbps,
        streaming_added_delay_guardrail_ms=streaming_added_delay_guardrail_ms,
        bulk_floor_mbps=bulk_floor_mbps,
        canary_duration_s=canary_duration_s,
        canary_breach_windows=canary_breach_windows,
        recovery_good_windows=recovery_good_windows,
        policy_max_step_pct=policy_max_step_pct,
        policy_min_interval_s=policy_min_interval_s,
        policy_deadband_pct=policy_deadband_pct,
        link_default_capacity_mbps=link_default_capacity_mbps,
    )
