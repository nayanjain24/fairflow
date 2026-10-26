"""calibrate_bottleneck.py — M2 ISP Bottleneck Calibration and R0 Standing Delay Verification.

Executes:
1. BOTTLENECK-ONLY calibration (no QoS on router) with iperf3 -R at burst 4096B, 16kb, 64kb.
   - Pinned with taskset: iperf3 server on vCPU 3, iperf3 client on vCPU 4.
   - Offloads (GSO/GRO/TSO) disabled on all interfaces.
   - Upstream delay (ff_r_wan) configured: netem 15ms limit 100000.
   - Downstream bottleneck (ff_s_wan) configured: netem 15ms limit 100000 + tbf 100mbit burst <burst> limit 2500000.
   - Reports raw JSON and achieved goodput for each burst.
   - Selects the smallest burst achieving >= 93.5 Mbps.
2. R0 alone calibration:
   - ff_r_lan configured with pfifo limit 1000.
   - Simultaneous call (UDP 5004, 20ms, pinned to vCPU 1/2) + iperf3 download (-R, pinned to vCPU 3/4).
   - Reports maximum standing one-way delay vs expected ~215 ms.
3. Completely tears down the testbed when finished.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.fairflow.testbed import Testbed, ScenarioConfig
from src.fairflow.bottleneck import BottleneckConfig, BottleneckManager
from src.fairflow.offloads import disable_offloads, query_offload_status
from src.fairflow.traffic import UDPCallSender, UDPCallReceiver, PacketRecord


def run_cmd(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Execute command via subprocess with argument list and shell=False."""
    res = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if check and res.returncode != 0:
        raise RuntimeError(
            f"Command failed ({res.returncode}): {' '.join(cmd)}\nSTDERR: {res.stderr}"
        )
    return res


def setup_environment(config: ScenarioConfig) -> None:
    """Disable offloads on all interfaces in all namespaces."""
    for role, ns in config.namespaces.items():
        if role == "client":
            disable_offloads("ff_c_lan", ns)
        elif role == "router":
            disable_offloads("ff_r_lan", ns)
            disable_offloads("ff_r_wan", ns)
        elif role == "server":
            disable_offloads("ff_s_wan", ns)


def run_iperf_download(duration_s: int = 10) -> Dict[str, Any]:
    """Run iperf3 server in ff_server and client in ff_client (-R) with taskset pinning."""
    # 1. Start iperf3 server in ff_server (taskset -c 3)
    server_cmd = [
        "taskset", "-c", "3",
        "ip", "netns", "exec", "ff_server",
        "iperf3", "-s", "-p", "5201", "-1"
    ]
    srv_proc = subprocess.Popen(server_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.5)

    # 2. Run iperf3 client in ff_client (taskset -c 4)
    client_cmd = [
        "taskset", "-c", "4",
        "ip", "netns", "exec", "ff_client",
        "iperf3", "-c", "10.0.2.2", "-p", "5201",
        "-t", str(duration_s),
        "-i", "1",
        "-R",
        "-J",
    ]
    res = subprocess.run(client_cmd, capture_output=True, text=True, shell=False)
    srv_proc.wait(timeout=5)

    if res.returncode != 0:
        raise RuntimeError(f"iperf3 client failed ({res.returncode}): {res.stderr}")

    return json.loads(res.stdout)


def main() -> None:
    scenario_yaml = REPO_ROOT / "experiments" / "scenario_a.yaml"
    if not scenario_yaml.exists():
        print(f"Error: {scenario_yaml} not found", file=sys.stderr)
        sys.exit(1)

    print("======================================================================")
    print("M2 CALIBRATION: ISP BOTTLENECK & R0 STANDING DELAY")
    print("======================================================================")

    config = ScenarioConfig.from_yaml(str(scenario_yaml))
    testbed = Testbed(config)
    bm = BottleneckManager()

    # Clean existing namespaces if present
    testbed.down()
    print("Torn down any existing testbed.")

    print("Provisioning fresh testbed...")
    testbed.up()

    try:
        print("Disabling hardware offloads (GSO/GRO/TSO) on all ff_ interfaces...")
        setup_environment(config)
        for ns, iface in [
            ("ff_client", "ff_c_lan"),
            ("ff_router", "ff_r_lan"),
            ("ff_router", "ff_r_wan"),
            ("ff_server", "ff_s_wan"),
        ]:
            st = query_offload_status(iface, ns)
            print(f"  {ns}/{iface}: GSO={st.get('gso')} GRO={st.get('gro')} TSO={st.get('tso')}")

        # Install upstream delay on ff_r_wan (netem 15ms limit 100000)
        print("\nConfiguring upstream WAN delay on ff_r_wan (netem delay 15ms limit 100000)...")
        bm.apply_delay("ff_r_wan", "ff_router", delay_ms=15.0, limit_pkts=100000)

        # -------------------------------------------------------------------
        # PART 1: BOTTLENECK-ONLY BURST SWEEP
        # -------------------------------------------------------------------
        print("\n======================================================================")
        print("PART 1: BOTTLENECK-ONLY CALIBRATION (iperf3 -R at 4096B, 16kb, 64kb)")
        print("======================================================================")

        burst_candidates = ["4096b", "16kb", "64kb"]
        burst_results: Dict[str, float] = {}
        raw_json_results: Dict[str, Dict[str, Any]] = {}

        for burst in burst_candidates:
            print(f"\n--- Testing Burst: {burst} ---")
            b_cfg = BottleneckConfig(
                interface="ff_s_wan",
                namespace="ff_server",
                capacity_mbps=100.0,
                base_one_way_delay_ms=15.0,
                netem_limit_pkts=100000,
                bottleneck_buffer_ms=200.0,
                burst=burst,
            )
            bm.apply_bottleneck(b_cfg)

            # Confirm qdisc state
            res_q = run_cmd(["ip", "netns", "exec", "ff_server", "tc", "qdisc", "show", "dev", "ff_s_wan"])
            print("Current qdisc on ff_s_wan:\n", res_q.stdout.strip())

            print(f"Running 10s iperf3 -R (server -> client)...")
            data = run_iperf_download(duration_s=10)
            raw_json_results[burst] = data

            # Extract overall and steady-state goodput
            end = data.get("end", {})
            sum_received = end.get("sum_received", {})
            bps = sum_received.get("bits_per_second", 0.0)
            overall_mbps = bps / 1e6

            # Steady-state: intervals from second 3 onwards (omitting 3s ramp)
            intervals = data.get("intervals", [])
            steady_intervals = intervals[3:] if len(intervals) >= 4 else intervals
            steady_bytes = sum(i["sum"]["bytes"] for i in steady_intervals)
            steady_seconds = sum(i["sum"]["seconds"] for i in steady_intervals)
            steady_mbps = (steady_bytes * 8.0 / steady_seconds / 1e6) if steady_seconds > 0 else overall_mbps

            burst_results[burst] = steady_mbps
            print(f"Overall goodput (including ramp): {overall_mbps:.2f} Mbps")
            print(f"Steady-state goodput (omitting 3s ramp): {steady_mbps:.2f} Mbps")

            # Print interval breakdown
            int_mbps = [i["sum"]["bits_per_second"] / 1e6 for i in intervals]
            print(f"Per-second intervals (Mbps): {[round(x, 2) for x in int_mbps]}")

            # Print Raw iperf3 end JSON block
            print(f"\n--- RAW iperf3 JSON (end block) for burst {burst} ---")
            print(json.dumps(end, indent=2))

        print("\n======================================================================")
        print("BURST SWEEP SUMMARY:")
        for burst, mbps in burst_results.items():
            print(f"  Burst {burst:6s}: {mbps:6.2f} Mbps (Target >= 93.5 Mbps: {'PASS' if mbps >= 93.5 else 'FAIL'})")

        # Select smallest burst achieving >= 93.5 Mbps
        selected_burst = None
        for b in burst_candidates:
            if burst_results[b] >= 93.5:
                selected_burst = b
                break

        if not selected_burst:
            print("WARNING: No candidate achieved >= 93.5 Mbps! Picking maximum goodput candidate.")
            selected_burst = max(burst_results, key=burst_results.get)

        print(f"\nSelected burst: {selected_burst}")

        # -------------------------------------------------------------------
        # PART 2: R0 ALONE STANDING DELAY CALIBRATION
        # -------------------------------------------------------------------
        print("\n======================================================================")
        print("PART 2: R0 ALONE STANDING DELAY CALIBRATION")
        print("Expected theoretical standing one-way delay: ~215 ms (15ms netem + 200ms TBF buffer)")
        print("======================================================================")

        # 1. Apply selected bottleneck on ff_s_wan
        b_cfg = BottleneckConfig(
            interface="ff_s_wan",
            namespace="ff_server",
            capacity_mbps=100.0,
            base_one_way_delay_ms=15.0,
            netem_limit_pkts=100000,
            bottleneck_buffer_ms=200.0,
            burst=selected_burst,
        )
        bm.apply_bottleneck(b_cfg)

        # 2. Apply pfifo limit 1000 on ff_r_lan (R0 unmanaged queue)
        run_cmd([
            "ip", "netns", "exec", "ff_router",
            "tc", "qdisc", "replace", "dev", "ff_r_lan",
            "root", "pfifo", "limit", "1000"
        ])
        res_r0 = run_cmd(["ip", "netns", "exec", "ff_router", "tc", "qdisc", "show", "dev", "ff_r_lan"])
        print("Router ff_r_lan qdisc:\n", res_r0.stdout.strip())

        # 3. Setup Call Receiver and Sender
        # Timeline: 25s total call, download starts at +5s and runs for 15s (ends at +20s), tail +5s
        print("\nStarting simultaneous Call + Download...")
        receiver_cmd = [
            "taskset", "-c", "2",
            "ip", "netns", "exec", "ff_client",
            "python3", "-c",
            """
import sys, time
sys.path.insert(0, '/home/ubuntu/fairflow')
from src.fairflow.traffic import UDPCallReceiver
rx = UDPCallReceiver('10.0.1.2', 5004)
records = rx.run(duration_s=25.0, timeout_s=3.0)
rx.write_csv('/tmp/r0_calibration_call.csv')
print(f'Received {len(records)} call packets.')
"""
        ]
        rx_proc = subprocess.Popen(receiver_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.5)

        # Start call sender in ff_server (taskset -c 1)
        sender_cmd = [
            "taskset", "-c", "1",
            "ip", "netns", "exec", "ff_server",
            "python3", "-c",
            """
import sys, time
sys.path.insert(0, '/home/ubuntu/fairflow')
from src.fairflow.traffic import UDPCallSender
tx = UDPCallSender('10.0.1.2', 5004, interval_s=0.02, payload_len=160)
sent = tx.run(duration_s=25.0)
print(f'Transmitted {sent} call packets.')
"""
        ]
        tx_proc = subprocess.Popen(sender_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Let call run alone for 5s (baseline phase)
        time.sleep(5.0)

        # Start iperf3 download for 15 seconds
        iperf_t_start = time.monotonic()
        print(f"Starting 15s iperf3 download at monotonic t={iperf_t_start:.4f}...")
        iperf_data = run_iperf_download(duration_s=15)
        iperf_t_end = time.monotonic()
        print(f"Finished iperf3 download at monotonic t={iperf_t_end:.4f} (duration={iperf_t_end - iperf_t_start:.2f}s)")

        # Wait for sender and receiver
        tx_proc.wait(timeout=10)
        rx_proc.wait(timeout=10)

        # Parse CSV records
        from src.fairflow.traffic import parse_csv_records
        records = parse_csv_records("/tmp/r0_calibration_call.csv")
        print(f"\nTotal call records received: {len(records)}")

        # Calculate delays by phase
        # iperf steady-state: [iperf_t_start + 3.0s, iperf_t_end]
        congested_records: List[PacketRecord] = []
        baseline_records: List[PacketRecord] = []

        # Convert packet timestamps to seconds relative to first packet
        t0_ns = records[0].send_time_ns
        for r in records:
            rel_t = (r.send_time_ns - t0_ns) / 1e9
            # Baseline phase: 0.5s to 4.5s (excluding process launch warmup)
            if 0.5 <= rel_t < 4.5:
                baseline_records.append(r)
            # Congested steady-state phase: 8.0s to 19.0s (download active, excluding 3s ramp-up)
            elif 8.0 <= rel_t <= 19.0:
                congested_records.append(r)

        base_delays = [r.one_way_delay_ms for r in baseline_records]
        cong_delays = [r.one_way_delay_ms for r in congested_records]

        base_delays_sorted = sorted(base_delays)
        cong_delays_sorted = sorted(cong_delays)

        base_p50 = base_delays_sorted[int(0.50 * len(base_delays_sorted))]
        base_p99 = base_delays_sorted[int(0.99 * len(base_delays_sorted))]

        cong_p50 = cong_delays_sorted[int(0.50 * len(cong_delays_sorted))]
        cong_p95 = cong_delays_sorted[int(0.95 * len(cong_delays_sorted))]
        cong_p99 = cong_delays_sorted[int(0.99 * len(cong_delays_sorted))]
        cong_max = max(cong_delays)

        added_delay_p99 = cong_p99 - base_p99
        added_delay_max = cong_max - base_p50

        print("\nR0 Delay Analysis:")
        print(f"  Baseline packets ({len(baseline_records)}): p50 = {base_p50:.2f} ms, p99 = {base_p99:.2f} ms")
        print(f"  Congested steady-state packets ({len(congested_records)}):")
        print(f"    p50:  {cong_p50:.2f} ms")
        print(f"    p95:  {cong_p95:.2f} ms")
        print(f"    p99:  {cong_p99:.2f} ms")
        print(f"    Max:  {cong_max:.2f} ms")
        print(f"  Added delay p99: {added_delay_p99:.2f} ms")
        print(f"  Standing delay (Max): {cong_max:.2f} ms vs Expected ~215 ms (Difference: {cong_max - 215.0:+.2f} ms)")

        if added_delay_p99 < 50.0:
            print("CRITICAL STOP CONDITION TRIGGERED: R0 added delay < 50 ms!")
        else:
            print("R0 Bloat Verification: PASS (Clear rise in delay under download congestion)")

    finally:
        print("\nCleaning up testbed...")
        testbed.down()
        print("Testbed cleanly torn down.")


if __name__ == "__main__":
    main()
