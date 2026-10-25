#!/usr/bin/env python3
"""compute_noise_floor_baseline.py

Reads all results/noise_floor_<timestamp>.json files (excluding noise_floor_summary.json),
computes min/median/max aggregates across the full runs, and optionally reads contract.yaml
to compute headroom margins (contract guardrail / worst observed noise-floor value).

Margins are printed with their exact contract.yaml key names so they are auditable.

Writes results/noise_floor_baseline.json.

Usage:
    python3 scripts/compute_noise_floor_baseline.py [--min-packets N]

Options:
    --min-packets N   Exclude runs with fewer than N packets (default: 1000)
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
OUTPUT_FILE = RESULTS_DIR / "noise_floor_baseline.json"


def load_runs(results_dir: Path, min_packets: int) -> list:
    """Load all timestamped noise-floor JSON files from results_dir."""
    # Only match timestamped run files: noise_floor_YYYYMMDD_HHMMSS.json
    # This deliberately excludes noise_floor_summary.json and noise_floor_baseline.json.
    import re as _re
    _TS_RE = _re.compile(r"^noise_floor_\d{8}_\d{6}\.json$")
    files = sorted(f for f in results_dir.glob("noise_floor_*.json") if _TS_RE.match(f.name))
    runs = []
    skipped = []
    for f in files:
        try:
            with f.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARNING: could not read {f.name}: {exc}", file=sys.stderr)
            continue
        n_sent = data.get("packets_sent", 0)
        if n_sent < min_packets:
            skipped.append((f.name, n_sent))
            continue
        data["_source_file"] = f.name
        runs.append(data)

    if skipped:
        names = ", ".join(f"{name} ({n} pkts)" for name, n in skipped)
        print(f"INFO: Skipped {len(skipped)} run(s) with < {min_packets} packets: {names}",
              file=sys.stderr)
    return runs


def median(values: list) -> float:
    """Return the median of a list of numbers."""
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def aggregate_field(runs: list, field: str) -> dict:
    """Return min/median/max for a numeric field across all runs."""
    values = [r[field] for r in runs if field in r]
    return {
        "min": round(min(values), 4),
        "median": round(median(values), 4),
        "max": round(max(values), 4),
    }


def load_contract(repo_root: Path):
    """Try to read contract.yaml; return None if not present or pyyaml missing."""
    contract_path = repo_root / "contract.yaml"
    if not contract_path.exists():
        return None
    try:
        import yaml
    except ImportError:
        print("WARNING: pyyaml not installed; skipping contract margins", file=sys.stderr)
        return None
    with contract_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def compute_margins(contract: dict, worst_p99_ms: float, worst_jitter_ms: float) -> dict:
    """Compute headroom ratios for the two delay metrics.

    Formula: contract_guardrail / worst_observed_noise_floor.
    A ratio > 1 means the noise floor is comfortably below the guardrail.
    Keys are printed verbatim from contract.yaml so the computation is auditable.
    """
    margins = {}

    # --- added-delay headroom ---
    key_delay = "interactive.added_delay_guardrail_ms"
    try:
        guardrail_delay = float(contract["interactive"]["added_delay_guardrail_ms"])
        ratio_delay = round(guardrail_delay / worst_p99_ms, 2) if worst_p99_ms > 0 else None
        margins[key_delay] = {
            "contract_value_ms": guardrail_delay,
            "worst_noise_floor_p99_ms": worst_p99_ms,
            "ratio": ratio_delay,
            "note": "contract guardrail / worst observed p99; ratio > 1 means noise floor is safely below guardrail",
        }
        print(f"  {key_delay} = {guardrail_delay} ms  |  "
              f"worst p99 = {worst_p99_ms} ms  |  ratio = {ratio_delay}")
    except (KeyError, TypeError) as exc:
        margins[key_delay] = {"error": str(exc)}
        print(f"  WARNING: could not read {key_delay}: {exc}", file=sys.stderr)

    # --- jitter headroom ---
    key_jitter = "interactive.jitter_guardrail_ms"
    try:
        guardrail_jitter = float(contract["interactive"]["jitter_guardrail_ms"])
        ratio_jitter = round(guardrail_jitter / worst_jitter_ms, 2) if worst_jitter_ms > 0 else None
        margins[key_jitter] = {
            "contract_value_ms": guardrail_jitter,
            "worst_noise_floor_jitter_ms": worst_jitter_ms,
            "ratio": ratio_jitter,
            "note": "contract guardrail / worst observed jitter; ratio > 1 means noise floor is safely below guardrail",
        }
        print(f"  {key_jitter} = {guardrail_jitter} ms  |  "
              f"worst jitter = {worst_jitter_ms} ms  |  ratio = {ratio_jitter}")
    except (KeyError, TypeError) as exc:
        margins[key_jitter] = {"error": str(exc)}
        print(f"  WARNING: could not read {key_jitter}: {exc}", file=sys.stderr)

    return margins


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute noise-floor aggregate baseline.")
    parser.add_argument(
        "--min-packets",
        type=int,
        default=1000,
        help="Exclude runs with fewer than this many packets (default: 1000)",
    )
    args = parser.parse_args()

    runs = load_runs(RESULTS_DIR, args.min_packets)
    if len(runs) < 2:
        print(
            f"ERROR: Need at least 2 valid runs for a meaningful baseline; found {len(runs)}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Aggregating {len(runs)} run(s):")
    for r in runs:
        print(f"  {r['_source_file']}")

    agg_p50  = aggregate_field(runs, "p50_delay_ms")
    agg_p99  = aggregate_field(runs, "p99_delay_ms")
    agg_mean = aggregate_field(runs, "mean_delay_ms")
    agg_jit  = aggregate_field(runs, "jitter_ms")
    agg_loss = aggregate_field(runs, "loss_pct")

    worst_p99    = agg_p99["max"]
    worst_jitter = agg_jit["max"]

    baseline: dict = {
        "computed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_count": len(runs),
        "source_files": [r["_source_file"] for r in runs],
        "aggregate_ms": {
            "p50_delay":  agg_p50,
            "p99_delay":  agg_p99,
            "mean_delay": agg_mean,
            "jitter":     agg_jit,
            "loss_pct":   agg_loss,
        },
    }

    contract = load_contract(REPO_ROOT)
    if contract is None:
        baseline["contract_margins"] = {
            "note": "contract.yaml not found; rerun after it is committed"
        }
        print("INFO: contract.yaml not found; margins skipped.")
    else:
        print("\nContract margins (guardrail / worst noise-floor value):")
        baseline["contract_margins"] = compute_margins(contract, worst_p99, worst_jitter)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as fh:
        json.dump(baseline, fh, indent=2)
    print(f"\nWritten: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
