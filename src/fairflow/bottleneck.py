"""bottleneck.py — ISP Bottleneck and Link Delay Emulation for FairFlow.

Emulates the ISP bottleneck and propagation delay on WAN veth interfaces:
1. Downstream ISP Bottleneck on ff_s_wan (ff_server namespace):
   - Root netem qdisc enforcing one-way base delay (e.g. 15 ms) with a high packet
     limit (100,000 pkts) so it never drops packets.
   - Child TBF (Token Bucket Filter) qdisc enforcing downstream link capacity
     (e.g. 100 Mbps) with a deliberately deep drop-tail buffer (e.g. 200 ms latency
     / 2.5 MB limit), modeling a typical unmanaged broadband modem buffer.
2. Upstream Link Delay on ff_r_wan (ff_router namespace):
   - Root netem qdisc enforcing one-way propagation delay (e.g. 15 ms) with a high
     packet limit (100,000 pkts) to yield an idle base RTT of 30 ms.

Safety Invariants:
- Only interfaces matching '^ff_[a-z0-9_]{1,12}$' are permitted.
- Only namespaces matching '^ff_[a-z0-9_]{1,12}$' are permitted.
- All subprocess commands are executed as explicit argument lists with shell=False.
"""

from dataclasses import dataclass
from typing import List, Optional
from src.fairflow.enforce import (
    validate_interface_name,
    validate_namespace_name,
    CommandRunner,
    SystemCommandRunner,
)


@dataclass(frozen=True)
class BottleneckConfig:
    """Configuration parameters for ISP bottleneck emulation."""

    interface: str
    namespace: str
    capacity_mbps: float = 100.0
    base_one_way_delay_ms: float = 15.0
    netem_limit_pkts: int = 100000
    bottleneck_buffer_ms: float = 200.0
    burst: str = "4096b"
    limit_bytes: Optional[int] = None

    def __post_init__(self) -> None:
        validate_interface_name(self.interface)
        validate_namespace_name(self.namespace)
        if self.capacity_mbps <= 0:
            raise ValueError(f"capacity_mbps must be > 0, got {self.capacity_mbps}")
        if self.base_one_way_delay_ms <= 0:
            raise ValueError(
                f"base_one_way_delay_ms must be > 0, got {self.base_one_way_delay_ms}"
            )
        if self.netem_limit_pkts <= 0:
            raise ValueError(f"netem_limit_pkts must be > 0, got {self.netem_limit_pkts}")
        if self.bottleneck_buffer_ms <= 0:
            raise ValueError(
                f"bottleneck_buffer_ms must be > 0, got {self.bottleneck_buffer_ms}"
            )
        if self.limit_bytes is not None and self.limit_bytes <= 0:
            raise ValueError(f"limit_bytes must be > 0, got {self.limit_bytes}")

    @property
    def calculated_limit_bytes(self) -> int:
        """Return explicit limit_bytes if set, else calculate from capacity and buffer_ms."""
        if self.limit_bytes is not None:
            return self.limit_bytes
        # bytes = (capacity_mbps * 1e6 bits/s / 8 bits/byte) * (buffer_ms / 1000 s)
        return int(self.capacity_mbps * 1e6 / 8.0 * (self.bottleneck_buffer_ms / 1000.0))


class BottleneckManager:
    """Manages the creation and removal of ISP bottleneck and delay qdiscs."""

    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        dry_run: bool = False,
    ) -> None:
        self.runner: CommandRunner = runner or SystemCommandRunner()
        self.dry_run: bool = dry_run

    def build_bottleneck_commands(self, config: BottleneckConfig) -> List[List[str]]:
        """Construct the tc commands to install netem root + TBF child on an interface."""
        validate_interface_name(config.interface)
        validate_namespace_name(config.namespace)

        # Rate formatting: use int if whole number (e.g. 100mbit)
        if config.capacity_mbps.is_integer():
            rate_str = f"{int(config.capacity_mbps)}mbit"
        else:
            rate_str = f"{config.capacity_mbps}mbit"

        # Delay formatting
        if config.base_one_way_delay_ms.is_integer():
            delay_str = f"{int(config.base_one_way_delay_ms)}ms"
        else:
            delay_str = f"{config.base_one_way_delay_ms}ms"

        limit_bytes = config.calculated_limit_bytes

        commands = [
            # 1. Root netem with delay and oversized packet limit (never drop)
            [
                "ip",
                "netns",
                "exec",
                config.namespace,
                "tc",
                "qdisc",
                "replace",
                "dev",
                config.interface,
                "root",
                "handle",
                "1:",
                "netem",
                "delay",
                delay_str,
                "limit",
                str(config.netem_limit_pkts),
            ],
            # 2. Child TBF with rate, burst, and 200ms drop-tail limit
            [
                "ip",
                "netns",
                "exec",
                config.namespace,
                "tc",
                "qdisc",
                "replace",
                "dev",
                config.interface,
                "parent",
                "1:",
                "handle",
                "2:",
                "tbf",
                "rate",
                rate_str,
                "burst",
                config.burst,
                "limit",
                str(limit_bytes),
            ],
        ]
        return commands

    def build_delay_commands(
        self,
        interface: str,
        namespace: str,
        delay_ms: float = 15.0,
        limit_pkts: int = 100000,
    ) -> List[List[str]]:
        """Construct the tc commands to install netem root delay on an interface."""
        validate_interface_name(interface)
        validate_namespace_name(namespace)
        if delay_ms <= 0:
            raise ValueError(f"delay_ms must be > 0, got {delay_ms}")
        if limit_pkts <= 0:
            raise ValueError(f"limit_pkts must be > 0, got {limit_pkts}")

        if delay_ms.is_integer():
            delay_str = f"{int(delay_ms)}ms"
        else:
            delay_str = f"{delay_ms}ms"

        return [
            [
                "ip",
                "netns",
                "exec",
                namespace,
                "tc",
                "qdisc",
                "replace",
                "dev",
                interface,
                "root",
                "handle",
                "1:",
                "netem",
                "delay",
                delay_str,
                "limit",
                str(limit_pkts),
            ]
        ]

    def build_teardown_commands(self, interface: str, namespace: str) -> List[List[str]]:
        """Construct the tc command to remove root qdiscs from an interface."""
        validate_interface_name(interface)
        validate_namespace_name(namespace)
        return [
            [
                "ip",
                "netns",
                "exec",
                namespace,
                "tc",
                "qdisc",
                "del",
                "dev",
                interface,
                "root",
            ]
        ]

    def apply_bottleneck(self, config: BottleneckConfig) -> List[List[str]]:
        """Apply ISP bottleneck qdiscs (netem root + TBF child) on the configured interface."""
        commands = self.build_bottleneck_commands(config)
        if not self.dry_run:
            for cmd in commands:
                self.runner.run(cmd, check=True)
        return commands

    def apply_delay(
        self,
        interface: str,
        namespace: str,
        delay_ms: float = 15.0,
        limit_pkts: int = 100000,
    ) -> List[List[str]]:
        """Apply one-way delay netem qdisc on the configured interface."""
        commands = self.build_delay_commands(
            interface, namespace, delay_ms=delay_ms, limit_pkts=limit_pkts
        )
        if not self.dry_run:
            for cmd in commands:
                self.runner.run(cmd, check=True)
        return commands

    def teardown(self, interface: str, namespace: str) -> List[List[str]]:
        """Tear down qdiscs on the specified interface (ignores failure if not present)."""
        commands = self.build_teardown_commands(interface, namespace)
        if not self.dry_run:
            for cmd in commands:
                self.runner.run(cmd, check=False)
        return commands
