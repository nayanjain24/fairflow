"""Unit tests for src/fairflow/arms.py."""

from typing import List, Tuple
import pytest
from src.fairflow.arms import QoSConfig, ArmManager


class MockRunner:
    def __init__(self, stdout: str = "", return_code: int = 0) -> None:
        self.stdout: str = stdout
        self.return_code: int = return_code
        self.executed: List[Tuple[List[str], bool]] = []

    def run(self, cmd: List[str], check: bool = True) -> Tuple[str, str, int]:
        self.executed.append((cmd, check))
        return (self.stdout, "", self.return_code)


def test_qos_config_validation() -> None:
    cfg = QoSConfig(
        interface="ff_r_lan",
        namespace="ff_router",
        shaping_rate_mbps=95.0,
        interactive_floor_mbps=2.0,
        streaming_floor_mbps=8.0,
        bulk_floor_mbps=2.0,
        call_port=5004,
    )
    assert cfg.interface == "ff_r_lan"
    assert cfg.shaping_rate_mbps == 95.0


@pytest.mark.parametrize("param,bad_val", [
    ("interface", "eth0"),
    ("namespace", "root"),
    ("shaping_rate_mbps", 0.0),
    ("interactive_floor_mbps", -1.0),
    ("streaming_floor_mbps", 0.0),
    ("bulk_floor_mbps", -2.0),
    ("call_port", 0),
    ("call_port", 70000),
])
def test_qos_config_invalid_parameters(param: str, bad_val: object) -> None:
    kwargs = {
        "interface": "ff_r_lan",
        "namespace": "ff_router",
        param: bad_val,
    }
    with pytest.raises((ValueError, TypeError)):
        QoSConfig(**kwargs)


def test_build_commands_r0() -> None:
    mgr = ArmManager()
    cfg = QoSConfig()
    cmds = mgr.build_commands("R0_no_qos", cfg)
    assert len(cmds) == 1
    assert cmds[0] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "qdisc", "replace", "dev", "ff_r_lan",
        "root", "pfifo", "limit", "1000",
    ]


def test_build_commands_b1() -> None:
    mgr = ArmManager()
    cfg = QoSConfig()
    cmds = mgr.build_commands("B1_static_htb", cfg)
    assert len(cmds) == 9
    # Root HTB
    assert cmds[0] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "qdisc", "replace", "dev", "ff_r_lan",
        "root", "handle", "1:", "htb", "default", "30", "r2q", "100",
    ]
    # Shaping class 1:1
    assert cmds[1] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "class", "replace", "dev", "ff_r_lan",
        "parent", "1:", "classid", "1:1", "htb", "rate", "95mbit", "ceil", "95mbit",
    ]
    # Interactive class 1:10
    assert cmds[2] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "class", "replace", "dev", "ff_r_lan",
        "parent", "1:1", "classid", "1:10", "htb", "rate", "2mbit", "ceil", "95mbit", "prio", "1",
    ]
    # Filter for UDP dport 5004 -> 1:10
    assert cmds[8] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "filter", "replace", "dev", "ff_r_lan",
        "parent", "1:", "protocol", "ip", "prio", "1", "u32",
        "match", "ip", "protocol", "17", "0xff",
        "match", "ip", "dport", "5004", "0xffff",
        "flowid", "1:10",
    ]


def test_build_commands_b2a() -> None:
    mgr = ArmManager()
    cfg = QoSConfig()
    cmds = mgr.build_commands("B2a_fq_codel", cfg)
    assert len(cmds) == 3
    assert cmds[2] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "qdisc", "replace", "dev", "ff_r_lan",
        "parent", "1:1", "handle", "10:", "fq_codel",
    ]


def test_build_commands_b2b() -> None:
    mgr = ArmManager()
    cfg = QoSConfig()
    cmds = mgr.build_commands("B2b_cake", cfg)
    assert len(cmds) == 1
    assert cmds[0] == [
        "ip", "netns", "exec", "ff_router",
        "tc", "qdisc", "replace", "dev", "ff_r_lan",
        "root", "cake", "bandwidth", "95mbit", "diffserv3", "triple-isolate",
        "nonat", "nowash", "no-ack-filter", "split-gso", "rtt", "100ms", "raw", "overhead", "0",
    ]


def test_build_commands_unsupported_arm() -> None:
    mgr = ArmManager()
    cfg = QoSConfig()
    with pytest.raises(ValueError, match="Unsupported arm 'unknown_arm'"):
        mgr.build_commands("unknown_arm", cfg)


def test_apply_arm_executes() -> None:
    mock = MockRunner()
    mgr = ArmManager(runner=mock)
    cfg = QoSConfig()
    cmds = mgr.apply_arm("R0_no_qos", cfg)
    assert len(mock.executed) == 1
    assert mock.executed[0][0] == cmds[0]
    assert mock.executed[0][1] is True


def test_snapshot_qdiscs() -> None:
    mock = MockRunner(stdout='[{"kind": "pfifo"}]')
    mgr = ArmManager(runner=mock)
    cfg = QoSConfig()
    data = mgr.snapshot_qdiscs(cfg)
    assert data == [{"kind": "pfifo"}]
