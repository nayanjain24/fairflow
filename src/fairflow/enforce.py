"""Traffic control enforcement and driver module (tc_driver) for FairFlow.

All tc/ip commands must pass through this module.
Hardware behaviour: software emulation using Linux network namespaces, veth pairs,
HTB (Hierarchical Token Bucket), and leaf qdiscs.

Non-negotiable safety invariant:
Only interfaces named 'ff_*' inside network namespaces are touched.
All other interfaces (e.g., eth0, wlan0, lo) are strictly rejected.
"""

import json
import os
import re
import subprocess
import sys
from typing import List, Dict, Any, Optional, Protocol, Sequence
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

    PRIVILEGED_BINARIES = frozenset({"ip", "tc", "ethtool", "sysctl"})

    def __init__(self, use_sudo_if_non_root: bool = False) -> None:
        self.use_sudo_if_non_root = use_sudo_if_non_root

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

        exec_cmd = cmd
        if (
            self.use_sudo_if_non_root
            and sys.platform == "linux"
            and os.geteuid() != 0
            and cmd
            and cmd[0] in self.PRIVILEGED_BINARIES
        ):
            exec_cmd = ["sudo", "-n"] + cmd

        proc = subprocess.run(exec_cmd, capture_output=True, text=True, shell=False)
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command '{' '.join(cmd)}' failed with code {proc.returncode}: {proc.stderr.strip()}"
            )
        return proc.stdout, proc.stderr, proc.returncode


class MockCommandRunner:
    """Mock command runner for tests and non-Linux/dry-run environments."""

    def __init__(self, responses: Optional[Dict[str, tuple[str, str, int]]] = None) -> None:
        self.commands: List[List[str]] = []
        self.responses: Dict[str, tuple[str, str, int]] = responses or {}

    def run(self, cmd: List[str], check: bool = True) -> tuple[str, str, int]:
        if not isinstance(cmd, list) or not all(isinstance(arg, str) for arg in cmd):
            raise TypeError(f"cmd must be a list of strings, got {cmd!r}")
        self.commands.append(cmd)
        cmd_str = " ".join(cmd)
        for pattern, resp in self.responses.items():
            if pattern in cmd_str:
                if check and resp[2] != 0:
                    raise RuntimeError(f"Command '{cmd_str}' failed with code {resp[2]}: {resp[1]}")
                return resp
        if "tc -j qdisc show" in cmd_str or "tc -s -j qdisc show" in cmd_str:
            return ('[{"kind": "htb", "handle": "1:", "bytes": 1000, "drops": 0}]', "", 0)
        if "tc -j class show" in cmd_str:
            return ('[{"classid": "1:10", "rate": "15Mbit"}]', "", 0)
        return ("", "", 0)


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

    def snapshot_classes(self, interface: str, namespace: str) -> List[Dict[str, Any]]:
        """Capture the current class state of an interface as JSON.

        Inputs:
            interface: Name of the interface (must start with 'ff_').
            namespace: Name of the namespace (must start with 'ff_').
        Outputs:
            Parsed JSON array representing current classes.
        """
        validate_interface_name(interface)
        validate_namespace_name(namespace)

        cmd = ["ip", "netns", "exec", namespace, "tc", "-j", "class", "show", "dev", interface]
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
            raise RuntimeError(f"Failed to parse tc class JSON output: {stdout!r}") from err

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

        # 1. Reset root qdisc to ensure clean tree replacement
        commands.append(ns_prefix + ["tc", "qdisc", "del", "dev", interface, "root"])

        # 2. Root HTB qdisc with default class id 30 (bulk)
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

        # 3. Root HTB class shaped to link_capacity_mbps
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

        # 4. Per-class HTB classes and leaf qdiscs
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
            # Execute root qdisc deletion allowing it to fail gracefully if no qdisc exists
            self.runner.run(commands[0], check=False)
            for cmd in commands[1:]:
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

    def snapshot_stats(self, interface: str, namespace: str) -> List[Dict[str, Any]]:
        """Capture live qdisc statistics including bytes, packets, drops, overlimits, and backlog via tc -s -j."""
        validate_interface_name(interface)
        validate_namespace_name(namespace)

        cmd = ["ip", "netns", "exec", namespace, "tc", "-s", "-j", "qdisc", "show", "dev", interface]
        stdout, _, _ = self.runner.run(cmd, check=False)
        trimmed = stdout.strip()
        if not trimmed:
            return []
        try:
            parsed = json.loads(trimmed)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return []

    def snapshot_class_stats(self, interface: str, namespace: str) -> List[Dict[str, Any]]:
        """Capture live HTB class statistics via tc -s -j class show."""
        validate_interface_name(interface)
        validate_namespace_name(namespace)

        cmd = ["ip", "netns", "exec", namespace, "tc", "-s", "-j", "class", "show", "dev", interface]
        stdout, _, _ = self.runner.run(cmd, check=False)
        trimmed = stdout.strip()
        if not trimmed:
            return []
        try:
            parsed = json.loads(trimmed)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return []

    def apply_flow_filters(
        self,
        interface: str,
        namespace: str,
        user_intents: Optional[Sequence[Any]] = None,
    ) -> List[List[str]]:
        """Install kernel u32 packet classification filters steering traffic into HTB classes 1:10, 1:20, 1:30.

        Priority 1: UserIntent explicit overrides (ports / IPs).
        Priority 2: DSCP EF (46 -> TOS 0xb8) & Interactive UDP ports (5004, 5005, 27015) -> 1:10.
        Priority 3: DSCP AF31 (26 -> TOS 0x68) & Streaming TCP/UDP ports (1935, 8080) -> 1:20.
        Default (unmatched): Routed to 1:30 (bulk) via HTB default 30.
        """
        validate_interface_name(interface)
        validate_namespace_name(namespace)

        ns_prefix = ["ip", "netns", "exec", namespace]
        commands: List[List[str]] = []

        # 1. Clear existing root filters on 1: so stale overrides don't persist
        del_cmd = ns_prefix + ["tc", "filter", "del", "dev", interface, "parent", "1:"]
        commands.append(del_cmd)
        if not self.dry_run:
            self.runner.run(del_cmd, check=False)

        filter_cmds: List[List[str]] = []

        # 2. UserIntent overrides (highest filter priority = 1)
        if user_intents:
            for intent in user_intents:
                target_cls = getattr(intent, "target_class", "bulk")
                cid = self.CLASS_IDS.get(target_cls, 30)
                proto_name = (getattr(intent, "protocol", None) or "").lower()
                src_port = getattr(intent, "src_port", None)
                dst_port = getattr(intent, "dst_port", None)

                match_args: List[str] = []
                if proto_name == "udp":
                    match_args.extend(["match", "ip", "protocol", "17", "0xff"])
                elif proto_name == "tcp":
                    match_args.extend(["match", "ip", "protocol", "6", "0xff"])

                if src_port is not None and 1 <= int(src_port) <= 65535:
                    match_args.extend(["match", "ip", "sport", str(int(src_port)), "0xffff"])
                if dst_port is not None and 1 <= int(dst_port) <= 65535:
                    match_args.extend(["match", "ip", "dport", str(int(dst_port)), "0xffff"])

                if match_args:
                    filter_cmds.append(
                        ns_prefix
                        + [
                            "tc",
                            "filter",
                            "add",
                            "dev",
                            interface,
                            "parent",
                            "1:",
                            "protocol",
                            "ip",
                            "prio",
                            "1",
                            "u32",
                        ]
                        + match_args
                        + ["flowid", f"1:{cid}"]
                    )

        # 3. Standard interactive rules -> class 1:10 (prio 2)
        for port in (5004, 5005, 27015):
            for port_flag in ("dport", "sport"):
                filter_cmds.append(
                    ns_prefix
                    + [
                        "tc",
                        "filter",
                        "add",
                        "dev",
                        interface,
                        "parent",
                        "1:",
                        "protocol",
                        "ip",
                        "prio",
                        "2",
                        "u32",
                        "match",
                        "ip",
                        "protocol",
                        "17",
                        "0xff",
                        "match",
                        "ip",
                        port_flag,
                        str(port),
                        "0xffff",
                        "flowid",
                        "1:10",
                    ]
                )

        # DSCP EF (46 << 2 = 184 = 0xb8) -> class 1:10
        filter_cmds.append(
            ns_prefix
            + [
                "tc",
                "filter",
                "add",
                "dev",
                interface,
                "parent",
                "1:",
                "protocol",
                "ip",
                "prio",
                "2",
                "u32",
                "match",
                "ip",
                "tos",
                "0xb8",
                "0xfc",
                "flowid",
                "1:10",
            ]
        )

        # 4. Standard streaming rules -> class 1:20 (prio 3)
        for port in (1935, 8080):
            for port_flag in ("sport", "dport"):
                filter_cmds.append(
                    ns_prefix
                    + [
                        "tc",
                        "filter",
                        "add",
                        "dev",
                        interface,
                        "parent",
                        "1:",
                        "protocol",
                        "ip",
                        "prio",
                        "3",
                        "u32",
                        "match",
                        "ip",
                        "protocol",
                        "6",
                        "0xff",
                        "match",
                        "ip",
                        port_flag,
                        str(port),
                        "0xffff",
                        "flowid",
                        "1:20",
                    ]
                )

        if not self.dry_run:
            for cmd in filter_cmds:
                self.runner.run(cmd, check=False)

        commands.extend(filter_cmds)
        return commands
