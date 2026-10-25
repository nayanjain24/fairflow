"""Unit tests for src/fairflow/contract.py.

Tests are self-contained: they build in-memory YAML strings rather than
touching contract.yaml, so they run as a normal user with no side-effects.

Covers:
  - Happy path: the real contract.yaml values pass all four validations.
  - V1: guardrail must be > target for each paired metric.
  - V2: sum of floor_mbps must not exceed link.default_capacity_mbps.
  - V3: breach_windows * window_s must be < canary.duration_s.
  - V4: missing keys and non-positive values each raise ContractError.
  - Immutability: the returned Contract object cannot be mutated.
  - FileNotFoundError for a non-existent path.
"""

import textwrap
import tempfile
from pathlib import Path

import pytest

from src.fairflow.contract import load_contract, Contract, ContractError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write *content* to a temp contract.yaml and return its path."""
    p = tmp_path / "contract.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# A minimal valid contract that satisfies all four constraints.
# Values match the real contract.yaml committed by the human author.
VALID_YAML = """
    version: 1
    measurement:
      window_s: 2
    interactive:
      added_delay_target_ms: 30
      added_delay_guardrail_ms: 80
      jitter_target_ms: 10
      jitter_guardrail_ms: 30
      loss_target_pct: 0.5
      loss_guardrail_pct: 2.0
      floor_mbps: 2.0
    streaming:
      floor_mbps: 8.0
      added_delay_guardrail_ms: 200
    bulk:
      floor_mbps: 2.0
    canary:
      duration_s: 10
      breach_windows: 2
    recovery:
      good_windows: 3
    policy:
      max_step_pct: 25
      min_interval_s: 15
      deadband_pct: 10
    link:
      default_capacity_mbps: 100
"""


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_contract_loads_and_returns_contract_object(tmp_path: Path) -> None:
    """A fully compliant YAML returns a Contract with correct typed values."""
    p = _write_yaml(tmp_path, VALID_YAML)
    c = load_contract(p)

    assert isinstance(c, Contract)
    assert c.measurement_window_s == 2.0
    assert c.interactive_added_delay_target_ms == 30.0
    assert c.interactive_added_delay_guardrail_ms == 80.0
    assert c.interactive_jitter_target_ms == 10.0
    assert c.interactive_jitter_guardrail_ms == 30.0
    assert c.interactive_loss_target_pct == 0.5
    assert c.interactive_loss_guardrail_pct == 2.0
    assert c.interactive_floor_mbps == 2.0
    assert c.streaming_floor_mbps == 8.0
    assert c.streaming_added_delay_guardrail_ms == 200.0
    assert c.bulk_floor_mbps == 2.0
    assert c.canary_duration_s == 10.0
    assert c.canary_breach_windows == 2.0
    assert c.recovery_good_windows == 3.0
    assert c.policy_max_step_pct == 25.0
    assert c.policy_min_interval_s == 15.0
    assert c.policy_deadband_pct == 10.0
    assert c.link_default_capacity_mbps == 100.0


def test_valid_contract_loads_real_file() -> None:
    """The actual committed contract.yaml must pass all validations."""
    real = Path(__file__).resolve().parent.parent / "contract.yaml"
    if not real.exists():
        pytest.skip("contract.yaml not present in repo root")
    c = load_contract(real)
    # Spot-check a few real values
    assert c.interactive_added_delay_guardrail_ms == 80.0
    assert c.interactive_jitter_guardrail_ms == 30.0
    assert c.link_default_capacity_mbps == 100.0


# ---------------------------------------------------------------------------
# V1: guardrail > target
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("broken_key,broken_value,desc", [
    ("added_delay_guardrail_ms", 30,    "guardrail equals target"),
    ("added_delay_guardrail_ms", 20,    "guardrail less than target"),
    ("jitter_guardrail_ms",      10,    "jitter guardrail equals target"),
    ("jitter_guardrail_ms",       5,    "jitter guardrail less than target"),
    ("loss_guardrail_pct",       0.5,   "loss guardrail equals target"),
    ("loss_guardrail_pct",       0.1,   "loss guardrail less than target"),
])
def test_v1_guardrail_must_exceed_target(
    tmp_path: Path, broken_key: str, broken_value: float, desc: str
) -> None:
    """V1: any guardrail <= its paired target must be rejected with ContractError."""
    yaml_text = VALID_YAML.replace(
        # replace the first occurrence of the key under [interactive]
        f"      {broken_key}:",
        f"      {broken_key}: {broken_value}\n      _orig_{broken_key}:",
        1,
    )
    # Build YAML differently — inject the bad value directly
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    raw["interactive"][broken_key] = broken_value
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="V1 violated"):
        load_contract(p)


# ---------------------------------------------------------------------------
# V2: sum of floors <= link capacity
# ---------------------------------------------------------------------------

def test_v2_floors_exceed_capacity_raises(tmp_path: Path) -> None:
    """V2: floors that sum beyond link capacity must raise ContractError."""
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    # Push interactive floor so that 60 + 8 + 2 = 70 <= 100 is fine,
    # but 95 + 8 + 2 = 105 > 100 must fail.
    raw["interactive"]["floor_mbps"] = 95.0
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="V2 violated"):
        load_contract(p)


def test_v2_floors_exactly_at_capacity_pass(tmp_path: Path) -> None:
    """V2: floors summing to exactly the link capacity are allowed (<=, not <)."""
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    # 90 + 8 + 2 = 100 == 100 → should pass
    raw["interactive"]["floor_mbps"] = 90.0
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    c = load_contract(p)
    assert c.interactive_floor_mbps == 90.0


# ---------------------------------------------------------------------------
# V3: breach_windows * window_s < canary.duration_s
# ---------------------------------------------------------------------------

def test_v3_breach_time_equals_canary_duration_raises(tmp_path: Path) -> None:
    """V3: breach_windows * window_s == canary.duration_s must be rejected."""
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    # 5 * 2 = 10 == 10 → equal, not strictly less
    raw["canary"]["breach_windows"] = 5
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="V3 violated"):
        load_contract(p)


def test_v3_breach_time_exceeds_canary_duration_raises(tmp_path: Path) -> None:
    """V3: breach_windows * window_s > canary.duration_s must be rejected."""
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    # 6 * 2 = 12 > 10 → too many breach windows
    raw["canary"]["breach_windows"] = 6
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="V3 violated"):
        load_contract(p)


def test_v3_valid_breach_windows_pass(tmp_path: Path) -> None:
    """V3: breach_windows * window_s strictly < canary.duration_s must pass."""
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    # 4 * 2 = 8 < 10 → fine
    raw["canary"]["breach_windows"] = 4
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    c = load_contract(p)
    assert c.canary_breach_windows == 4.0


# ---------------------------------------------------------------------------
# V4: missing keys
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section,key", [
    ("measurement", "window_s"),
    ("interactive", "added_delay_target_ms"),
    ("interactive", "added_delay_guardrail_ms"),
    ("interactive", "jitter_target_ms"),
    ("interactive", "jitter_guardrail_ms"),
    ("interactive", "loss_target_pct"),
    ("interactive", "loss_guardrail_pct"),
    ("interactive", "floor_mbps"),
    ("streaming",   "floor_mbps"),
    ("streaming",   "added_delay_guardrail_ms"),
    ("bulk",        "floor_mbps"),
    ("canary",      "duration_s"),
    ("canary",      "breach_windows"),
    ("recovery",    "good_windows"),
    ("policy",      "max_step_pct"),
    ("policy",      "min_interval_s"),
    ("policy",      "deadband_pct"),
    ("link",        "default_capacity_mbps"),
])
def test_v4_missing_key_raises(tmp_path: Path, section: str, key: str) -> None:
    """V4: every required key, when removed, must raise ContractError."""
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    del raw[section][key]
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="missing from contract.yaml"):
        load_contract(p)


@pytest.mark.parametrize("section,key,bad_value", [
    ("measurement",  "window_s",                   0),
    ("measurement",  "window_s",                  -1),
    ("interactive",  "added_delay_target_ms",       0),
    ("interactive",  "jitter_guardrail_ms",        -5),
    ("link",         "default_capacity_mbps",       0),
])
def test_v4_non_positive_value_raises(
    tmp_path: Path, section: str, key: str, bad_value: float
) -> None:
    """V4: any required key set to zero or negative must raise ContractError."""
    import yaml
    raw = yaml.safe_load(textwrap.dedent(VALID_YAML))
    raw[section][key] = bad_value
    p = tmp_path / "contract.yaml"
    p.write_text(yaml.dump(raw), encoding="utf-8")

    with pytest.raises(ContractError, match="must be > 0"):
        load_contract(p)


# ---------------------------------------------------------------------------
# File not found
# ---------------------------------------------------------------------------

def test_file_not_found_raises(tmp_path: Path) -> None:
    """load_contract raises FileNotFoundError for a non-existent path."""
    with pytest.raises(FileNotFoundError):
        load_contract(tmp_path / "no_such_file.yaml")


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------

def test_contract_is_immutable(tmp_path: Path) -> None:
    """The returned Contract object must not be mutable (frozen dataclass)."""
    p = _write_yaml(tmp_path, VALID_YAML)
    c = load_contract(p)
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        c.measurement_window_s = 999.0  # type: ignore[misc]
