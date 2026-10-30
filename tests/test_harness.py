"""tests/test_harness.py — Unit tests for multi-scenario harness dispatching."""

import pytest
from unittest.mock import patch, MagicMock
from src.fairflow.harness import run_scenario_harness


def test_scenario_harness_invalid_id() -> None:
    with pytest.raises(Exception):
        run_scenario_harness("scenario_unknown")


@patch("sys.platform", "darwin")
@patch("src.fairflow.harness.subprocess.run")
def test_scenario_harness_host_delegation(mock_run, tmp_path) -> None:
    """When run on host (macOS), harness delegates to scripts/vm.sh."""
    mock_run.return_value = MagicMock(returncode=0, stdout="Simulated VM output", stderr="")
    res, out_dir = run_scenario_harness("scenario_d", duration_s=5.0, run_id="test_run_d")
    assert mock_run.called
    called_cmd = mock_run.call_args[0][0]
    assert any("vm.sh" in arg for arg in called_cmd)
    assert "--scenario" in called_cmd
    assert "scenario_d" in called_cmd
