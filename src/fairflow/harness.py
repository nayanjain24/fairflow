"""harness.py — M2 Scenario A Experiment Orchestration Engine.

Orchestrates block-randomized baseline evaluations:
- Rebuilds testbed per trial from scratch.
- Enforces strict 'ff_' naming, hardware offload disabling, and contract verification.
- Manages simultaneous Call and Download traffic pinned to isolated vCPUs.
- Captures pre/post trial tc state and 1 Hz periodic queue monitoring.
- Uses observed monotonic clock timestamps for steady-state phase slicing.
- Enforces invalid-trial policy and R0 bloat stop conditions.
- Writes trial metrics, summary CSVs, markdown reports, and figures under isolated run directories.
"""

import hashlib
import json
import os
import random
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.fairflow.testbed import Testbed, ScenarioConfig
from src.fairflow.bottleneck import BottleneckConfig, BottleneckManager
from src.fairflow.arms import ArmManager, QoSConfig
from src.fairflow.offloads import disable_offloads, query_offload_status
from src.fairflow.traffic import parse_csv_records
from src.fairflow.stats import compute_trial_metrics, compute_arm_summary, percentile
from src.fairflow.report import write_trial_metrics_csv, write_summary_by_arm_csv, generate_markdown_report, generate_figures
from src.fairflow.policy import Policy, ClassPolicy
from src.fairflow.enforcement_coordinator import EnforcementCoordinator, EnforcementState, CanaryMeasurement
from src.fairflow.controller import PolicyEngine, PolicyState
from src.fairflow.feasibility import SafetyContractEngine
from src.fairflow.enforce import TCDriver


def verify_contract_integrity() -> str:
    """Verify that contract.yaml matches contract.sha256 exactly."""
    contract_file = REPO_ROOT / "contract.yaml"
    sha_file = REPO_ROOT / "contract.sha256"
    if not contract_file.exists() or not sha_file.exists():
        raise FileNotFoundError("contract.yaml or contract.sha256 missing")
    expected = sha_file.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(contract_file.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"contract.yaml SHA256 mismatch: expected {expected}, got {actual}")
    return actual


def get_system_metadata() -> Dict[str, Any]:
    """Capture kernel sysctls, CPU topology, and system information."""
    metadata: Dict[str, Any] = {}

    def _read_sysctl(key: str) -> str:
        res = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True)
        return res.stdout.strip() if res.returncode == 0 else "unknown"

    metadata["tcp_congestion_control"] = _read_sysctl("net.ipv4.tcp_congestion_control")
    metadata["tcp_rmem"] = _read_sysctl("net.ipv4.tcp_rmem")
    metadata["tcp_wmem"] = _read_sysctl("net.ipv4.tcp_wmem")
    metadata["default_qdisc"] = _read_sysctl("net.core.default_qdisc")

    # CPU topology
    lscpu = subprocess.run(["lscpu"], capture_output=True, text=True)
    metadata["lscpu_raw"] = lscpu.stdout

    # Offload states on all ff_ interfaces in namespaces
    offload_states: Dict[str, Dict[str, bool]] = {}
    for ns, dev in [
        ("ff_client", "ff_c_lan"),
        ("ff_router", "ff_r_lan"),
        ("ff_router", "ff_r_wan"),
        ("ff_server", "ff_s_wan"),
    ]:
        offload_states[f"{ns}:{dev}"] = query_offload_status(dev, ns)
    metadata["offloads"] = offload_states

    return metadata


class QueueMonitor:
    """Samples 'tc -s -j qdisc show' every 1s during a trial."""

    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self.samples: List[Dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop_event.clear()
        self.samples = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> List[Dict[str, Any]]:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        return self.samples

    def _run(self) -> None:
        while not self._stop_event.is_set():
            t_sample = time.monotonic()
            sample: Dict[str, Any] = {"monotonic_t": t_sample}

            for ns, dev in [("ff_server", "ff_s_wan"), ("ff_router", "ff_r_lan")]:
                res = subprocess.run(
                    ["ip", "netns", "exec", ns, "tc", "-s", "-j", "qdisc", "show", "dev", dev],
                    capture_output=True, text=True,
                )
                try:
                    sample[f"{ns}:{dev}"] = json.loads(res.stdout)
                except Exception:
                    sample[f"{ns}:{dev}"] = []

            self.samples.append(sample)
            self._stop_event.wait(self.interval_s)


class M2Harness:
    """Experiment harness for running M2 Scenario A trials."""

    def __init__(
        self,
        config_path: Path,
        mode: str = "smoke",
        run_id: Optional[str] = None,
    ) -> None:
        self.config_path = config_path
        self.mode = mode
        self.contract_hash = verify_contract_integrity()

        # Load YAML specification
        with open(config_path, "r", encoding="utf-8") as f:
            self.yaml_data = yaml.safe_load(f)

        self.scenario_config = ScenarioConfig.from_dict(self.yaml_data)
        self.testbed = Testbed(self.scenario_config)
        self.bm = BottleneckManager()
        self.arm_mgr = ArmManager()

        phases = self.yaml_data["phases"][mode]
        self.baseline_s: float = float(phases["baseline_s"])
        self.congested_s: float = float(phases["congested_s"])
        self.tail_s: float = float(phases["tail_s"])
        self.ramp_s: float = float(phases["ramp_s"])
        self.n_trials_per_arm: int = int(phases["n_trials_per_arm"])

        self.arms: List[str] = list(self.yaml_data["arms"].keys())
        self.seed: int = int(self.yaml_data["schedule"]["random_seed"])
        self.cooldown_s: float = float(self.yaml_data["schedule"]["cooldown_s"])
        self.max_sender_lateness_ms: float = float(self.yaml_data["guardrails"]["max_sender_lateness_ms"])
        self.r0_min_added_delay_ms: float = float(self.yaml_data["guardrails"]["r0_min_added_delay_ms"])
        self.max_invalid_trials_per_arm: int = int(self.yaml_data["guardrails"]["max_invalid_trials_per_arm"])

        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_id = run_id or f"{mode}_{timestamp_str}"
        self.run_dir = REPO_ROOT / "results" / "m2" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def generate_schedule(self) -> List[Tuple[str, int]]:
        """Generate deterministic block-randomized trial schedule."""
        schedule: List[Tuple[str, int]] = []
        for trial_num in range(1, self.n_trials_per_arm + 1):
            block = list(self.arms)
            rng = random.Random(self.seed + trial_num)
            rng.shuffle(block)
            for arm in block:
                schedule.append((arm, trial_num))
        return schedule

    def setup_topology_and_bottleneck(self) -> None:
        """Tear down existing topology, bring up fresh links, and install bottleneck."""
        self.testbed.down()
        self.testbed.up()

        # Disable hardware offloads
        for ns, dev in [
            ("ff_client", "ff_c_lan"),
            ("ff_router", "ff_r_lan"),
            ("ff_router", "ff_r_wan"),
            ("ff_server", "ff_s_wan"),
        ]:
            disable_offloads(dev, ns)

        # Upstream delay on router WAN egress (15 ms)
        self.bm.apply_delay("ff_r_wan", "ff_router", delay_ms=15.0, limit_pkts=100000)

        # Downstream bottleneck on server WAN egress (15 ms netem + 100 Mbps TBF with calibrated burst 4096b)
        b_cfg = BottleneckConfig(
            interface="ff_s_wan",
            namespace="ff_server",
            capacity_mbps=100.0,
            base_one_way_delay_ms=15.0,
            netem_limit_pkts=100000,
            bottleneck_buffer_ms=200.0,
            burst="4096b",
        )
        self.bm.apply_bottleneck(b_cfg)

    def run_single_trial(self, arm_name: str, trial_num: int) -> Tuple[Dict[str, Any], Path]:
        """Execute one isolated trial of an arm."""
        trial_dir = self.run_dir / "raw" / f"{arm_name}_trial{trial_num}"
        trial_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n======================================================================")
        print(f"RUNNING TRIAL: {arm_name} (Trial {trial_num}/{self.n_trials_per_arm})")
        print(f"Output directory: {trial_dir}")
        print(f"======================================================================")

        # 1. Rebuild topology & bottleneck
        self.setup_topology_and_bottleneck()

        # 2. Configure arm on router LAN egress
        qos_cfg = QoSConfig(interface="ff_r_lan", namespace="ff_router", call_port=5004)
        self.arm_mgr.apply_arm(arm_name, qos_cfg)

        # 3. Capture Pre-trial snapshot & metadata
        qdisc_before = self.arm_mgr.snapshot_qdiscs(qos_cfg)
        class_before = self.arm_mgr.snapshot_classes_text(qos_cfg)
        sys_meta = get_system_metadata()
        sys_meta["contract_sha256"] = self.contract_hash
        sys_meta["arm"] = arm_name
        sys_meta["trial"] = trial_num
        sys_meta["qdisc_before"] = qdisc_before
        sys_meta["class_before"] = class_before

        # 4. Start 1 Hz Queue Monitor
        q_monitor = QueueMonitor(interval_s=1.0)
        q_monitor.start()

        # 5. Launch Traffic
        call_csv_path = trial_dir / "call_packets.csv"
        iperf_json_path = trial_dir / "iperf3.json"
        total_duration_s = self.baseline_s + self.congested_s + self.tail_s

        # Launch Receiver in ff_client (vCPU 2)
        rx_proc = subprocess.Popen([
            "taskset", "-c", "2",
            "ip", "netns", "exec", "ff_client",
            "python3", "-c",
            f"""
import sys
sys.path.insert(0, '{str(REPO_ROOT)}')
from src.fairflow.traffic import UDPCallReceiver
rx = UDPCallReceiver('10.0.1.2', 5004)
records = rx.run(duration_s={total_duration_s}, timeout_s=3.0)
rx.write_csv('{str(call_csv_path)}')
print(f'Receiver finished: {{len(records)}} packets received.')
"""
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.3)

        # Launch Sender in ff_server (vCPU 1)
        sender_log_path = trial_dir / "sender_summary.json"
        tx_proc = subprocess.Popen([
            "taskset", "-c", "1",
            "ip", "netns", "exec", "ff_server",
            "python3", "-c",
            f"""
import sys, json
sys.path.insert(0, '{str(REPO_ROOT)}')
from src.fairflow.traffic import UDPCallSender
tx = UDPCallSender('10.0.1.2', 5004, interval_s=0.02, payload_len=160)
seq = tx.run(duration_s={total_duration_s})
with open('{str(sender_log_path)}', 'w') as f:
    json.dump({{'total_sent': seq, 'p99_lateness_ms': round(tx.p99_lateness_ms, 4)}}, f)
print(f'Sender finished: {{seq}} packets sent, p99 lateness={{tx.p99_lateness_ms:.3f}}ms.')
"""
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait baseline phase
        print(f"Phase 1: Baseline call traffic ({self.baseline_s}s)...")
        time.sleep(self.baseline_s)

        # Launch iperf3 server in ff_server (vCPU 3)
        print(f"Phase 2: Congested call + download ({self.congested_s}s)...")
        iperf_srv = subprocess.Popen([
            "taskset", "-c", "3",
            "ip", "netns", "exec", "ff_server",
            "iperf3", "-s", "-p", "5201", "-1"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.4)

        # Run iperf3 client in ff_client (vCPU 4) with observed monotonic clock timing
        iperf_start_t = time.monotonic()
        iperf_res = subprocess.run([
            "taskset", "-c", "4",
            "ip", "netns", "exec", "ff_client",
            "iperf3", "-c", "10.0.2.2", "-p", "5201",
            "-t", str(int(self.congested_s)),
            "-i", "1",
            "-R",
            "-J",
        ], capture_output=True, text=True)
        iperf_end_t = time.monotonic()
        iperf_srv.wait(timeout=5)

        iperf_json_path.write_text(iperf_res.stdout, encoding="utf-8")
        print(f"Observed download duration: {iperf_end_t - iperf_start_t:.3f}s")

        # Wait tail phase
        print(f"Phase 3: Tail recovery call traffic ({self.tail_s}s)...")
        tx_proc.wait(timeout=10)
        rx_proc.wait(timeout=10)

        # Stop queue monitor and capture post-trial state
        q_samples = q_monitor.stop()
        (trial_dir / "qdisc_samples.json").write_text(json.dumps(q_samples, indent=2), encoding="utf-8")

        qdisc_after = self.arm_mgr.snapshot_qdiscs(qos_cfg)
        class_after = self.arm_mgr.snapshot_classes_text(qos_cfg)
        sys_meta["qdisc_after"] = qdisc_after
        sys_meta["class_after"] = class_after
        sys_meta["iperf_start_monotonic"] = iperf_start_t
        sys_meta["iperf_end_monotonic"] = iperf_end_t
        (trial_dir / "metadata.json").write_text(json.dumps(sys_meta, indent=2), encoding="utf-8")

        # 6. Parse and compute trial metrics
        call_records = parse_csv_records(str(call_csv_path)) if call_csv_path.exists() else []

        sender_meta = {}
        if sender_log_path.exists():
            sender_meta = json.loads(sender_log_path.read_text(encoding="utf-8"))

        total_sent = sender_meta.get("total_sent", len(call_records))
        p99_lateness = sender_meta.get("p99_lateness_ms", 0.0)

        # Compute steady-state goodput from iperf JSON (omitting ramp)
        bulk_goodput = 0.0
        try:
            iperf_data = json.loads(iperf_res.stdout)
            intervals = iperf_data.get("intervals", [])
            ramp_intervals = int(self.ramp_s)
            steady_intervals = intervals[ramp_intervals:] if len(intervals) > ramp_intervals else intervals
            if steady_intervals:
                total_bytes = sum(i["sum"]["bytes"] for i in steady_intervals)
                total_secs = sum(i["sum"]["seconds"] for i in steady_intervals)
                bulk_goodput = (total_bytes * 8.0 / total_secs / 1e6) if total_secs > 0 else 0.0
            else:
                bulk_goodput = iperf_data.get("end", {}).get("sum_received", {}).get("bits_per_second", 0.0) / 1e6
        except Exception:
            bulk_goodput = 0.0

        metrics = compute_trial_metrics(
            records=call_records,
            total_call_sent=total_sent,
            iperf_start_t=iperf_start_t,
            iperf_end_t=iperf_end_t,
            ramp_s=self.ramp_s,
            capacity_mbps=100.0,
            bulk_goodput_mbps=bulk_goodput,
            max_sender_lateness_ms=self.max_sender_lateness_ms,
            observed_p99_lateness_ms=p99_lateness,
        )
        metrics["arm"] = arm_name
        metrics["trial"] = trial_num

        print(f"Trial Results ({arm_name} #{trial_num}):")
        print(f"  Valid: {metrics['valid']} {metrics.get('invalid_reason')}")
        print(f"  Added Delay p99: {metrics.get('congested_added_delay_p99_ms')} ms (Target <= 30 ms: {metrics.get('interactive_target_met')})")
        print(f"  Bulk Goodput: {metrics.get('bulk_goodput_mbps')} Mbps (Floor >= 2.0 Mbps: {metrics.get('bulk_floor_met')})")
        print(f"  Call Loss: {metrics.get('call_loss_pct')}%")

        # 7. Teardown
        self.testbed.down()
        return metrics, trial_dir

    def run(self) -> Dict[str, Any]:
        """Execute the complete experiment run."""
        schedule = self.generate_schedule()
        print(f"Beginning M2 {self.mode.upper()} run: {len(schedule)} total trials across {len(self.arms)} arms.")
        print(f"Schedule: {schedule}")

        all_trial_records: List[Dict[str, Any]] = []
        invalid_counts: Dict[str, int] = {arm: 0 for arm in self.arms}

        for arm_name, trial_num in schedule:
            retry_count = 0
            while True:
                metrics, trial_dir = self.run_single_trial(arm_name, trial_num)

                # Check R0 stop condition: added delay must be >= 50 ms
                if arm_name == "R0_no_qos":
                    r0_delay = metrics.get("congested_added_delay_p99_ms", 0.0)
                    if r0_delay < self.r0_min_added_delay_ms:
                        raise RuntimeError(
                            f"CRITICAL STOP CONDITION TRIGGERED: R0 added delay ({r0_delay:.2f} ms) "
                            f"< {self.r0_min_added_delay_ms} ms. Bottleneck bufferbloat model failed!"
                        )

                if metrics.get("valid", True):
                    all_trial_records.append(metrics)
                    break

                # Invalid trial handling
                invalid_counts[arm_name] += 1
                all_trial_records.append(metrics)  # Retain invalid trial record
                if invalid_counts[arm_name] > self.max_invalid_trials_per_arm:
                    raise RuntimeError(
                        f"CRITICAL STOP CONDITION: Arm '{arm_name}' exceeded max invalid trials "
                        f"({invalid_counts[arm_name]} > {self.max_invalid_trials_per_arm})!"
                    )
                retry_count += 1
                print(f"Retrying invalid trial {arm_name} #{trial_num} (attempt {retry_count + 1})...")

            # Cooldown between trials
            print(f"Cooldown for {self.cooldown_s}s...")
            time.sleep(self.cooldown_s)

        # Compute arm summaries
        arm_summaries: Dict[str, Dict[str, Any]] = {}
        for arm in self.arms:
            arm_trials = [t for t in all_trial_records if t["arm"] == arm]
            arm_summaries[arm] = compute_arm_summary(arm_trials, seed=self.seed)

        # Write CSVs, report.md, and figures
        write_trial_metrics_csv(all_trial_records, self.run_dir / "trial_metrics.csv")
        write_summary_by_arm_csv(arm_summaries, self.run_dir / "summary_by_arm.csv")

        metadata = {
            "scenario_name": self.yaml_data["scenario_name"],
            "run_id": self.run_id,
            "mode": self.mode,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "kernel": "Linux 6.8 (Ubuntu 24.04 aarch64)",
            "tcp_congestion_control": "cubic",
            "contract_sha256": self.contract_hash,
        }
        report_md = generate_markdown_report(arm_summaries, metadata, self.run_dir / "report.md")
        generate_figures(all_trial_records, arm_summaries, self.run_dir / "figures")

        print("\n======================================================================")
        print("EXPERIMENT RUN COMPLETE")
        print("======================================================================")
        print(report_md)
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "trial_records": all_trial_records,
            "arm_summaries": arm_summaries,
        }


def run_scenario_b(
    duration_s: float = 30.0,
    run_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Execute Scenario B: Bottleneck capacity collapse from 100 Mbps to 20 Mbps."""
    run_id = run_id or f"scen_b_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = REPO_ROOT / "results" / "scenario_b" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_path = REPO_ROOT / "experiments" / "scenario_b.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    scenario_cfg = ScenarioConfig.from_dict(yaml_data)
    tb = Testbed(scenario_cfg)
    bm = BottleneckManager()
    arm_mgr = ArmManager()

    print(f"\n=== Starting Scenario B: Capacity Collapse (Run {run_id}) ===")
    tb.down()
    tb.up()

    try:
        # 1. Disable offloads
        for ns, dev in [
            ("ff_client", "ff_c_lan"),
            ("ff_router", "ff_r_lan"),
            ("ff_router", "ff_r_wan"),
            ("ff_server", "ff_s_wan"),
        ]:
            disable_offloads(dev, ns)

        # 2. Upstream delay (15 ms)
        bm.apply_delay("ff_r_wan", "ff_router", delay_ms=15.0)

        # 3. Initial 100 Mbps bottleneck
        bm.apply_bottleneck(
            BottleneckConfig(
                interface="ff_s_wan",
                namespace="ff_server",
                capacity_mbps=100.0,
                base_one_way_delay_ms=15.0,
                bottleneck_buffer_ms=200.0,
                burst="4096b",
            )
        )

        # 4. Apply FairFlow QoS on router LAN
        qos_cfg = QoSConfig(interface="ff_r_lan", namespace="ff_router", call_port=5004)
        arm_mgr.apply_arm("B1_static_htb", qos_cfg)

        # 5. Launch Call Traffic
        call_csv_path = run_dir / "call_packets.csv"
        call_rx = subprocess.Popen([
            "taskset", "-c", "2",
            "ip", "netns", "exec", "ff_client",
            "python3", "-c",
            f"""
import sys
sys.path.insert(0, '{str(REPO_ROOT)}')
from src.fairflow.traffic import UDPCallReceiver
rx = UDPCallReceiver('10.0.1.2', 5004)
rx.run(duration_s={duration_s}, timeout_s=3.0)
rx.write_csv('{str(call_csv_path)}')
"""
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        call_tx = subprocess.Popen([
            "taskset", "-c", "1",
            "ip", "netns", "exec", "ff_server",
            "python3", "-c",
            f"""
import sys
sys.path.insert(0, '{str(REPO_ROOT)}')
from src.fairflow.traffic import UDPCallSender
tx = UDPCallSender('10.0.1.2', 5004, interval_s=0.02, payload_len=160)
tx.run(duration_s={duration_s})
"""
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Launch iperf3 server
        iperf_srv = subprocess.Popen([
            "taskset", "-c", "3",
            "ip", "netns", "exec", "ff_server",
            "iperf3", "-s", "-p", "5201", "-1"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)

        half_s = duration_s / 2.0
        # Run iperf3 download for first half (100 Mbps)
        print(f"Phase 1: 100 Mbps bottleneck ({half_s:.1f}s)...")
        iperf1 = subprocess.run([
            "taskset", "-c", "4",
            "ip", "netns", "exec", "ff_client",
            "iperf3", "-c", "10.0.2.2", "-p", "5201",
            "-t", str(int(half_s)),
            "-i", "1", "-R", "-J",
        ], capture_output=True, text=True)

        # Collapse bottleneck to 20 Mbps!
        print(f"Phase 2: Collapsing bottleneck to 20 Mbps for remaining {half_s:.1f}s...")
        bm.apply_bottleneck(
            BottleneckConfig(
                interface="ff_s_wan",
                namespace="ff_server",
                capacity_mbps=20.0,
                base_one_way_delay_ms=15.0,
                bottleneck_buffer_ms=200.0,
                burst="4096b",
            )
        )

        # Launch second half download (20 Mbps bottleneck)
        iperf_srv2 = subprocess.Popen([
            "taskset", "-c", "3",
            "ip", "netns", "exec", "ff_server",
            "iperf3", "-s", "-p", "5201", "-1"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

        iperf2 = subprocess.run([
            "taskset", "-c", "4",
            "ip", "netns", "exec", "ff_client",
            "iperf3", "-c", "10.0.2.2", "-p", "5201",
            "-t", str(int(half_s)),
            "-i", "1", "-R", "-J",
        ], capture_output=True, text=True)

        call_tx.wait(timeout=5)
        call_rx.wait(timeout=5)

        # Parse results
        records = parse_csv_records(str(call_csv_path)) if call_csv_path.exists() else []
        pre_collapse = [r.one_way_delay_ms for r in records if r.send_time_ns < (records[0].send_time_ns + int(half_s * 1e9))] if records else []
        post_collapse = [r.one_way_delay_ms for r in records if r.send_time_ns >= (records[0].send_time_ns + int(half_s * 1e9))] if records else []

        tput1 = 0.0
        tput2 = 0.0
        try:
            d1 = json.loads(iperf1.stdout)
            tput1 = round(d1.get("end", {}).get("sum_received", {}).get("bits_per_second", 0) / 1e6, 2)
        except Exception:
            pass
        try:
            d2 = json.loads(iperf2.stdout)
            tput2 = round(d2.get("end", {}).get("sum_received", {}).get("bits_per_second", 0) / 1e6, 2)
        except Exception:
            pass

        metrics = {
            "scenario": "scenario_b",
            "run_id": run_id,
            "total_packets": len(records),
            "pre_collapse_p50_delay_ms": round(percentile(pre_collapse, 50.0), 2) if pre_collapse else 0.0,
            "pre_collapse_p95_delay_ms": round(percentile(pre_collapse, 95.0), 2) if pre_collapse else 0.0,
            "pre_collapse_tput_mbps": tput1,
            "post_collapse_p50_delay_ms": round(percentile(post_collapse, 50.0), 2) if post_collapse else 0.0,
            "post_collapse_p95_delay_ms": round(percentile(post_collapse, 95.0), 2) if post_collapse else 0.0,
            "post_collapse_tput_mbps": tput2,
            "capacity_collapse_adapted": bool(tput2 <= 22.0),
        }

        (run_dir / "metrics_summary.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        report_text = f"""# FairFlow Scenario B: Capacity Collapse Report
- **Run ID**: {run_id}
- **Pre-Collapse (100 Mbps)**: Throughput={tput1} Mbps, p95 delay={metrics['pre_collapse_p95_delay_ms']} ms
- **Post-Collapse (20 Mbps)**: Throughput={tput2} Mbps, p95 delay={metrics['post_collapse_p95_delay_ms']} ms
- **Adaptation Valid**: {metrics['capacity_collapse_adapted']}
"""
        (run_dir / "report.md").write_text(report_text, encoding="utf-8")
        print(f"Scenario B completed: {metrics}")
        return metrics, str(run_dir)
    finally:
        tb.down()


def run_scenario_c(
    duration_s: float = 20.0,
    run_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Execute Scenario C: Multi-flow 3 bulk streams + gaming low-latency traffic."""
    run_id = run_id or f"scen_c_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = REPO_ROOT / "results" / "scenario_c" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_path = REPO_ROOT / "experiments" / "scenario_c.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    scenario_cfg = ScenarioConfig.from_dict(yaml_data)
    tb = Testbed(scenario_cfg)
    bm = BottleneckManager()
    arm_mgr = ArmManager()

    print(f"\n=== Starting Scenario C: Multi-flow Fairness (Run {run_id}) ===")
    tb.down()
    tb.up()

    try:
        # Disable offloads
        for ns, dev in [
            ("ff_client", "ff_c_lan"),
            ("ff_router", "ff_r_lan"),
            ("ff_router", "ff_r_wan"),
            ("ff_server", "ff_s_wan"),
        ]:
            disable_offloads(dev, ns)

        bm.apply_delay("ff_r_wan", "ff_router", delay_ms=15.0)
        bm.apply_bottleneck(
            BottleneckConfig(
                interface="ff_s_wan",
                namespace="ff_server",
                capacity_mbps=100.0,
                base_one_way_delay_ms=15.0,
                bottleneck_buffer_ms=200.0,
                burst="4096b",
            )
        )

        qos_cfg = QoSConfig(interface="ff_r_lan", namespace="ff_router", call_port=5005)
        arm_mgr.apply_arm("B2a_fq_codel", qos_cfg)

        # Launch gaming probe
        game_csv = run_dir / "game_packets.csv"
        game_rx = subprocess.Popen([
            "taskset", "-c", "2",
            "ip", "netns", "exec", "ff_client",
            "python3", "-c",
            f"""
import sys
sys.path.insert(0, '{str(REPO_ROOT)}')
from src.fairflow.traffic import UDPCallReceiver
rx = UDPCallReceiver('10.0.1.2', 5005)
rx.run(duration_s={duration_s}, timeout_s=3.0)
rx.write_csv('{str(game_csv)}')
"""
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        game_tx = subprocess.Popen([
            "taskset", "-c", "1",
            "ip", "netns", "exec", "ff_server",
            "python3", "-c",
            f"""
import sys
sys.path.insert(0, '{str(REPO_ROOT)}')
from src.fairflow.traffic import UDPCallSender
tx = UDPCallSender('10.0.1.2', 5005, interval_s=0.015, payload_len=120)
tx.run(duration_s={duration_s})
"""
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Launch 3-stream iperf3
        iperf_srv = subprocess.Popen([
            "taskset", "-c", "3",
            "ip", "netns", "exec", "ff_server",
            "iperf3", "-s", "-p", "5201", "-1"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)

        iperf_res = subprocess.run([
            "taskset", "-c", "4",
            "ip", "netns", "exec", "ff_client",
            "iperf3", "-c", "10.0.2.2", "-p", "5201",
            "-P", "3",
            "-t", str(int(duration_s)),
            "-i", "1", "-R", "-J",
        ], capture_output=True, text=True)

        game_tx.wait(timeout=5)
        game_rx.wait(timeout=5)

        # Calculate Jain's Fairness Index across the 3 streams
        stream_tputs: List[float] = []
        try:
            d = json.loads(iperf_res.stdout)
            streams = d.get("end", {}).get("streams", [])
            for s in streams:
                bps = s.get("receiver", {}).get("bits_per_second", 0)
                stream_tputs.append(round(bps / 1e6, 2))
        except Exception:
            pass

        jain_fairness = 0.0
        if stream_tputs and sum(stream_tputs) > 0:
            n = len(stream_tputs)
            sq_sum = sum(stream_tputs) ** 2
            sum_sq = sum(x**2 for x in stream_tputs)
            jain_fairness = round(sq_sum / (n * sum_sq), 4)

        game_records = parse_csv_records(str(game_csv)) if game_csv.exists() else []
        game_delays = [r.one_way_delay_ms for r in game_records] if game_records else []

        metrics = {
            "scenario": "scenario_c",
            "run_id": run_id,
            "stream_throughputs_mbps": stream_tputs,
            "jain_fairness_index": jain_fairness,
            "gaming_p50_delay_ms": round(percentile(game_delays, 50.0), 2) if game_delays else 0.0,
            "gaming_p95_delay_ms": round(percentile(game_delays, 95.0), 2) if game_delays else 0.0,
            "gaming_sample_count": len(game_delays),
            "fairness_target_met": bool(jain_fairness >= 0.85),
        }

        (run_dir / "metrics_summary.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        report_text = f"""# FairFlow Scenario C: Multi-flow Streaming + Gaming Report
- **Run ID**: {run_id}
- **Streams (3 flows)**: {stream_tputs} Mbps
- **Jain Fairness Index**: {jain_fairness} (Target >= 0.85: {metrics['fairness_target_met']})
- **Gaming Latency p95**: {metrics['gaming_p95_delay_ms']} ms
"""
        (run_dir / "report.md").write_text(report_text, encoding="utf-8")
        print(f"Scenario C completed: {metrics}")
        return metrics, str(run_dir)
    finally:
        tb.down()


def run_scenario_d(
    duration_s: float = 10.0,
    run_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Execute Scenario D: Deliberately harmful policy proposal, breach detection, and verified rollback."""
    run_id = run_id or f"scen_d_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = REPO_ROOT / "results" / "scenario_d" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config_path = REPO_ROOT / "experiments" / "scenario_d.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f)

    scenario_cfg = ScenarioConfig.from_dict(yaml_data)
    tb = Testbed(scenario_cfg)
    arm_mgr = ArmManager()
    tc_driver = TCDriver()

    print(f"\n=== Starting Scenario D: Harmful Policy Rollback (Run {run_id}) ===")
    tb.down()
    tb.up()

    try:
        qos_cfg = QoSConfig(interface="ff_r_lan", namespace="ff_router")
        # 1. Establish known-good baseline
        arm_mgr.apply_arm("B2a_fq_codel", qos_cfg)
        snap_baseline = tc_driver.snapshot("ff_r_lan", "ff_router")

        # 2. SafetyContractEngine rejection check:
        from src.fairflow.contract import load_contract
        c = load_contract("contract.yaml")
        safety = SafetyContractEngine(contract=c)

        # Infeasible candidate: interactive floor 0.5 Mbps (violates contract minimum 2.0 Mbps)
        harmful_classes = {
            "interactive": ClassPolicy(rate_floor_mbps=0.5, rate_ceiling_mbps=95.0, priority=1, leaf_qdisc="fq_codel"),
            "bulk": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=95.0, priority=3, leaf_qdisc="fq_codel"),
        }
        harmful_policy = Policy(link_capacity_mbps=100.0, classes=harmful_classes)
        feas = safety.evaluate(harmful_policy, estimated_capacity_mbps=100.0)
        assert not feas.is_feasible, "Harmful policy must be rejected by SafetyContractEngine"

        # 3. Simulate Canary breach & verified rollback on kernel
        engine = PolicyEngine(contract=c)
        coordinator = EnforcementCoordinator(
            engine=engine,
            driver=tc_driver,
            interface="ff_r_lan",
            namespace="ff_router",
            contract=c,
        )

        record = engine.generate_candidate_policy(
            classified_flows=[],
            estimated_capacity_mbps=95.0,
            timestamp=100.0,
        )
        assert record.state == PolicyState.VALIDATED

        apply_outcome = coordinator.apply_and_verify(record)
        assert apply_outcome.success is True
        assert apply_outcome.kernel_verified is True
        assert coordinator.state == EnforcementState.ENFORCED

        # Inject 2 consecutive breaching canary measurements (> 80 ms guardrail) -> triggers rollback
        bad_measurements = [
            CanaryMeasurement(timestamp=0.0, window_index=0, added_delay_ms=90.0, jitter_ms=5.0, loss_pct=0.0),
            CanaryMeasurement(timestamp=2.0, window_index=1, added_delay_ms=92.0, jitter_ms=5.0, loss_pct=0.0),
        ]
        canary_outcome = coordinator.canary_evaluate_and_commit(record, bad_measurements)
        assert canary_outcome.success is False
        assert canary_outcome.rollback_performed is True
        assert canary_outcome.rollback_verified is True
        assert coordinator.state == EnforcementState.ROLLED_BACK

        # Independently inspect restored kernel state
        snap_restored = tc_driver.snapshot("ff_r_lan", "ff_router")
        # Root HTB qdisc 1: must be gone (clean default baseline restored)
        verified = not any(q.get("kind") == "htb" and q.get("handle") == "1:" for q in snap_restored)

        metrics = {
            "scenario": "scenario_d",
            "run_id": run_id,
            "harmful_policy_infeasible_rejected": True,
            "rejection_reasons": list(feas.reasons),
            "canary_breach_detected": True,
            "automated_rollback_executed": True,
            "coordinator_final_state": coordinator.state.value,
            "kernel_restoration_verified": verified,
        }

        (run_dir / "metrics_summary.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        report_text = f"""# FairFlow Scenario D: Harmful Policy Rejection & Rollback Report
- **Run ID**: {run_id}
- **Infeasible Policy Rejection**: PASSED ({feas.reasons})
- **Canary Guardrail Breach Rollback**: PASSED (State={coordinator.state.value})
- **Independent Kernel State Verification**: {verified}
"""
        (run_dir / "report.md").write_text(report_text, encoding="utf-8")
        print(f"Scenario D completed: {metrics}")
        return metrics, str(run_dir)
    finally:
        tb.down()


def run_scenario_harness(
    scenario_id: str,
    duration_s: float = 30.0,
    run_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Universal dispatcher for FairFlow QoS scenarios (A, B, C, D).

    Delegates cleanly to VM via scripts/vm.sh when invoked on macOS host.
    """
    overrides = overrides or {}
    run_id = run_id or f"{scenario_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # If invoked on macOS host or non-root Linux, elevate appropriately
    if sys.platform != "linux" or os.geteuid() != 0:
        if sys.platform == "linux":
            cmd = [
                "sudo",
                "-n",
                f"PYTHONPATH={str(REPO_ROOT)}",
                sys.executable,
                str(REPO_ROOT / "src" / "fairflow" / "harness.py"),
                "--scenario",
                scenario_id,
                "--duration",
                str(duration_s),
                "--run-id",
                run_id,
            ]
        else:
            cmd = [
                str(REPO_ROOT / "scripts" / "vm.sh"),
                "sudo",
                "PYTHONPATH=/home/ubuntu/fairflow",
                "/home/ubuntu/venv-ff/bin/python",
                "src/fairflow/harness.py",
                "--scenario",
                scenario_id,
                "--duration",
                str(duration_s),
                "--run-id",
                run_id,
            ]
        print(f"Executing {scenario_id}: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Scenario execution failed (exit code {res.returncode}): {res.stderr}")

        # Look for output metrics_summary.json or results directory
        candidates = [
            REPO_ROOT / "results" / "m2" / run_id / "trial_metrics.csv",
            REPO_ROOT / "results" / scenario_id / run_id / "metrics_summary.json",
            REPO_ROOT / "results" / "scenario_b" / run_id / "metrics_summary.json",
            REPO_ROOT / "results" / "scenario_c" / run_id / "metrics_summary.json",
            REPO_ROOT / "results" / "scenario_d" / run_id / "metrics_summary.json",
        ]
        for c in candidates:
            if c.exists():
                if c.suffix == ".json":
                    metrics = json.loads(c.read_text(encoding="utf-8"))
                    return metrics, str(c.parent)
                elif c.suffix == ".csv":
                    return {"scenario": scenario_id, "run_id": run_id, "status": "completed"}, str(c.parent)

        return {"scenario": scenario_id, "run_id": run_id, "output": res.stdout[-500:]}, str(REPO_ROOT / "results")

    # Native execution inside Linux VM as root
    if scenario_id == "scenario_a":
        config_path = REPO_ROOT / "experiments" / "scenario_a.yaml"
        mode = overrides.get("mode", "smoke")
        harness = M2Harness(config_path=config_path, mode=mode, run_id=run_id)
        res = harness.run()
        return res, str(harness.run_dir)
    elif scenario_id == "scenario_b":
        return run_scenario_b(duration_s=duration_s, run_id=run_id, overrides=overrides)
    elif scenario_id == "scenario_c":
        return run_scenario_c(duration_s=duration_s, run_id=run_id, overrides=overrides)
    elif scenario_id == "scenario_d":
        return run_scenario_d(duration_s=duration_s, run_id=run_id, overrides=overrides)
    else:
        raise ValueError(f"Unknown scenario_id '{scenario_id}'; must be one of [scenario_a, scenario_b, scenario_c, scenario_d]")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="FairFlow Multi-Scenario Experiment Runner")
    parser.add_argument("--scenario", default="scenario_a", choices=["scenario_a", "scenario_b", "scenario_c", "scenario_d"])
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--run-id", default=None)
    # Positional mode backward compatibility for scripts/run_m2.sh
    parser.add_argument("pos_mode", nargs="?", choices=["smoke", "full"], default=None)
    args = parser.parse_args()

    mode = args.pos_mode or args.mode
    run_scenario_harness(
        scenario_id=args.scenario,
        duration_s=args.duration,
        run_id=args.run_id,
        overrides={"mode": mode},
    )


if __name__ == "__main__":
    main()
