"""Shared fixtures and configuration for FairFlow tests."""

from typing import List, Tuple, Dict, Any, Optional
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as requiring Linux network namespace and root privileges"
    )


class MockCommandRunner:
    """Mock command runner for unit testing without invoking real system commands.

    Inputs:
        responses: Optional dictionary mapping command substrings to (stdout, stderr, returncode)
    Outputs:
        Records history of commands executed.
    """

    def __init__(self, responses: Optional[Dict[str, Tuple[str, str, int]]] = None) -> None:
        self.history: List[List[str]] = []
        self.responses: Dict[str, Tuple[str, str, int]] = responses or {}

    def run(self, cmd: List[str], check: bool = True) -> Tuple[str, str, int]:
        """Record command and return configured mock response or default success (0, '', '')."""
        self.history.append(cmd)
        cmd_str = " ".join(cmd)

        for pattern, res in self.responses.items():
            if pattern in cmd_str:
                stdout, stderr, code = res
                if check and code != 0:
                    raise RuntimeError(f"Command failed with code {code}: {stderr}")
                return stdout, stderr, code

        return "", "", 0


@pytest.fixture
def mock_runner() -> MockCommandRunner:
    """Fixture providing a fresh MockCommandRunner instance."""
    return MockCommandRunner()
