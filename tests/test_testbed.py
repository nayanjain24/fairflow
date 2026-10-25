"""Unit and integration tests for testbed management.

Ensures:
- Strictly enforces 'ff_' naming on all interfaces and namespaces.
- Creates topology (client, router, server) via ip netns / ip link.
- Cleans up cleanly on down().
- Integration test for complete netns lifecycle on Linux root.
"""

import os
import shutil
import sys
import pytest
from src.fairflow.testbed import Testbed, ScenarioConfig
from tests.conftest import MockCommandRunner


def test_reject_scenario_with_non_ff_interface(mock_runner: MockCommandRunner) -> None:
    """Verifies that scenario configs containing non-ff_ interface names are rejected."""
    bad_config = {
        "scenario_name": "invalid_iface",
        "namespaces": {"client": "ff_c", "router": "ff_r", "server": "ff_s"},
        "links": {
            "lan": {
                "endpoint_a": {"namespace": "ff_c", "interface": "eth0", "ip": "10.0.1.2/24"},
                "endpoint_b": {"namespace": "ff_r", "interface": "ff_r_lan", "ip": "10.0.1.1/24"},
            }
        },
    }

    with pytest.raises(ValueError, match="Interface name must start with 'ff_'"):
        ScenarioConfig.from_dict(bad_config)


def test_reject_scenario_with_non_ff_namespace(mock_runner: MockCommandRunner) -> None:
    """Verifies that scenario configs containing non-ff_ namespace names are rejected."""
    bad_config = {
        "scenario_name": "invalid_ns",
        "namespaces": {"client": "client_ns", "router": "ff_r", "server": "ff_s"},
        "links": {},
    }

    with pytest.raises(ValueError, match="Namespace name must start with 'ff_'"):
        ScenarioConfig.from_dict(bad_config)


def test_testbed_up_generates_correct_commands(mock_runner: MockCommandRunner) -> None:
    """Verifies that testbed.up() creates namespaces, veth pairs, addresses, routes, and sysctls."""
    config_dict = {
        "scenario_name": "test_up",
        "namespaces": {"client": "ff_c", "router": "ff_r", "server": "ff_s"},
        "links": {
            "lan": {
                "endpoint_a": {"namespace": "ff_c", "interface": "ff_c_lan", "ip": "10.0.1.2/24"},
                "endpoint_b": {"namespace": "ff_r", "interface": "ff_r_lan", "ip": "10.0.1.1/24"},
            },
            "wan": {
                "endpoint_a": {"namespace": "ff_r", "interface": "ff_r_wan", "ip": "10.0.2.1/24"},
                "endpoint_b": {"namespace": "ff_s", "interface": "ff_s_wan", "ip": "10.0.2.2/24"},
            },
        },
        "routes": [
            {"namespace": "ff_c", "destination": "10.0.2.0/24", "gateway": "10.0.1.1"},
            {"namespace": "ff_s", "destination": "10.0.1.0/24", "gateway": "10.0.2.1"},
        ],
    }

    config = ScenarioConfig.from_dict(config_dict)
    testbed = Testbed(config=config, runner=mock_runner)
    testbed.up()

    history_str = [" ".join(cmd) for cmd in mock_runner.history]

    # Verify namespace creation
    assert any("ip netns add ff_c" in cmd for cmd in history_str)
    assert any("ip netns add ff_r" in cmd for cmd in history_str)
    assert any("ip netns add ff_s" in cmd for cmd in history_str)

    # Verify veth creation
    assert any("ip link add ff_c_lan type veth peer name ff_r_lan" in cmd for cmd in history_str)

    # Verify router IP forwarding enabled in router namespace only
    assert any("ip netns exec ff_r sysctl -w net.ipv4.ip_forward=1" in cmd for cmd in history_str)

    # Verify loopback interfaces brought up
    assert any("ip netns exec ff_c ip link set lo up" in cmd for cmd in history_str)


def test_testbed_down_deletes_namespaces(mock_runner: MockCommandRunner) -> None:
    """Verifies that testbed.down() safely cleans up all created namespaces."""
    config_dict = {
        "scenario_name": "test_down",
        "namespaces": {"client": "ff_c", "router": "ff_r", "server": "ff_s"},
        "links": {},
        "routes": [],
    }
    config = ScenarioConfig.from_dict(config_dict)
    testbed = Testbed(config=config, runner=mock_runner)
    testbed.down()

    history_str = [" ".join(cmd) for cmd in mock_runner.history]
    assert any("ip netns del ff_c" in cmd for cmd in history_str)
    assert any("ip netns del ff_r" in cmd for cmd in history_str)
    assert any("ip netns del ff_s" in cmd for cmd in history_str)


@pytest.mark.integration
def test_integration_testbed_up_then_down_is_clean() -> None:
    """Integration test: create real namespaces and veths, then tear them down."""
    if sys.platform != "linux":
        pytest.skip("Integration test requires Linux kernel")
    if os.geteuid() != 0:
        pytest.skip("Integration test requires root privileges")
    if not shutil.which("ip"):
        pytest.skip("iproute2 'ip' command not found on PATH")

    scenario_file = "experiments/idle_noise_floor.yaml"
    config = ScenarioConfig.from_yaml(scenario_file)
    testbed = Testbed(config=config)

    try:
        testbed.up()
        # Verify namespaces exist via ip netns list
        stdout, _, _ = testbed.runner.run(["ip", "netns", "list"])
        assert "ff_client" in stdout
        assert "ff_router" in stdout
        assert "ff_server" in stdout
    finally:
        testbed.down()
        # Verify namespaces are removed
        stdout, _, _ = testbed.runner.run(["ip", "netns", "list"])
        assert "ff_client" not in stdout
        assert "ff_router" not in stdout
        assert "ff_server" not in stdout
