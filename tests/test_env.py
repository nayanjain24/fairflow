"""Verification tests for the FairFlow execution environment.

Ensures results/env.json is recorded from the Linux VM (not macOS host)
and that required system tools are present.
"""

import json
from pathlib import Path
import pytest


def test_env_json_reports_linux_vm() -> None:
    """Verifies results/env.json exists, reports Linux, and has required tools."""
    env_file = Path("results/env.json")
    if not env_file.exists():
        pytest.fail("results/env.json does not exist. Run scripts/00_check_env.sh inside the VM via scripts/vm.sh")

    with open(env_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    platform_system = data.get("platform", {}).get("system", "")
    if platform_system == "Darwin":
        pytest.fail(
            "results/env.json reports Darwin. All environment checks and tests must be generated "
            "inside the Ubuntu VM via scripts/vm.sh"
        )

    assert platform_system == "Linux", f"Expected Linux platform in env.json, got {platform_system!r}"
    assert data.get("netns_capable") is True, "netns_capable must be true in results/env.json"

    tools = data.get("system_tools", {})
    assert tools.get("tc", {}).get("path") != "missing", "tc must be present in env.json"
    assert tools.get("ip", {}).get("path") != "missing", "ip must be present in env.json"
    assert tools.get("iperf3", {}).get("path") != "missing", "iperf3 must be present in env.json"
