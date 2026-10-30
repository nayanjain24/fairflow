"""Root integration tests for M2 QoS arms, classification, and safety invariants.

These tests run inside the Linux VM as root and require network namespaces,
virtual ethernet pairs, and traffic control kernel modules.
"""

import os
import re
import subprocess
import time
from pathlib import Path
import pytest

from src.fairflow.testbed import Testbed, ScenarioConfig
from src.fairflow.arms import ArmManager, QoSConfig
from src.fairflow.bottleneck import BottleneckManager, BottleneckConfig
from src.fairflow.offloads import disable_offloads
from src.fairflow.traffic import UDPCallSender, UDPCallReceiver
from src.fairflow.contract import load_contract, ContractError

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_integration_all_four_arms_apply_and_snapshot(tmp_path: Path) -> None:
    """Verify that all 4 arms apply cleanly on real veth interfaces and preserve snapshots."""
    cfg = ScenarioConfig.from_yaml(str(REPO_ROOT / "experiments" / "scenario_a.yaml"))
    tb = Testbed(cfg)
    tb.down()
    tb.up()

    arm_mgr = ArmManager()
    qos_cfg = QoSConfig(interface="ff_r_lan", namespace="ff_router")

    try:
        for arm_name in ["R0_no_qos", "B1_static_htb", "B2a_fq_codel", "B2b_cake"]:
            # Capture before snapshot
            snap_before = arm_mgr.snapshot_qdiscs(qos_cfg)

            # Apply arm
            arm_mgr.apply_arm(arm_name, qos_cfg)

            # Capture after snapshot
            snap_after = arm_mgr.snapshot_qdiscs(qos_cfg)
            assert len(snap_after) > 0, f"Expected active qdiscs for {arm_name}"

            # Verify kind
            kinds = [q.get("kind") for q in snap_after]
            if arm_name == "R0_no_qos":
                assert "pfifo" in kinds
            elif arm_name == "B1_static_htb":
                assert "htb" in kinds
            elif arm_name == "B2a_fq_codel":
                assert "htb" in kinds
            elif arm_name == "B2b_cake":
                assert "cake" in kinds

            # Cleanup
            arm_mgr.teardown(qos_cfg)
    finally:
        tb.down()


def test_integration_b1_traffic_classification_counters() -> None:
    """Verify that B1 classifies UDP dst port 5004 into class 1:10 and TCP bulk into class 1:30."""
    cfg = ScenarioConfig.from_yaml(str(REPO_ROOT / "experiments" / "scenario_a.yaml"))
    tb = Testbed(cfg)
    tb.down()
    tb.up()

    arm_mgr = ArmManager()
    qos_cfg = QoSConfig(interface="ff_r_lan", namespace="ff_router", call_port=5004)

    try:
        # Disable offloads
        for ns, iface in [("ff_client", "ff_c_lan"), ("ff_router", "ff_r_lan"), ("ff_router", "ff_r_wan"), ("ff_server", "ff_s_wan")]:
            disable_offloads(iface, ns)

        # Apply B1 on router LAN egress
        arm_mgr.apply_arm("B1_static_htb", qos_cfg)

        # 1. Start Call traffic (UDP 5004, 30 packets from server to client)
        rx = UDPCallReceiver("10.0.1.2", 5004)
        tx = UDPCallSender("10.0.1.2", 5004, interval_s=0.02, payload_len=160)

        import threading
        rx_records = []
        def _rx():
            nonlocal rx_records
            # Execute in client namespace
            rx_proc = subprocess.run([
                "ip", "netns", "exec", "ff_client",
                "python3", "-c",
                "import sys; sys.path.insert(0, '/home/ubuntu/fairflow'); from src.fairflow.traffic import UDPCallReceiver; r = UDPCallReceiver('10.0.1.2', 5004); r.run(duration_s=1.0, timeout_s=1.0)"
            ], capture_output=True, text=True)

        t_rx = threading.Thread(target=_rx)
        t_rx.start()
        time.sleep(0.2)

        # Send call packets from server namespace
        subprocess.run([
            "ip", "netns", "exec", "ff_server",
            "python3", "-c",
            "import sys; sys.path.insert(0, '/home/ubuntu/fairflow'); from src.fairflow.traffic import UDPCallSender; s = UDPCallSender('10.0.1.2', 5004, interval_s=0.02, payload_len=160); s.run(duration_s=0.8)"
        ], check=True)
        t_rx.join(timeout=3.0)

        # 2. Run short iperf3 download (TCP bulk traffic)
        srv_proc = subprocess.Popen([
            "ip", "netns", "exec", "ff_server",
            "iperf3", "-s", "-p", "5201", "-1"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

        subprocess.run([
            "ip", "netns", "exec", "ff_client",
            "iperf3", "-c", "10.0.2.2", "-p", "5201", "-t", "2", "-R"
        ], capture_output=True, text=True, check=True)
        srv_proc.wait(timeout=5)

        # 3. Inspect tc class counters on router
        class_stats = arm_mgr.snapshot_classes_text(qos_cfg)

        # Parse packets sent in class 1:10 and class 1:30
        # Format:
        # class htb 1:10 parent 1:1 ...
        #  Sent <bytes> bytes <pkts> pkt ...
        c10_match = re.search(r"class htb 1:10[\s\S]*?Sent \d+ bytes (\d+) pkt", class_stats)
        c30_match = re.search(r"class htb 1:30[\s\S]*?Sent \d+ bytes (\d+) pkt", class_stats)

        assert c10_match is not None, "Class 1:10 not found in tc stats"
        assert c30_match is not None, "Class 1:30 not found in tc stats"

        c10_pkts = int(c10_match.group(1))
        c30_pkts = int(c30_match.group(1))

        assert c10_pkts > 0, f"Expected interactive call packets in class 1:10, got {c10_pkts}"
        assert c30_pkts > 0, f"Expected bulk iperf3 packets in class 1:30, got {c30_pkts}"

    finally:
        tb.down()


def test_integration_safety_invariants_and_contract_hash() -> None:
    """Verify contract hash check and interface whitelist rejection."""
    # 1. Contract SHA256 integrity
    import hashlib
    sha_file = REPO_ROOT / "contract.sha256"
    contract_file = REPO_ROOT / "contract.yaml"
    expected = sha_file.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(contract_file.read_bytes()).hexdigest()
    assert actual == expected

    # 2. Interface whitelist rejection in ArmManager
    arm_mgr = ArmManager()
    with pytest.raises(ValueError, match="Interface name must match pattern"):
        arm_mgr.build_commands("R0_no_qos", QoSConfig(interface="eth0"))

    with pytest.raises(ValueError, match="Interface name must match pattern"):
        arm_mgr.build_commands("R0_no_qos", QoSConfig(interface="lo"))
