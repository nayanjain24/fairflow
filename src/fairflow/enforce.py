"""Traffic control enforcement and driver module (tc_driver) for FairFlow.

All tc/ip commands must pass through this module.
Hardware behaviour: software emulation using Linux network namespaces, veth pairs,
HTB (Hierarchical Token Bucket), and leaf qdiscs.

Non-negotiable safety invariant:
Only interfaces named 'ff_*' inside network namespaces are touched.
All other interfaces (e.g., eth0, wlan0, lo) are strictly rejected.
"""

import json
import re
import subprocess
from typing import List, Dict, Any, Optional, Protocol
from src.fairflow.policy import Policy


def validate_interface_name(interface: str) -> str:
    """Validate that the network interface follows the required 'ff_' naming convention.

    Inputs:
        interface: Name of the interface to validate.
    Outputs:
        Validated interface string.
    Failure handling:
        Raises ValueError if interface does not match '^ff_[a-z0-9_]{1,12}$' (max 15 chars).
    Success condition:
        Returns interface string unmodified if valid.
    """
    if not isinstance(interface, str):
        raise TypeError(f"Interface name must be a string, got {type(interface).__name__}")
    if not re.match(r"^ff_[a-z0-9_]{1,12}$", interface):
        raise ValueError(
            f"Interface name must match pattern '^ff_[a-z0-9_]{{1,12}}$' (max 15 chars): {interface!r}"
        )
    return interface


def validate_namespace_name(namespace: str) -> str:
    """Validate that the network namespace follows the required 'ff_' naming convention.

    Inputs:
        namespace: Name of the network namespace.
    Outputs:
        Validated namespace string.
    Failure handling:
        Raises ValueError if namespace does not match '^ff_[a-z0-9_]{1,12}$' (max 15 chars).
    Success condition:
        Returns namespace string unmodified if valid.
    """
    if not isinstance(namespace, str):
        raise TypeError(f"Namespace name must be a string, got {type(namespace).__name__}")
    if not re.match(r"^ff_[a-z0-9_]{1,12}$", namespace):
        raise ValueError(
            f"Namespace name must match pattern '^ff_[a-z0-9_]{{1,12}}$' (max 15 chars): {namespace!r}"
        )
    return namespace


class CommandRunner(Protocol):
    """Protocol for command execution, allowing seamless mocking in unit tests."""

    def run(self, cmd: List[str], check: bool = True) -> tuple[str, str, int]:
        """Execute command and return (stdout, stderr, returncode)."""
        ...


class SystemCommandRunner:
    """Default command runner invoking real system commands via subprocess."""

    def run(self, cmd: List[str], check: bool = True) -> tuple[str, str, int]:
        """Execute command via subprocess.run using argument lists with shell=False.

        Inputs:
            cmd: Command argument list of strings.
            check: Whether to raise RuntimeError on non-zero exit code.
        Outputs:
            Tuple of (stdout_str, stderr_str, exit_code).
        Failure handling:
            Raises TypeError if cmd is not a list of strings.
            Raises RuntimeError if check=True and process returns non-zero code.
        """
        if not isinstance(cmd, list) or not all(isinstance(arg, str) for arg in cmd):
            raise TypeError(f"cmd must be a list of strings, got {cmd!r}")

        proc = subprocess.run(cmd, capture_output=True, text=True, shell=False)
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command '{' '.join(cmd)}' failed with code {proc.returncode}: {proc.stderr.strip()}"
            )
        return proc.stdout, proc.stderr, proc.returncode


class TCDriver:
    """Manages tc qdisc configuration and state snapshots on emulated interfaces.

    Inputs:
        runner: CommandRunner implementation (defaults to SystemCommandRunner).
        dry_run: When True, commands are constructed and returned but not executed.
    """

    # Class ID mapping for standard FairFlow traffic classes
    CLASS_IDS: Dict[str, int] = {
        "interactive": 10,
        "streaming": 20,
        "bulk": 30,
    }

    def __init__(self, runner: Optional[CommandRunner] = None, dry_run: bool = False) -> None:
        self.runner: CommandRunner = runner or SystemCommandRunner()
        self.dry_run: bool = dry_run

    def snapshot(self, interface: str, namespace: str) -> List[Dict[str, Any]]:
        """Capture the current qdisc state of an interface as JSON.

        Inputs:
            interface: Name of the interface (must start with 'ff_').
            namespace: Name of the namespace (must start with 'ff_').
        Outputs:
            Parsed JSON array representing current qdiscs.
        Failure handling:
            Raises ValueError on invalid interface or namespace.
            Raises RuntimeError if tc command execution fails or returns invalid JSON.
        Success condition:
            Returns parsed list of qdisc dictionaries.
        """
        validate_interface_name(interface)
        validate_namespace_name(namespace)

        cmd = ["ip", "netns", "exec", namespace, "tc", "-j", "qdisc", "show", "dev", interface]
        stdout, stderr, code = self.runner.run(cmd, check=True)
        trimmed = stdout.strip()
        if not trimmed:
            return []
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, list):
                return parsed
            return [parsed]
        except json.JSONDecodeError as err:
            raise RuntimeError(f"Failed to parse tc JSON output: {stdout!r}") from err

    def apply(self, interface: str, namespace: str, policy: Policy) -> List[List[str]]:
        """Apply a QoS Policy object to the specified emulated interface.

        Constructs an HTB root qdisc with hierarchical classes for interactive,
        streaming, and bulk traffic, along with leaf qdiscs (e.g. fq_codel).

        Inputs:
            interface: Interface name (must start with 'ff_').
            namespace: Namespace name (must start with 'ff_').
            policy: Policy dataclass containing shaped capacity and class parameters.
        Outputs:
            List of command argument lists executed (or prepared in dry_run).
        Failure handling:
            Raises ValueError on invalid interface or namespace.
            Raises RuntimeError if command execution fails.
        Success condition:
            All tc qdisc and class replace commands execute successfully.
        """
        validate_interface_name(interface)
        validate_namespace_name(namespace)

        commands: List[List[str]] = []
        ns_prefix = ["ip", "netns", "exec", namespace]

        # 1. Root HTB qdisc with default class id 30 (bulk)
        commands.append(
            ns_prefix
            + [
                "tc",
                "qdisc",
                "replace",
                "dev",
                interface,
                "root",
                "handle",
                "1:",
                "htb",
                "default",
                "30",
            ]
        )

        # 2. Root HTB class shaped to link_capacity_mbps
        cap_rate = f"{policy.link_capacity_mbps:.1f}Mbit"
        commands.append(
            ns_prefix
            + [
                "tc",
                "class",
                "replace",
                "dev",
                interface,
                "parent",
                "1:",
                "classid",
                "1:1",
                "htb",
                "rate",
                cap_rate,
                "ceil",
                cap_rate,
            ]
        )

        # 3. Per-class HTB classes and leaf qdiscs
        for class_name, class_pol in policy.classes.items():
            class_id = self.CLASS_IDS.get(class_name, 99)
            floor_rate = f"{class_pol.rate_floor_mbps:.1f}Mbit"
            ceil_rate = f"{class_pol.rate_ceiling_mbps:.1f}Mbit"

            # Class definition
            commands.append(
                ns_prefix
                + [
                    "tc",
                    "class",
                    "replace",
                    "dev",
                    interface,
                    "parent",
                    "1:1",
                    "classid",
                    f"1:{class_id}",
                    "htb",
                    "rate",
                    floor_rate,
                    "ceil",
                    ceil_rate,
                    "prio",
                    str(class_pol.priority),
                ]
            )

            # Leaf qdisc (e.g. fq_codel)
            leaf = class_pol.leaf_qdisc or "fq_codel"
            commands.append(
                ns_prefix
                + [
                    "tc",
                    "qdisc",
                    "replace",
                    "dev",
                    interface,
                    "parent",
                    f"1:{class_id}",
                    "handle",
                    f"{class_id}0:",
                    leaf,
                ]
            )

        if not self.dry_run:
            for cmd in commands:
                self.runner.run(cmd, check=True)

        return commands

    def rollback(
        self, interface: str, namespace: str, target_policy: Optional[Policy] = None
    ) -> List[List[str]]:
        """Rollback QoS state to the last-known-good Policy object or delete root qdisc.

        Inputs:
            interface: Interface name (must start with 'ff_').
            namespace: Namespace name (must start with 'ff_').
            target_policy: Last-known-good Policy object. If None, deletes the root qdisc.
        Outputs:
            List of command argument lists executed (or prepared in dry_run).
        Failure handling:
            Raises ValueError on invalid interface or namespace.
            Raises RuntimeError if command execution fails.
        Success condition:
            State successfully reverted to target_policy or clean baseline.
        """
        validate_interface_name(interface)
        validate_namespace_name(namespace)

        if target_policy is not None:
            return self.apply(interface=interface, namespace=namespace, policy=target_policy)

        # If no last-known-good policy exists, remove the root qdisc to restore clean default
        cmd = ["ip", "netns", "exec", namespace, "tc", "qdisc", "del", "dev", interface, "root"]
        if not self.dry_run:
            # We don't check=True here because deleting a non-existent qdisc returns error 2
            self.runner.run(cmd, check=False)
        return [cmd]
