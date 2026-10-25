#!/usr/bin/env python3
"""compute_noise_floor_baseline.py

Reads all results/noise_floor_<timestamp>.json files, computes min/median/max
aggregates, and optionally reads contract.yaml to compute headroom margins.

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
    files = sorted(results_dir.glob("noise_floor_*.json"))
    runs = []
    skipped = []
    for f in files:
        if f.name == "noise_floor_summary.json":
            continue
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
        print(
            f"INFO: Skipped {len(skipped)} run(s) with < {min_packets} packets: "
            + ", ".join(f"{name} ({n})" for name, n in skipped),
            file=sys.stderr,
        )
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
    """Try to read contract.yaml; return None if not present."""
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


def compute_margins(contract: dict, worst_p99: float, worst_jitter: float) -> dict:
    """
    Compute headroom ratios: contract_limit / observed_value.
    Ratio > 1 means observed is safely within the contract limit.
    Reads: constraints.voice.max_delay_ms and constraints.voice.max_jitter_ms.
    """
    margins = {}
    try:
        voice = contract["constraints"]["voice"]
        max_delay = float(voice["max_delay_ms"])
        margins["p99_delay_headroom"] = {
            "contract_limit_ms": max_delay,
            "observed_worst_p99_ms": worst_p99,
            "ratio": round(max_delay / worst_p99, 2) if worst_p99 > 0 else None,
            "note": "ratio > 1 means observed is within contract",
        }
    except (KeyError, TypeError):
        margins["p99_delay_headroom"] = {
            "note": "key constraints.voice.max_delay_ms not found in contract.yaml"
        }

    try:
        voice = contract["constraints"]["voice"]
        max_jitter = float(voice["max_jitter_ms"])
        margins["jitter_headroom"] = {
            "contract_limit_ms": max_jitter,
            "observed_worst_jitter_ms": worst_jitter,
            "ratio": round(max_jitter / worst_jitter, 2) if worst_jitter > 0 else None,
            "note": "ratio > 1 means observed is within contract",
        }
    except (KeyError, TypeError):
        margins["jitter_headroom"] = {
            "note": "key constraints.voice.max_jitter_ms not found in contract.yaml"
        }

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
            f"ERROR: Need at least 2 valid runs; found {len(runs)}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Aggregating {len(runs)} run(s):", [r["_source_file"] for r in runs])

    baseline = {
        "computed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_count": len(runs),
        "source_files": [r["_source_file"] for r in runs],
        "aggregate_ms": {
            "p50_delay": aggregate_field(runs, "p50_delay_ms"),
            "p99_delay": aggregate_field(runs, "p99_delay_ms"),
            "mean_delay": aggregate_field(runs, "mean_delay_ms"),
            "jitter": aggregate_field(runs, "jitter_ms"),
            "loss_pct": aggregate_field(runs, "loss_pct"),
        },
    }

    worst_p99 = baseline["aggregate_ms"]["p99_delay"]["max"]
    worst_jitter = baseline["aggregate_ms"]["jitter"]["max"]

    contract = load_contract(REPO_ROOT)
    if contract is None:
        baseline["contract_margins"] = {
            "note": "contract.yaml not yet committed; rerun after it is added"
        }
        print("INFO: contract.yaml not found; margins skipped.")
    else:
        baseline["contract_margins"] = compute_margins(contract, worst_p99, worst_jitter)
        print("INFO: contract.yaml found; margins computed.")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as fh:
        json.dump(baseline, fh, indent=2)
    print(f"Written: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
