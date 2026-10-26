"""Unit tests for src/fairflow/offloads.py."""

from typing import List, Tuple
import pytest
from src.fairflow.offloads import disable_offloads, query_offload_status


class MockRunner:
    def __init__(self, stdout: str = "", return_code: int = 0) -> None:
        self.stdout: str = stdout
        self.return_code: int = return_code
        self.executed: List[Tuple[List[str], bool]] = []

    def run(self, cmd: List[str], check: bool = True) -> Tuple[str, str, int]:
        self.executed.append((cmd, check))
        return (self.stdout, "", self.return_code)


def test_disable_offloads_command() -> None:
    mock = MockRunner()
    cmd = disable_offloads("ff_c_lan", "ff_client", runner=mock)
    assert cmd == [
        "ip", "netns", "exec", "ff_client",
        "ethtool", "-K", "ff_c_lan",
        "gso", "off", "gro", "off", "tso", "off",
    ]
    assert len(mock.executed) == 1
    assert mock.executed[0][0] == cmd
    assert mock.executed[0][1] is True


def test_disable_offloads_rejects_invalid_interface() -> None:
    mock = MockRunner()
    with pytest.raises(ValueError, match="Interface name must match pattern"):
        disable_offloads("eth0", "ff_client", runner=mock)


def test_disable_offloads_rejects_invalid_namespace() -> None:
    mock = MockRunner()
    with pytest.raises(ValueError, match="Namespace name must match pattern"):
        disable_offloads("ff_c_lan", "default", runner=mock)


def test_query_offload_status_parsing() -> None:
    sample_output = """
rx-checksumming: on
tx-checksumming: on
scatter-gather: on
tcp-segmentation-offload: off
generic-segmentation-offload: off
generic-receive-offload: off
"""
    mock = MockRunner(stdout=sample_output)
    status = query_offload_status("ff_c_lan", "ff_client", runner=mock)
    assert status == {
        "tso": False,
        "gso": False,
        "gro": False,
    }
