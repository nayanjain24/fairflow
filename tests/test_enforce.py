"""Unit and integration tests for enforce (tc_driver) module.

Ensures:
- Strict interface allowlist (ff_* only).
- Clean command runner abstraction and dry-run mode.
- Policy application and rollback using stored Policy objects.
- Real integration test proving rollback restores identical 'tc -j qdisc show' JSON.
"""

import json
import os
import shutil
import sys
import pytest
from src.fairflow.policy import Policy, ClassPolicy
from src.fairflow.enforce import (
    validate_interface_name,
    TCDriver,
    CommandRunner,
    SystemCommandRunner,
)
from tests.conftest import MockCommandRunner


def test_reject_non_ff_interface() -> None:
    """Verifies that non-ff_* interfaces and malformed names are strictly refused."""
    # Disallowed prefixes
    for bad_name in ["eth0", "wlan0", "en0", "docker0", "lo", "veth0"]:
        with pytest.raises(ValueError, match="must match pattern"):
            validate_interface_name(bad_name)

    # Disallowed characters / casing / empty suffix
    for bad_pattern in ["ff_", "ff_WAN", "ff_eth-0", "ff_a.b", "ff_a@b"]:
        with pytest.raises(ValueError, match="must match pattern"):
            validate_interface_name(bad_pattern)

    # Length > 15 chars (e.g. ff_ + 13 chars = 16 chars)
    too_long = "ff_1234567890123"
    assert len(too_long) == 16
    with pytest.raises(ValueError, match="must match pattern"):
        validate_interface_name(too_long)

    # Non-string types
    for bad_type in [None, 123, ["ff_eth0"]]:
        with pytest.raises(TypeError, match="must be a string"):
            validate_interface_name(bad_type)  # type: ignore[arg-type]


def test_accept_ff_interface() -> None:
    """Verifies that valid ff_* interface names (up to 15 chars) pass validation."""
    valid_names = [
        "ff_wan",
        "ff_r_lan",
        "ff_s_wan",
        "ff_test0",
        "ff_a_1_b",
        "ff_123456789012",  # exactly 15 chars (ff_ + 12 chars)
    ]
    for valid_name in valid_names:
        assert len(valid_name) <= 15
        assert validate_interface_name(valid_name) == valid_name


def test_system_command_runner_enforces_argument_list_safety() -> None:
    """Verifies SystemCommandRunner strictly enforces argument lists (no raw shell strings)."""
    runner = SystemCommandRunner()

    with pytest.raises(TypeError, match="cmd must be a list of strings"):
        runner.run("echo dangerous; rm -rf /")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="cmd must be a list of strings"):
        runner.run([1, 2, 3])  # type: ignore[list-item]


def test_tc_driver_refuses_non_ff_interface_on_all_operations(mock_runner: MockCommandRunner) -> None:
    """Verifies that TCDriver methods reject non-ff_ interfaces before any command execution."""
    driver = TCDriver(runner=mock_runner)
    dummy_policy = Policy(
        link_capacity_mbps=100.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=10.0, rate_ceiling_mbps=100.0, priority=1, leaf_qdisc="fq_codel"),
        },
    )

    with pytest.raises(ValueError):
        driver.apply(interface="eth0", namespace="ff_test", policy=dummy_policy)

    with pytest.raises(ValueError):
        driver.snapshot(interface="eth0", namespace="ff_test")

    with pytest.raises(ValueError):
        driver.rollback(interface="eth0", namespace="ff_test", target_policy=None)

    assert len(mock_runner.history) == 0


def test_dry_run_mode_does_not_execute_commands(mock_runner: MockCommandRunner) -> None:
    """Verifies dry-run mode returns commands without executing them."""
    driver = TCDriver(runner=mock_runner, dry_run=True)
    policy = Policy(
        link_capacity_mbps=50.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=5.0, rate_ceiling_mbps=50.0, priority=1, leaf_qdisc="fq_codel"),
            "bulk": ClassPolicy(rate_floor_mbps=1.0, rate_ceiling_mbps=50.0, priority=2, leaf_qdisc="fq_codel"),
        },
    )

    commands = driver.apply(interface="ff_wan", namespace="ff_router", policy=policy)
    assert len(commands) > 0
    # runner history should remain empty because it was a dry-run
    assert len(mock_runner.history) == 0


def test_snapshot_calls_tc_json(mock_runner: MockCommandRunner) -> None:
    """Verifies that snapshot issues 'tc -j qdisc show dev <iface>' inside namespace."""
    mock_runner.responses["tc -j qdisc show"] = ('[{"kind":"htb","handle":"1:"}]', "", 0)
    driver = TCDriver(runner=mock_runner)

    snapshot_data = driver.snapshot(interface="ff_wan", namespace="ff_router")
    assert snapshot_data == [{"kind": "htb", "handle": "1:"}]
    assert any("tc -j qdisc show dev ff_wan" in " ".join(cmd) for cmd in mock_runner.history)


def test_apply_policy_generates_and_executes_tc_commands(mock_runner: MockCommandRunner) -> None:
    """Verifies that apply constructs HTB root, classes, and leaf qdiscs."""
    driver = TCDriver(runner=mock_runner)
    policy = Policy(
        link_capacity_mbps=100.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=20.0, rate_ceiling_mbps=100.0, priority=1, leaf_qdisc="fq_codel"),
            "streaming": ClassPolicy(rate_floor_mbps=30.0, rate_ceiling_mbps=100.0, priority=2, leaf_qdisc="fq_codel"),
            "bulk": ClassPolicy(rate_floor_mbps=5.0, rate_ceiling_mbps=100.0, priority=3, leaf_qdisc="fq_codel"),
        },
    )

    commands = driver.apply(interface="ff_r_lan", namespace="ff_router", policy=policy)
    assert len(commands) > 0
    assert len(mock_runner.history) == len(commands)


def test_rollback_to_clean_when_no_target_policy(mock_runner: MockCommandRunner) -> None:
    """Verifies that rolling back with target_policy=None deletes the root qdisc."""
    driver = TCDriver(runner=mock_runner)
    driver.rollback(interface="ff_r_lan", namespace="ff_router", target_policy=None)

    assert len(mock_runner.history) == 1
    cmd_str = " ".join(mock_runner.history[0])
    assert "ip netns exec ff_router tc qdisc del dev ff_r_lan root" in cmd_str


def test_rollback_applies_stored_policy(mock_runner: MockCommandRunner) -> None:
    """Verifies that rollback with a target_policy reapplies that exact policy."""
    driver = TCDriver(runner=mock_runner)
    last_known_good = Policy(
        link_capacity_mbps=40.0,
        classes={
            "interactive": ClassPolicy(rate_floor_mbps=10.0, rate_ceiling_mbps=40.0, priority=1, leaf_qdisc="fq_codel"),
        },
    )

    driver.rollback(interface="ff_r_lan", namespace="ff_router", target_policy=last_known_good)
    assert any("rate 40.0Mbit" in " ".join(cmd) for cmd in mock_runner.history)


@pytest.mark.integration
def test_real_integration_rollback_restores_identical_tc_json() -> None:
    """Real integration test on Linux kernel with network namespaces and root.

    Creates an isolated test namespace and veth pair named ff_test0 <-> ff_test1,
    applies Policy 1, captures 'tc -j qdisc show', applies Policy 2, rolls back to
    Policy 1, and verifies the resulting 'tc -j qdisc show' JSON is identical.

    Fails loudly if not run as root on Linux with iproute2.
    """
    if sys.platform != "linux":
        pytest.fail("Integration test requires Linux kernel (network namespaces and iproute2)")
    if os.geteuid() != 0:
        pytest.fail("Integration test requires root privileges for network namespace operations; run with sudo")
    if not shutil.which("ip") or not shutil.which("tc"):
        pytest.fail("iproute2 tools (ip, tc) not found on PATH")

    ns = "ff_integ_ns"
    veth_a = "ff_int_a"
    veth_b = "ff_int_b"
    runner = SystemCommandRunner()
    driver = TCDriver(runner=runner)

    # Clean up any leftover test namespace first
    runner.run(["ip", "netns", "del", ns], check=False)

    try:
        # Create isolated namespace and veth pair
        runner.run(["ip", "netns", "add", ns])
        runner.run(["ip", "link", "add", veth_a, "type", "veth", "peer", "name", veth_b])
        runner.run(["ip", "link", "set", veth_a, "netns", ns])
        runner.run(["ip", "netns", "exec", ns, "ip", "link", "set", veth_a, "up"])

        p1 = Policy(
            link_capacity_mbps=50.0,
            classes={
                "interactive": ClassPolicy(rate_floor_mbps=10.0, rate_ceiling_mbps=50.0, priority=1, leaf_qdisc="fq_codel"),
                "bulk": ClassPolicy(rate_floor_mbps=5.0, rate_ceiling_mbps=50.0, priority=2, leaf_qdisc="fq_codel"),
            },
        )
        p2 = Policy(
            link_capacity_mbps=20.0,
            classes={
                "interactive": ClassPolicy(rate_floor_mbps=5.0, rate_ceiling_mbps=20.0, priority=1, leaf_qdisc="fq_codel"),
                "bulk": ClassPolicy(rate_floor_mbps=2.0, rate_ceiling_mbps=20.0, priority=2, leaf_qdisc="fq_codel"),
            },
        )

        # Apply Policy 1 and capture snapshot
        driver.apply(interface=veth_a, namespace=ns, policy=p1)
        json_p1_initial = driver.snapshot(interface=veth_a, namespace=ns)

        # Apply Policy 2 and verify it changed
        driver.apply(interface=veth_a, namespace=ns, policy=p2)
        json_p2 = driver.snapshot(interface=veth_a, namespace=ns)
        assert json_p2 != json_p1_initial, "Policy 2 snapshot should differ from Policy 1"

        # Rollback to Policy 1
        driver.rollback(interface=veth_a, namespace=ns, target_policy=p1)
        json_p1_after_rollback = driver.snapshot(interface=veth_a, namespace=ns)

        # Assert identical qdisc structure
        assert json_p1_after_rollback == json_p1_initial, "Rollback did not restore identical tc -j qdisc state"

    finally:
        # Always tear down test namespace and link
        runner.run(["ip", "netns", "del", ns], check=False)
        runner.run(["ip", "link", "del", veth_b], check=False)
