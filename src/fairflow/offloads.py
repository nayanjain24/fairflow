"""offloads.py — Hardware/segmentation offload management for FairFlow interfaces.

Disables GSO (Generic Segmentation Offload), GRO (Generic Receive Offload),
and TSO (TCP Segmentation Offload) on virtual interfaces so that emulated
queues and rate limiters operate on real MTU-sized packets rather than
large synthetic super-packets (64 KB).
"""

from typing import Dict, List, Optional
from src.fairflow.enforce import (
    validate_interface_name,
    validate_namespace_name,
    CommandRunner,
    SystemCommandRunner,
)


def disable_offloads(
    interface: str,
    namespace: str,
    runner: Optional[CommandRunner] = None,
) -> List[str]:
    """Disable GSO, GRO, and TSO on an interface within a network namespace.

    Inputs:
        interface: Interface name (must start with 'ff_').
        namespace: Namespace name (must start with 'ff_').
        runner: CommandRunner instance (defaults to SystemCommandRunner).

    Returns:
        The command list executed.
    """
    validate_interface_name(interface)
    validate_namespace_name(namespace)
    cmd = [
        "ip",
        "netns",
        "exec",
        namespace,
        "ethtool",
        "-K",
        interface,
        "gso",
        "off",
        "gro",
        "off",
        "tso",
        "off",
    ]
    r = runner or SystemCommandRunner()
    r.run(cmd, check=True)
    return cmd


def query_offload_status(
    interface: str,
    namespace: str,
    runner: Optional[CommandRunner] = None,
) -> Dict[str, bool]:
    """Query current status of gso, gro, tso on an interface via ethtool -k.

    Returns:
        Dictionary mapping feature name ('gso', 'gro', 'tso') to boolean status (True if on, False if off).
    """
    validate_interface_name(interface)
    validate_namespace_name(namespace)
    cmd = ["ip", "netns", "exec", namespace, "ethtool", "-k", interface]
    r = runner or SystemCommandRunner()
    stdout, _, _ = r.run(cmd, check=True)

    result: Dict[str, bool] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip().lower()
        if key in ("generic-segmentation-offload", "gso"):
            result["gso"] = "on" in val
        elif key in ("generic-receive-offload", "gro"):
            result["gro"] = "on" in val
        elif key in ("tcp-segmentation-offload", "tso"):
            result["tso"] = "on" in val

    return result
