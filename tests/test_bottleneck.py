"""Unit tests for src/fairflow/bottleneck.py.

All tests run locally as a normal user without root privileges using mocked CommandRunner.
Verifies command generation, argument validation, and strict 'ff_' naming invariants.
"""

from typing import List, Tuple
import pytest
from src.fairflow.bottleneck import BottleneckConfig, BottleneckManager


class MockRunner:
    """Mock CommandRunner recording executed commands."""

    def __init__(self, return_code: int = 0) -> None:
        self.executed: List[Tuple[List[str], bool]] = []
        self.return_code: int = return_code

    def run(self, cmd: List[str], check: bool = True) -> Tuple[str, str, int]:
        self.executed.append((cmd, check))
        return ("", "", self.return_code)


def test_bottleneck_config_validation_success() -> None:
    """Valid parameters create BottleneckConfig without error."""
    cfg = BottleneckConfig(
        interface="ff_s_wan",
        namespace="ff_server",
        capacity_mbps=100.0,
        base_one_way_delay_ms=15.0,
        netem_limit_pkts=100000,
        bottleneck_buffer_ms=200.0,
        burst="4096b",
    )
    assert cfg.interface == "ff_s_wan"
    assert cfg.namespace == "ff_server"
    assert cfg.calculated_limit_bytes == 2500000


@pytest.mark.parametrize("bad_interface", ["eth0", "wlan0", "veth0", "ff_", "ff_toolongnamehere"])
def test_bottleneck_config_rejects_invalid_interface(bad_interface: str) -> None:
    """Interfaces that do not match '^ff_[a-z0-9_]{1,12}$' are strictly rejected."""
    with pytest.raises(ValueError, match="Interface name must match pattern"):
        BottleneckConfig(
            interface=bad_interface,
            namespace="ff_server",
        )


@pytest.mark.parametrize("bad_namespace", ["default", "ns1", "ff_", "ff_toolongnamesp"])
def test_bottleneck_config_rejects_invalid_namespace(bad_namespace: str) -> None:
    """Namespaces that do not match '^ff_[a-z0-9_]{1,12}$' are strictly rejected."""
    with pytest.raises(ValueError, match="Namespace name must match pattern"):
        BottleneckConfig(
            interface="ff_s_wan",
            namespace=bad_namespace,
        )


@pytest.mark.parametrize("param,value", [
    ("capacity_mbps", 0.0),
    ("capacity_mbps", -10.0),
    ("base_one_way_delay_ms", 0.0),
    ("base_one_way_delay_ms", -5.0),
    ("netem_limit_pkts", 0),
    ("netem_limit_pkts", -100),
    ("bottleneck_buffer_ms", 0.0),
    ("bottleneck_buffer_ms", -50.0),
    ("limit_bytes", 0),
    ("limit_bytes", -1000),
])
def test_bottleneck_config_rejects_non_positive_numbers(param: str, value: object) -> None:
    """All numerical capacity, delay, and buffer values must be strictly positive."""
    kwargs = {
        "interface": "ff_s_wan",
        "namespace": "ff_server",
        param: value,
    }
    with pytest.raises(ValueError, match="must be > 0"):
        BottleneckConfig(**kwargs)


def test_calculated_limit_bytes_math() -> None:
    """Test buffer size calculation: capacity * buffer_ms / 8."""
    # 100 Mbps * 200 ms / 8 = 2.5 MB
    cfg100 = BottleneckConfig(
        interface="ff_s_wan",
        namespace="ff_server",
        capacity_mbps=100.0,
        bottleneck_buffer_ms=200.0,
    )
    assert cfg100.calculated_limit_bytes == 2500000

    # 20 Mbps * 200 ms / 8 = 500 KB
    cfg20 = BottleneckConfig(
        interface="ff_s_wan",
        namespace="ff_server",
        capacity_mbps=20.0,
        bottleneck_buffer_ms=200.0,
    )
    assert cfg20.calculated_limit_bytes == 500000

    # Explicit override takes precedence
    cfg_override = BottleneckConfig(
        interface="ff_s_wan",
        namespace="ff_server",
        capacity_mbps=100.0,
        bottleneck_buffer_ms=200.0,
        limit_bytes=1234567,
    )
    assert cfg_override.calculated_limit_bytes == 1234567


def test_build_bottleneck_commands_structure() -> None:
    """Verifies that netem root + TBF child commands are correctly formatted."""
    cfg = BottleneckConfig(
        interface="ff_s_wan",
        namespace="ff_server",
        capacity_mbps=100.0,
        base_one_way_delay_ms=15.0,
        netem_limit_pkts=100000,
        bottleneck_buffer_ms=200.0,
        burst="4096b",
    )
    mgr = BottleneckManager()
    cmds = mgr.build_bottleneck_commands(cfg)

    assert len(cmds) == 2
    # Command 1: Root netem
    assert cmds[0] == [
        "ip", "netns", "exec", "ff_server",
        "tc", "qdisc", "replace", "dev", "ff_s_wan",
        "root", "handle", "1:",
        "netem", "delay", "15ms", "limit", "100000",
    ]
    # Command 2: Child TBF
    assert cmds[1] == [
        "ip", "netns", "exec", "ff_server",
        "tc", "qdisc", "replace", "dev", "ff_s_wan",
        "parent", "1:", "handle", "2:",
        "tbf", "rate", "100mbit", "burst", "4096b", "limit", "2500000",
    ]


def test_build_delay_commands_structure() -> None:
    """Verifies delay command generation for ff_r_wan upstream delay."""
    mgr = BottleneckManager()
    cmds = mgr.build_delay_commands(
        interface="ff_r_wan",
        namespace="ff_router",
        delay_ms=15.0,
        limit_pkts=100000,
    )
    assert len(cmds) == 1
    assert cmds[0] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "qdisc", "replace", "dev", "ff_r_wan",
        "root", "handle", "1:",
        "netem", "delay", "15ms", "limit", "100000",
    ]


def test_teardown_commands_structure() -> None:
    """Verifies teardown command structure."""
    mgr = BottleneckManager()
    cmds = mgr.build_teardown_commands("ff_s_wan", "ff_server")
    assert len(cmds) == 1
    assert cmds[0] == [
        "ip", "netns", "exec", "ff_server",
        "tc", "qdisc", "del", "dev", "ff_s_wan", "root",
    ]


def test_apply_bottleneck_invokes_runner() -> None:
    """apply_bottleneck executes commands via CommandRunner with check=True."""
    mock = MockRunner()
    mgr = BottleneckManager(runner=mock)
    cfg = BottleneckConfig(
        interface="ff_s_wan",
        namespace="ff_server",
        capacity_mbps=100.0,
        burst="16kb",
    )
    cmds = mgr.apply_bottleneck(cfg)
    assert len(mock.executed) == 2
    assert mock.executed[0][0] == cmds[0]
    assert mock.executed[0][1] is True
    assert mock.executed[1][0] == cmds[1]
    assert mock.executed[1][1] is True


def test_apply_delay_invokes_runner() -> None:
    """apply_delay executes commands via CommandRunner with check=True."""
    mock = MockRunner()
    mgr = BottleneckManager(runner=mock)
    cmds = mgr.apply_delay("ff_r_wan", "ff_router", delay_ms=15.0)
    assert len(mock.executed) == 1
    assert mock.executed[0][0] == cmds[0]
    assert mock.executed[0][1] is True


def test_teardown_invokes_runner_with_check_false() -> None:
    """teardown executes command via CommandRunner with check=False to tolerate missing qdiscs."""
    mock = MockRunner()
    mgr = BottleneckManager(runner=mock)
    cmds = mgr.teardown("ff_s_wan", "ff_server")
    assert len(mock.executed) == 1
    assert mock.executed[0][0] == cmds[0]
    assert mock.executed[0][1] is False
