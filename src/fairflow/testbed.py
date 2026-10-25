"""Testbed lifecycle and topology provisioning for FairFlow.

Hardware behaviour: software emulation using Linux network namespaces and veth pairs.
Creates and tears down isolated namespaces: client, router, and server.
Enforces strict 'ff_' naming on all interfaces and namespaces.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml
from src.fairflow.enforce import (
    validate_interface_name,
    validate_namespace_name,
    CommandRunner,
    SystemCommandRunner,
)


@dataclass(frozen=True)
class Endpoint:
    """Interface configuration on one side of an emulated link."""

    namespace: str
    interface: str
    ip: str

    def __post_init__(self) -> None:
        validate_namespace_name(self.namespace)
        validate_interface_name(self.interface)


@dataclass(frozen=True)
class Link:
    """Emulated veth link connecting two namespace endpoints."""

    endpoint_a: Endpoint
    endpoint_b: Endpoint


@dataclass(frozen=True)
class Route:
    """Static route inside an emulated namespace."""

    namespace: str
    destination: str
    gateway: str

    def __post_init__(self) -> None:
        validate_namespace_name(self.namespace)


@dataclass(frozen=True)
class ScenarioConfig:
    """Validated configuration for a testbed scenario."""

    scenario_name: str
    namespaces: Dict[str, str]
    links: Dict[str, Link]
    routes: List[Route] = field(default_factory=list)
    duration_seconds: int = 60

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioConfig":
        """Parse and validate scenario dictionary."""
        scenario_name = data.get("scenario_name", "unnamed_scenario")
        raw_namespaces = data.get("namespaces", {})

        # Validate all namespaces start with ff_
        namespaces: Dict[str, str] = {}
        for role, ns_name in raw_namespaces.items():
            namespaces[role] = validate_namespace_name(ns_name)

        # Parse links
        links: Dict[str, Link] = {}
        for link_name, link_data in data.get("links", {}).items():
            ep_a = Endpoint(
                namespace=link_data["endpoint_a"]["namespace"],
                interface=link_data["endpoint_a"]["interface"],
                ip=link_data["endpoint_a"]["ip"],
            )
            ep_b = Endpoint(
                namespace=link_data["endpoint_b"]["namespace"],
                interface=link_data["endpoint_b"]["interface"],
                ip=link_data["endpoint_b"]["ip"],
            )
            links[link_name] = Link(endpoint_a=ep_a, endpoint_b=ep_b)

        # Parse routes
        routes: List[Route] = []
        for r in data.get("routes", []):
            routes.append(
                Route(
                    namespace=r["namespace"],
                    destination=r["destination"],
                    gateway=r["gateway"],
                )
            )

        duration = int(data.get("duration_seconds", 60))
        return cls(
            scenario_name=scenario_name,
            namespaces=namespaces,
            links=links,
            routes=routes,
            duration_seconds=duration,
        )

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "ScenarioConfig":
        """Load scenario config from a YAML file."""
        content = Path(yaml_path).read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return cls.from_dict(data)


class Testbed:
    """Controls the lifecycle (up / down) of the emulated network testbed."""

    __test__ = False

    def __init__(self, config: ScenarioConfig, runner: Optional[CommandRunner] = None) -> None:
        self.config: ScenarioConfig = config
        self.runner: CommandRunner = runner or SystemCommandRunner()

    def up(self) -> None:
        """Provision the emulated testbed topology according to scenario config.

        Creates:
        1. Network namespaces.
        2. Loopback interfaces brought UP.
        3. Veth pairs moved into respective namespaces and assigned IPs.
        4. IPv4 forwarding enabled in the router namespace.
        5. Static routing entries configured.

        Failure handling:
            Raises RuntimeError if any command fails.
        """
        # 1. Create namespaces and bring up loopback
        for ns in self.config.namespaces.values():
            self.runner.run(["ip", "netns", "add", ns])
            self.runner.run(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"])

        # 2. Create veth pairs and move into namespaces
        for link in self.config.links.values():
            ep_a = link.endpoint_a
            ep_b = link.endpoint_b

            # Create veth pair in root namespace initially
            self.runner.run(
                ["ip", "link", "add", ep_a.interface, "type", "veth", "peer", "name", ep_b.interface]
            )

            # Move endpoints into respective namespaces
            self.runner.run(["ip", "link", "set", ep_a.interface, "netns", ep_a.namespace])
            self.runner.run(["ip", "link", "set", ep_b.interface, "netns", ep_b.namespace])

            # Configure IP addresses
            self.runner.run(
                ["ip", "netns", "exec", ep_a.namespace, "ip", "addr", "add", ep_a.ip, "dev", ep_a.interface]
            )
            self.runner.run(
                ["ip", "netns", "exec", ep_b.namespace, "ip", "addr", "add", ep_b.ip, "dev", ep_b.interface]
            )

            # Bring endpoints UP
            self.runner.run(
                ["ip", "netns", "exec", ep_a.namespace, "ip", "link", "set", ep_a.interface, "up"]
            )
            self.runner.run(
                ["ip", "netns", "exec", ep_b.namespace, "ip", "link", "set", ep_b.interface, "up"]
            )

        # 3. Enable IP forwarding in router namespace
        router_ns = self.config.namespaces.get("router")
        if router_ns:
            self.runner.run(
                ["ip", "netns", "exec", router_ns, "sysctl", "-w", "net.ipv4.ip_forward=1"]
            )

        # 4. Configure static routing
        for route in self.config.routes:
            self.runner.run(
                [
                    "ip",
                    "netns",
                    "exec",
                    route.namespace,
                    "ip",
                    "route",
                    "add",
                    route.destination,
                    "via",
                    route.gateway,
                ]
            )

    def down(self) -> None:
        """Tear down all namespaces and associated virtual links.

        Deleting the network namespaces automatically removes their virtual links.
        Does not raise errors if a namespace was already deleted.
        """
        for ns in self.config.namespaces.values():
            self.runner.run(["ip", "netns", "del", ns], check=False)
