"""arms.py — M2 Home Router QoS Arms Configuration.

Implements the four M2 baseline QoS arms on the home router LAN egress interface
('ff_r_lan' in namespace 'ff_router'):

1. R0_no_qos:
   Unmanaged FIFO queue (pfifo limit 1000) with no rate shaping. All downstream
   queueing accumulates at the ISP bottleneck.
2. B1_static_htb:
   HTB root rate-shaped to 95 Mbps (0.95 * capacity). Fixed classes:
   - 1:10: Interactive (2 Mbps floor, ceil 95 Mbps, prio 1)
   - 1:20: Streaming (8 Mbps floor, ceil 95 Mbps, prio 2)
   - 1:30: Bulk / Default (2 Mbps floor, ceil 95 Mbps, prio 3)
   All leaf qdiscs: pfifo limit 1000.
   Classification: UDP dst port 5004 -> class 1:10 (interactive); default -> 1:30 (bulk).
3. B2a_fq_codel:
   HTB root rate-shaped to 95 Mbps with default fq_codel leaf (Linux defaults, no tuning).
4. B2b_cake:
   CAKE shaped to 95 Mbps with explicit default options (diffserv3, triple-isolate,
   nonat, nowash, no-ack-filter, split-gso, rtt 100ms, raw overhead 0, no tuning).

Safety Invariants:
- Only interfaces matching '^ff_[a-z0-9_]{1,12}$' are permitted.
- Only namespaces matching '^ff_[a-z0-9_]{1,12}$' are permitted.
- All commands execute with explicit argument arrays and shell=False.
"""

import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from src.fairflow.enforce import (
    validate_interface_name,
    validate_namespace_name,
    CommandRunner,
    SystemCommandRunner,
)


@dataclass(frozen=True)
class QoSConfig:
    """Configuration for router QoS arms."""

    interface: str = "ff_r_lan"
    namespace: str = "ff_router"
    shaping_rate_mbps: float = 95.0
    interactive_floor_mbps: float = 2.0
    streaming_floor_mbps: float = 8.0
    bulk_floor_mbps: float = 2.0
    call_port: int = 5004

    def __post_init__(self) -> None:
        validate_interface_name(self.interface)
        validate_namespace_name(self.namespace)
        if self.shaping_rate_mbps <= 0:
            raise ValueError(f"shaping_rate_mbps must be > 0, got {self.shaping_rate_mbps}")
        if self.interactive_floor_mbps <= 0:
            raise ValueError(f"interactive_floor_mbps must be > 0, got {self.interactive_floor_mbps}")
        if self.streaming_floor_mbps <= 0:
            raise ValueError(f"streaming_floor_mbps must be > 0, got {self.streaming_floor_mbps}")
        if self.bulk_floor_mbps <= 0:
            raise ValueError(f"bulk_floor_mbps must be > 0, got {self.bulk_floor_mbps}")
        if not (1 <= self.call_port <= 65535):
            raise ValueError(f"call_port must be in 1..65535, got {self.call_port}")


class ArmManager:
    """Builds and applies QoS configurations for the M2 experimental arms."""

    SUPPORTED_ARMS = ("R0_no_qos", "B1_static_htb", "B2a_fq_codel", "B2b_cake")

    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        dry_run: bool = False,
    ) -> None:
        self.runner: CommandRunner = runner or SystemCommandRunner()
        self.dry_run: bool = dry_run

    def build_commands(self, arm_name: str, config: QoSConfig) -> List[List[str]]:
        """Construct the exact tc commands list for the requested arm."""
        if arm_name not in self.SUPPORTED_ARMS:
            raise ValueError(f"Unsupported arm '{arm_name}'. Supported: {self.SUPPORTED_ARMS}")

        validate_interface_name(config.interface)
        validate_namespace_name(config.namespace)

        ns = config.namespace
        dev = config.interface

        # Formatting rates
        def _rate_str(mbps: float) -> str:
            return f"{int(mbps)}mbit" if mbps.is_integer() else f"{mbps}mbit"

        shaping_str = _rate_str(config.shaping_rate_mbps)
        interactive_str = _rate_str(config.interactive_floor_mbps)
        streaming_str = _rate_str(config.streaming_floor_mbps)
        bulk_str = _rate_str(config.bulk_floor_mbps)

        if arm_name == "R0_no_qos":
            return [
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "root", "pfifo", "limit", "1000"]
            ]

        elif arm_name == "B1_static_htb":
            return [
                # 1. Root HTB with default class 30 (bulk) and r2q 100
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "root", "handle", "1:", "htb", "default", "30", "r2q", "100"],
                # 2. Main rate shaping class (95 Mbps)
                ["ip", "netns", "exec", ns, "tc", "class", "replace", "dev", dev, "parent", "1:", "classid", "1:1", "htb", "rate", shaping_str, "ceil", shaping_str],
                # 3. Interactive class 1:10 (2 Mbps floor, ceil 95 Mbps, prio 1)
                ["ip", "netns", "exec", ns, "tc", "class", "replace", "dev", dev, "parent", "1:1", "classid", "1:10", "htb", "rate", interactive_str, "ceil", shaping_str, "prio", "1"],
                # 4. Streaming class 1:20 (8 Mbps floor, ceil 95 Mbps, prio 2)
                ["ip", "netns", "exec", ns, "tc", "class", "replace", "dev", dev, "parent", "1:1", "classid", "1:20", "htb", "rate", streaming_str, "ceil", shaping_str, "prio", "2"],
                # 5. Bulk class 1:30 (2 Mbps floor, ceil 95 Mbps, prio 3 - default)
                ["ip", "netns", "exec", ns, "tc", "class", "replace", "dev", dev, "parent", "1:1", "classid", "1:30", "htb", "rate", bulk_str, "ceil", shaping_str, "prio", "3"],
                # 6. Leaf pfifo qdiscs
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "parent", "1:10", "handle", "10:", "pfifo", "limit", "1000"],
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "parent", "1:20", "handle", "20:", "pfifo", "limit", "1000"],
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "parent", "1:30", "handle", "30:", "pfifo", "limit", "1000"],
                # 7. Classification filter: UDP dst port 5004 -> class 1:10 (interactive)
                ["ip", "netns", "exec", ns, "tc", "filter", "replace", "dev", dev, "parent", "1:", "protocol", "ip", "prio", "1", "u32", "match", "ip", "protocol", "17", "0xff", "match", "ip", "dport", str(config.call_port), "0xffff", "flowid", "1:10"],
            ]

        elif arm_name == "B2a_fq_codel":
            return [
                # 1. Root HTB with default class 1
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "root", "handle", "1:", "htb", "default", "1", "r2q", "100"],
                # 2. Shaped class (95 Mbps)
                ["ip", "netns", "exec", ns, "tc", "class", "replace", "dev", dev, "parent", "1:", "classid", "1:1", "htb", "rate", shaping_str, "ceil", shaping_str],
                # 3. fq_codel leaf
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "parent", "1:1", "handle", "10:", "fq_codel"],
            ]

        elif arm_name == "B2b_cake":
            return [
                ["ip", "netns", "exec", ns, "tc", "qdisc", "replace", "dev", dev, "root", "cake", "bandwidth", shaping_str, "diffserv3", "triple-isolate", "nonat", "nowash", "no-ack-filter", "split-gso", "rtt", "100ms", "raw", "overhead", "0"]
            ]

        raise ValueError(f"Unhandled arm: {arm_name}")

    def apply_arm(self, arm_name: str, config: QoSConfig) -> List[List[str]]:
        """Apply the specified QoS arm configuration."""
        cmds = self.build_commands(arm_name, config)
        if not self.dry_run:
            for cmd in cmds:
                self.runner.run(cmd, check=True)
        return cmds

    def teardown(self, config: QoSConfig) -> List[List[str]]:
        """Remove root qdisc from router interface."""
        validate_interface_name(config.interface)
        validate_namespace_name(config.namespace)
        cmd = ["ip", "netns", "exec", config.namespace, "tc", "qdisc", "del", "dev", config.interface, "root"]
        if not self.dry_run:
            self.runner.run(cmd, check=False)
        return [cmd]

    def snapshot_qdiscs(self, config: QoSConfig) -> List[Dict[str, Any]]:
        """Capture current qdiscs as JSON list via tc -j qdisc show."""
        validate_interface_name(config.interface)
        validate_namespace_name(config.namespace)
        cmd = ["ip", "netns", "exec", config.namespace, "tc", "-j", "qdisc", "show", "dev", config.interface]
        stdout, _, _ = self.runner.run(cmd, check=True)
        try:
            return json.loads(stdout)
        except Exception:
            return []

    def snapshot_classes_text(self, config: QoSConfig) -> str:
        """Capture current class statistics text via tc -s class show."""
        validate_interface_name(config.interface)
        validate_namespace_name(config.namespace)
        cmd = ["ip", "netns", "exec", config.namespace, "tc", "-s", "class", "show", "dev", config.interface]
        stdout, _, _ = self.runner.run(cmd, check=True)
        return stdout
