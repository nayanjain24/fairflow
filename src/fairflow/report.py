"""report.py — Generates M2 summary CSVs, markdown reports, and figures."""

import csv
from pathlib import Path
from typing import Dict, Any, List


def write_trial_metrics_csv(trial_records: List[Dict[str, Any]], out_path: Path) -> None:
    """Write trial_metrics.csv containing all executed trial results."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "arm", "trial", "valid", "invalid_reason",
        "congested_added_delay_p99_ms", "added_delay_p95_ms",
        "raw_added_delay_p99_ms", "raw_added_delay_p95_ms",
        "bulk_goodput_mbps", "bulk_goodput_fraction", "call_loss_pct",
        "interactive_target_met", "bulk_floor_met",
        "baseline_p50_ms", "baseline_p99_ms",
        "congested_p50_ms", "congested_p95_ms", "congested_p99_ms",
        "congested_max_ms", "congested_jitter_ms", "sender_lateness_p99_ms",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in trial_records:
            row = {
                "arm": r["arm"],
                "trial": r["trial"],
                "valid": r.get("valid", True),
                "invalid_reason": r.get("invalid_reason", ""),
                "congested_added_delay_p99_ms": r.get("congested_added_delay_p99_ms", 0.0),
                "added_delay_p95_ms": r.get("added_delay_p95_ms", 0.0),
                "raw_added_delay_p99_ms": r.get("raw_added_delay_p99_ms", 0.0),
                "raw_added_delay_p95_ms": r.get("raw_added_delay_p95_ms", 0.0),
                "bulk_goodput_mbps": r.get("bulk_goodput_mbps", 0.0),
                "bulk_goodput_fraction": r.get("bulk_goodput_fraction", 0.0),
                "call_loss_pct": r.get("call_loss_pct", 0.0),
                "interactive_target_met": r.get("interactive_target_met", False),
                "bulk_floor_met": r.get("bulk_floor_met", False),
                "baseline_p50_ms": r.get("baseline", {}).get("p50_ms", 0.0),
                "baseline_p99_ms": r.get("baseline", {}).get("p99_ms", 0.0),
                "congested_p50_ms": r.get("congested", {}).get("p50_ms", 0.0),
                "congested_p95_ms": r.get("congested", {}).get("p95_ms", 0.0),
                "congested_p99_ms": r.get("congested", {}).get("p99_ms", 0.0),
                "congested_max_ms": r.get("congested", {}).get("max_ms", 0.0),
                "congested_jitter_ms": r.get("congested", {}).get("jitter_ms", 0.0),
                "sender_lateness_p99_ms": r.get("sender_lateness_p99_ms", 0.0),
            }
            writer.writerow(row)


def write_summary_by_arm_csv(arm_summaries: Dict[str, Dict[str, Any]], out_path: Path) -> None:
    """Write summary_by_arm.csv with aggregated statistical distributions."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "arm", "n_valid", "n_total", "interactive_target_met",
        "added_delay_p99_median_ms", "added_delay_p99_iqr_ms", "added_delay_p99_ci95_low", "added_delay_p99_ci95_high", "added_delay_p99_cv",
        "bulk_goodput_median_mbps", "bulk_goodput_iqr_mbps", "bulk_goodput_fraction_median",
        "call_loss_median_pct",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for arm, s in arm_summaries.items():
            if s.get("n_valid", 0) == 0:
                writer.writerow({
                    "arm": arm,
                    "n_valid": 0,
                    "n_total": s.get("n_total", 0),
                    "interactive_target_met": s.get("interactive_target_met_ratio", "0/0"),
                })
                continue
            row = {
                "arm": arm,
                "n_valid": s["n_valid"],
                "n_total": s["n_total"],
                "interactive_target_met": s["interactive_target_met"],
                "added_delay_p99_median_ms": s["primary_added_delay_p99_ms"]["median"],
                "added_delay_p99_iqr_ms": s["primary_added_delay_p99_ms"]["iqr"],
                "added_delay_p99_ci95_low": s["primary_added_delay_p99_ms"]["bootstrap_ci95"][0],
                "added_delay_p99_ci95_high": s["primary_added_delay_p99_ms"]["bootstrap_ci95"][1],
                "added_delay_p99_cv": s["primary_added_delay_p99_ms"]["cv"],
                "bulk_goodput_median_mbps": s["secondary_bulk_goodput_mbps"]["median"],
                "bulk_goodput_iqr_mbps": s["secondary_bulk_goodput_mbps"]["iqr"],
                "bulk_goodput_fraction_median": s["secondary_bulk_goodput_fraction"]["median"],
                "call_loss_median_pct": s["secondary_call_loss_pct"]["median"],
            }
            writer.writerow(row)


def generate_markdown_report(
    arm_summaries: Dict[str, Dict[str, Any]],
    metadata: Dict[str, Any],
    out_path: Path,
) -> str:
    """Generate script-only markdown report comparing baseline arms."""
    lines = [
        f"# FairFlow M2 Scenario A Report: {metadata.get('scenario_name', 'scenario_a_baselines')}",
        "",
        f"- **Run ID**: `{metadata.get('run_id')}`",
        f"- **Mode**: `{metadata.get('mode', 'smoke')}`",
        f"- **Timestamp UTC**: `{metadata.get('timestamp_utc')}`",
        f"- **Kernel**: `{metadata.get('kernel', 'Linux 6.8')}`",
        f"- **TCP Congestion Control**: `{metadata.get('tcp_congestion_control', 'cubic')}`",
        f"- **Contract SHA256**: `{metadata.get('contract_sha256')}`",
        "",
        "## 1. Primary & Secondary Metrics Summary",
        "",
        "| Arm | Valid Trials | Target Met (k/N) | Added Delay p99 Median (ms) | Added Delay p99 IQR (ms) | 95% Bootstrap CI (ms) | Added Delay CV | Bulk Goodput Median (Mbps) | Goodput Fraction | Call Loss Median (%) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for arm, s in arm_summaries.items():
        if s.get("n_valid", 0) == 0:
            lines.append(f"| {arm} | 0/{s.get('n_total', 0)} | 0/0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")
            continue
        p99 = s["primary_added_delay_p99_ms"]
        gp = s["secondary_bulk_goodput_mbps"]
        gpf = s["secondary_bulk_goodput_fraction"]
        loss = s["secondary_call_loss_pct"]
        ci_str = f"[{p99['bootstrap_ci95'][0]}, {p99['bootstrap_ci95'][1]}]"
        lines.append(
            f"| `{arm}` | {s['n_valid']}/{s['n_total']} | **{s['interactive_target_met']}** | {p99['median']:.2f} | {p99['iqr']:.2f} | {ci_str} | {p99['cv']:.3f} | {gp['median']:.2f} | {gpf['median']:.2%} | {loss['median']:.2f}% |"
        )

    lines.extend([
        "",
        "## 2. Safety Contract Adherence",
        "",
        "| Arm | Interactive Added Delay Target <= 30 ms | Bulk Floor >= 2.0 Mbps | Status |",
        "|---|---|---|---|",
    ])
    for arm, s in arm_summaries.items():
        if s.get("n_valid", 0) == 0:
            lines.append(f"| `{arm}` | N/A | N/A | INVALID |")
            continue
        med_delay = s["primary_added_delay_p99_ms"]["median"]
        med_gp = s["secondary_bulk_goodput_mbps"]["median"]
        delay_pass = med_delay <= 30.0
        gp_pass = med_gp >= 2.0
        overall = "COMPLIANT" if (delay_pass and gp_pass) else "NON-COMPLIANT"
        lines.append(f"| `{arm}` | {'PASS' if delay_pass else 'FAIL'} ({med_delay:.2f} ms) | {'PASS' if gp_pass else 'FAIL'} ({med_gp:.2f} Mbps) | **{overall}** |")

    content = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return content


def generate_figures(
    trial_records: List[Dict[str, Any]],
    arm_summaries: Dict[str, Dict[str, Any]],
    figures_dir: Path,
) -> None:
    """Generate M2 figures using matplotlib if available."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    figures_dir.mkdir(parents=True, exist_ok=True)

    # 1. Congested p99 added delay boxplot by arm
    plt.figure(figsize=(8, 5))
    arms = list(arm_summaries.keys())
    data_by_arm = []
    for arm in arms:
        delays = [t["congested_added_delay_p99_ms"] for t in trial_records if t["arm"] == arm and t.get("valid", True)]
        data_by_arm.append(delays if delays else [0.0])

    plt.boxplot(data_by_arm, tick_labels=arms)
    plt.axhline(30.0, color="r", linestyle="--", label="Contract Target (30 ms)")
    plt.axhline(80.0, color="orange", linestyle=":", label="Contract Guardrail (80 ms)")
    plt.title("Scenario A: Congested Added Delay (p99) by Arm")
    plt.ylabel("Added Delay (ms)")
    plt.xlabel("QoS Arm")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures_dir / "congested_p99_boxplot.png", dpi=150)
    plt.close()

    # 2. Bulk goodput by arm
    plt.figure(figsize=(8, 5))
    goodputs_by_arm = []
    for arm in arms:
        gps = [t["bulk_goodput_mbps"] for t in trial_records if t["arm"] == arm and t.get("valid", True)]
        goodputs_by_arm.append(gps if gps else [0.0])

    plt.boxplot(goodputs_by_arm, tick_labels=arms)
    plt.axhline(2.0, color="r", linestyle="--", label="Contract Bulk Floor (2.0 Mbps)")
    plt.title("Scenario A: Bulk Download Goodput by Arm")
    plt.ylabel("Goodput (Mbps)")
    plt.xlabel("QoS Arm")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures_dir / "bulk_goodput_comparison.png", dpi=150)
    plt.close()
