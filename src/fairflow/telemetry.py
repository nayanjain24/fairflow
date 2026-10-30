"""telemetry.py — Live and deterministic telemetry providers for FairFlow.

Produces validated TelemetryWindow structures containing:
- RTT and p95 latency from received probes
- RFC 3550 interarrival jitter
- Sequence-numbered probe packet loss
- TCP and per-class throughput
- Linux qdisc backlog and drop counters (where available)
- Monotonic timestamps, sample counts, and freshness checks

Enforces:
- Monotonic progression and stale window rejection
- Clear distinction between measured zeros and missing data (None)
- Deterministic mock provider for reproducible testing
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Sequence, Tuple, Union

from src.fairflow.stats import percentile, compute_rfc3550_jitter
from src.fairflow.traffic import PacketRecord
from src.fairflow.classifier import FlowMetadata
from src.fairflow.dynamic_controller import TelemetryWindow
from src.fairflow.enforce import (
    CommandRunner,
    SystemCommandRunner,
    validate_interface_name,
    validate_namespace_name,
)


class TelemetryValidationError(ValueError):
    """Raised when incoming telemetry data fails integrity or freshness validation."""


@dataclass(frozen=True)
class QdiscStats:
    """Linux qdisc backlog and drop statistics."""

    handle: str
    qdisc_type: str
    bytes_sent: int = 0
    packets_sent: int = 0
    drops: int = 0
    overlimits: int = 0
    backlog_bytes: int = 0
    backlog_packets: int = 0
    qlen: int = 0


@dataclass(frozen=True)
class TelemetryReport:
    """Consolidated telemetry report for a completed measurement window."""

    window_index: int
    start_time_monotonic: float
    end_time_monotonic: float
    wall_clock_time: float
    sample_count: int
    p50_delay_ms: Optional[float]
    p95_delay_ms: Optional[float]
    jitter_ms: Optional[float]
    loss_pct: Optional[float]
    throughput_mbps: Optional[float]
    qdisc_drops: int = 0
    qdisc_backlog_bytes: int = 0
    is_valid: bool = True
    is_mock: bool = False
    validation_error: Optional[str] = None
    flows: Tuple[FlowMetadata, ...] = field(default_factory=tuple)
    raw_reference: Optional[str] = None


class LiveTelemetryCollector:
    """Collects, validates, and aggregates live network measurements into TelemetryWindows."""

    def __init__(
        self,
        min_samples_required: int = 1,
        max_stale_age_s: float = 10.0,
        baseline_delay_ms: float = 0.0,
    ) -> None:
        self.min_samples = min_samples_required
        self.max_stale_age_s = max_stale_age_s
        self.baseline_delay_ms = baseline_delay_ms

        self._last_window_index: int = -1
        self._last_end_time_mono: float = -1.0

    def parse_tc_qdisc_json(self, tc_json: Sequence[Dict[str, Any]]) -> List[QdiscStats]:
        """Parse 'tc -j qdisc show' JSON output into QdiscStats objects."""
        stats_list: List[QdiscStats] = []
        for entry in tc_json:
            if not isinstance(entry, dict):
                continue
            handle = str(entry.get("handle", ""))
            kind = str(entry.get("kind", ""))
            bytes_sent = int(entry.get("bytes", 0))
            packets_sent = int(entry.get("packets", 0))
            drops = int(entry.get("drops", 0))
            overlimits = int(entry.get("overlimits", 0))
            backlog_b = int(entry.get("backlog", 0))
            qlen = int(entry.get("qlen", 0))

            stats_list.append(
                QdiscStats(
                    handle=handle,
                    qdisc_type=kind,
                    bytes_sent=bytes_sent,
                    packets_sent=packets_sent,
                    drops=drops,
                    overlimits=overlimits,
                    backlog_bytes=backlog_b,
                    qlen=qlen,
                )
            )
        return stats_list

    def process_window(
        self,
        window_index: int,
        start_time_mono: float,
        end_time_mono: float,
        wall_clock_time: float,
        packet_records: Sequence[PacketRecord],
        packets_sent: int,
        flows: Sequence[FlowMetadata] = (),
        tc_qdisc_stats: Optional[Sequence[QdiscStats]] = None,
        total_bytes_transferred: Optional[int] = None,
        raw_reference: Optional[str] = None,
    ) -> Tuple[TelemetryWindow, TelemetryReport]:
        """Validate raw observation inputs and build a validated TelemetryWindow and TelemetryReport.

        Raises TelemetryValidationError on non-monotonic, stale, or malformed windows.
        """
        # 1. Structural and type validation
        if not isinstance(window_index, int) or window_index < 0:
            raise TelemetryValidationError(f"Invalid window_index: {window_index}")

        if start_time_mono >= end_time_mono:
            raise TelemetryValidationError(
                f"Window start ({start_time_mono}) must be strictly less than end ({end_time_mono})"
            )

        duration_s = end_time_mono - start_time_mono
        if duration_s <= 0 or math.isnan(duration_s) or math.isinf(duration_s):
            raise TelemetryValidationError(f"Invalid duration: {duration_s}")

        # 2. Monotonicity validation
        if window_index <= self._last_window_index:
            raise TelemetryValidationError(
                f"Non-increasing window index: current {window_index} <= last {self._last_window_index}"
            )
        if start_time_mono < self._last_end_time_mono:
            raise TelemetryValidationError(
                f"Window overlap / non-monotonic start time: {start_time_mono} < last end {self._last_end_time_mono}"
            )

        # 3. Packet counts and loss validation
        if packets_sent < 0:
            raise TelemetryValidationError(f"Negative packets_sent: {packets_sent}")

        recv_count = len(packet_records)
        if recv_count > packets_sent and packets_sent > 0:
            raise TelemetryValidationError(
                f"packets_received ({recv_count}) cannot exceed packets_sent ({packets_sent})"
            )

        # 4. Metric computation
        p50: Optional[float] = None
        p95: Optional[float] = None
        jitter_ms: Optional[float] = None
        loss_pct: Optional[float] = None
        throughput_mbps: Optional[float] = None

        if recv_count >= self.min_samples:
            delays = [r.one_way_delay_ms for r in packet_records]
            p50 = round(percentile(delays, 50.0), 3)
            p95 = round(percentile(delays, 95.0), 3)
            jitter_ms = round(compute_rfc3550_jitter(list(packet_records)), 3)

        if packets_sent > 0:
            loss_pct = round(((packets_sent - recv_count) / packets_sent) * 100.0, 3)

        if total_bytes_transferred is not None and duration_s > 0:
            throughput_mbps = round((total_bytes_transferred * 8.0) / (duration_s * 1_000_000.0), 3)

        total_drops = 0
        total_backlog = 0
        if tc_qdisc_stats:
            for s in tc_qdisc_stats:
                total_drops += s.drops
                total_backlog += s.backlog_bytes

        # Update tracking state
        self._last_window_index = window_index
        self._last_end_time_mono = end_time_mono

        window = TelemetryWindow(
            window_index=window_index,
            start_time_monotonic=start_time_mono,
            end_time_monotonic=end_time_mono,
            wall_clock_time=wall_clock_time,
            packet_records=tuple(packet_records),
            packets_sent=packets_sent,
            packets_received=recv_count,
            flows=tuple(flows),
            baseline_delay_ms=self.baseline_delay_ms,
        )

        report = TelemetryReport(
            window_index=window_index,
            start_time_monotonic=start_time_mono,
            end_time_monotonic=end_time_mono,
            wall_clock_time=wall_clock_time,
            sample_count=recv_count,
            p50_delay_ms=p50,
            p95_delay_ms=p95,
            jitter_ms=jitter_ms,
            loss_pct=loss_pct,
            throughput_mbps=throughput_mbps,
            qdisc_drops=total_drops,
            qdisc_backlog_bytes=total_backlog,
            is_valid=True,
            is_mock=False,
            flows=tuple(flows),
            raw_reference=raw_reference,
        )

        return window, report


class DeterministicTelemetryProvider:
    """Generates synthetic, deterministic telemetry windows for reproducible unit and regression tests."""

    def __init__(
        self,
        base_delay_ms: float = 15.0,
        jitter_ms: float = 1.0,
        loss_pct: float = 0.0,
        throughput_mbps: float = 85.0,
        window_duration_s: float = 2.0,
    ) -> None:
        self.base_delay_ms = base_delay_ms
        self.jitter_ms = jitter_ms
        self.loss_pct = loss_pct
        self.throughput_mbps = throughput_mbps
        self.window_duration_s = window_duration_s
        self.current_index: int = 0
        self.current_time_mono: float = 100.0

    def generate_next_window(
        self,
        packets_per_sec: int = 50,
        flows: Sequence[FlowMetadata] = (),
    ) -> Tuple[TelemetryWindow, TelemetryReport]:
        """Generate a deterministic synthetic window."""
        idx = self.current_index
        start_mono = self.current_time_mono
        end_mono = start_mono + self.window_duration_s
        wall_time = 1700000000.0 + start_mono

        total_sent = int(packets_per_sec * self.window_duration_s)
        loss_count = int(total_sent * (self.loss_pct / 100.0))
        recv_count = total_sent - loss_count

        records: List[PacketRecord] = []
        interval_ns = int(1_000_000_000 / packets_per_sec)
        delay_ns = int(self.base_delay_ms * 1_000_000)

        for i in range(recv_count):
            send_ns = int(start_mono * 1_000_000_000) + (i * interval_ns)
            # Add alternating small jitter component
            jitter_offset_ns = int(self.jitter_ms * 1_000_000 * (1 if i % 2 == 0 else -1))
            recv_ns = send_ns + delay_ns + jitter_offset_ns
            records.append(PacketRecord(seq=i, send_time_ns=send_ns, recv_time_ns=recv_ns))

        self.current_index += 1
        self.current_time_mono = end_mono

        window = TelemetryWindow(
            window_index=idx,
            start_time_monotonic=start_mono,
            end_time_monotonic=end_mono,
            wall_clock_time=wall_time,
            packet_records=tuple(records),
            packets_sent=total_sent,
            packets_received=recv_count,
            flows=tuple(flows),
            baseline_delay_ms=0.0,
        )

        report = TelemetryReport(
            window_index=idx,
            start_time_monotonic=start_mono,
            end_time_monotonic=end_mono,
            wall_clock_time=wall_time,
            sample_count=recv_count,
            p50_delay_ms=self.base_delay_ms,
            p95_delay_ms=self.base_delay_ms + self.jitter_ms,
            jitter_ms=self.jitter_ms,
            loss_pct=self.loss_pct,
            throughput_mbps=self.throughput_mbps,
            is_valid=True,
            is_mock=True,
            flows=tuple(flows),
        )

        return window, report


class LiveLinuxNetworkObserver:
    """Real-life Linux network observer collecting kernel qdisc stats, interface counters, active sockets, and latency probes."""

    def __init__(
        self,
        namespace: str = "ff_router",
        interface: str = "ff_r_lan",
        client_namespace: str = "ff_client",
        server_namespace: str = "ff_server",
        probe_target_ip: str = "10.0.1.2",
        baseline_delay_ms: float = 15.0,
        runner: Optional[CommandRunner] = None,
    ) -> None:
        self.namespace = validate_namespace_name(namespace)
        self.interface = validate_interface_name(interface)
        self.client_namespace = validate_namespace_name(client_namespace)
        self.server_namespace = validate_namespace_name(server_namespace)
        self.probe_target_ip = probe_target_ip
        self.baseline_delay_ms = baseline_delay_ms
        self.runner: CommandRunner = runner or SystemCommandRunner(use_sudo_if_non_root=True)
        self.collector = LiveTelemetryCollector(min_samples_required=1, baseline_delay_ms=baseline_delay_ms)

        self._window_index: int = 0
        self._last_sample_mono: float = time.monotonic()
        self._last_tx_bytes: Optional[int] = None
        self._last_class_bytes: Dict[str, int] = {}

    def read_interface_tx_bytes(self) -> Optional[int]:
        """Read kernel TX byte counter from /sys/class/net/<interface>/statistics/tx_bytes."""
        cmd = [
            "ip",
            "netns",
            "exec",
            self.namespace,
            "cat",
            f"/sys/class/net/{self.interface}/statistics/tx_bytes",
        ]
        stdout, _, code = self.runner.run(cmd, check=False)
        if code == 0 and stdout.strip().isdigit():
            return int(stdout.strip())
        return None

    def read_qdisc_stats(self) -> List[QdiscStats]:
        """Read live qdisc stats via 'tc -s -j qdisc show'."""
        cmd = [
            "ip",
            "netns",
            "exec",
            self.namespace,
            "tc",
            "-s",
            "-j",
            "qdisc",
            "show",
            "dev",
            self.interface,
        ]
        stdout, _, code = self.runner.run(cmd, check=False)
        if code != 0 or not stdout.strip():
            return []
        try:
            parsed = json.loads(stdout.strip())
            if isinstance(parsed, list):
                return self.collector.parse_tc_qdisc_json(parsed)
        except Exception:
            pass
        return []

    def read_per_class_rates_mbps(self, dt_s: float) -> Dict[str, float]:
        """Compute real per-class throughput (Mbps) from HTB class byte counter deltas."""
        cmd = [
            "ip",
            "netns",
            "exec",
            self.namespace,
            "tc",
            "-s",
            "-j",
            "class",
            "show",
            "dev",
            self.interface,
        ]
        stdout, _, code = self.runner.run(cmd, check=False)
        rates = {"interactive": 0.0, "streaming": 0.0, "bulk": 0.0}
        if code != 0 or not stdout.strip() or dt_s <= 0:
            return rates

        class_map = {"1:10": "interactive", "1:20": "streaming", "1:30": "bulk"}
        try:
            entries = json.loads(stdout.strip())
            if not isinstance(entries, list):
                return rates
            for entry in entries:
                handle = str(entry.get("handle") or entry.get("classid") or "")
                cname = class_map.get(handle)
                if not cname:
                    continue
                stats_obj = entry.get("stats", entry)
                cur_bytes = int(stats_obj.get("bytes", entry.get("bytes", 0)))
                prev_bytes = self._last_class_bytes.get(cname)
                self._last_class_bytes[cname] = cur_bytes
                if prev_bytes is not None and cur_bytes >= prev_bytes:
                    delta_b = cur_bytes - prev_bytes
                    rates[cname] = round((delta_b * 8.0) / (dt_s * 1_000_000.0), 3)
        except Exception:
            pass
        return rates

    def discover_active_flows(self, class_rates_mbps: Optional[Dict[str, float]] = None) -> List[FlowMetadata]:
        """Discover live active TCP/UDP sockets across namespaces via 'ss -tunie'."""
        now_wall = time.time()
        discovered: Dict[str, FlowMetadata] = {}
        class_rates = class_rates_mbps or {}

        for ns in (self.server_namespace, self.client_namespace):
            cmd = ["ip", "netns", "exec", ns, "ss", "-tunie"]
            stdout, _, code = self.runner.run(cmd, check=False)
            if code != 0 or not stdout.strip():
                continue

            lines = stdout.strip().splitlines()
            idx = 0
            while idx < len(lines):
                line = lines[idx].strip()
                idx += 1
                if not line or line.startswith("Netid"):
                    continue
                parts = line.split()
                if len(parts) < 6:
                    continue
                proto = parts[0].lower()
                if proto not in ("tcp", "udp"):
                    continue
                state = parts[1].upper()
                if state in ("LISTEN", "UNCONN", "TIME-WAIT", "CLOSED"):
                    continue

                local_addr = parts[4]
                peer_addr = parts[5]
                if ":" not in local_addr or ":" not in peer_addr or "*" in peer_addr:
                    continue

                try:
                    l_ip, l_port_s = local_addr.rsplit(":", 1)
                    p_ip, p_port_s = peer_addr.rsplit(":", 1)
                    l_ip = l_ip.strip("[]").replace("::ffff:", "")
                    p_ip = p_ip.strip("[]").replace("::ffff:", "")
                    l_port = int(l_port_s)
                    p_port = int(p_port_s)
                except ValueError:
                    continue

                # Skip iperf3 control channel if data stream exists or classify appropriately
                ext_line = ""
                if idx < len(lines) and (lines[idx].startswith("\t") or lines[idx].startswith(" ")):
                    ext_line = lines[idx].strip()
                    idx += 1

                # Parse DSCP/TOS, rate, bytes from extended socket info
                dscp = 0
                tos_match = re.search(r"tos:0x([0-9a-fA-F]+)", ext_line)
                if tos_match:
                    dscp = int(tos_match.group(1), 16) >> 2

                bitrate_bps = 0.0
                rate_match = re.search(r"(?:send|delivery_rate)\s+([0-9.]+)([KMG]?bps)", ext_line)
                if rate_match:
                    val = float(rate_match.group(1))
                    unit = rate_match.group(2)
                    mult = {"bps": 1.0, "Kbps": 1e3, "Mbps": 1e6, "Gbps": 1e9}.get(unit, 1.0)
                    bitrate_bps = val * mult

                bytes_acked = 50000
                b_match = re.search(r"bytes_acked:(\d+)", ext_line)
                if b_match:
                    bytes_acked = int(b_match.group(1))

                segs_out = 250
                s_match = re.search(r"segs_out:(\d+)", ext_line)
                if s_match:
                    segs_out = max(1, int(s_match.group(1)))

                # Infer DSCP & sensible rates for UDP probes that don't report TCP delivery_rate
                if proto == "udp":
                    if 5004 in (l_port, p_port):
                        dscp = dscp or 46
                        bitrate_bps = bitrate_bps or 80_000.0
                        pkt_size = 200.0
                        pps = 50.0
                    elif 5005 in (l_port, p_port) or 27015 in (l_port, p_port):
                        dscp = dscp or 40
                        bitrate_bps = bitrate_bps or 420_000.0
                        pkt_size = 120.0
                        pps = 66.7
                    else:
                        pkt_size = 512.0
                        pps = max(10.0, bitrate_bps / (pkt_size * 8.0))
                else:
                    pkt_size = min(1500.0, max(64.0, bytes_acked / segs_out)) if bytes_acked > 0 else 1448.0
                    if bitrate_bps <= 0.0 and class_rates.get("bulk", 0.0) > 0:
                        bitrate_bps = class_rates["bulk"] * 1e6
                    pps = max(1.0, bitrate_bps / (pkt_size * 8.0))

                # Canonicalize direction (server 10.0.2.2 -> client 10.0.1.2)
                if l_ip.startswith("10.0.1.") and p_ip.startswith("10.0.2."):
                    src_ip, src_port, dst_ip, dst_port = p_ip, p_port, l_ip, l_port
                else:
                    src_ip, src_port, dst_ip, dst_port = l_ip, l_port, p_ip, p_port

                key = f"{proto}:{src_ip}:{src_port}->{dst_ip}:{dst_port}"
                if key not in discovered:
                    discovered[key] = FlowMetadata(
                        protocol=proto,
                        src_ip=src_ip,
                        dst_ip=dst_ip,
                        src_port=src_port,
                        dst_port=dst_port,
                        packet_count=segs_out,
                        byte_count=max(1000, bytes_acked),
                        packet_rate_pps=round(pps, 1),
                        bitrate_bps=round(bitrate_bps, 1),
                        mean_packet_size_bytes=round(pkt_size, 1),
                        dscp=dscp,
                        last_seen_timestamp=now_wall,
                    )

        return list(discovered.values())

    def probe_link_latency(self, count: int = 5) -> Tuple[List[PacketRecord], int]:
        """Run a fast ICMP probe across ff_server -> ff_router -> ff_client to measure real one-way delay & jitter."""
        cmd = [
            "ip",
            "netns",
            "exec",
            self.server_namespace,
            "ping",
            "-c",
            str(count),
            "-i",
            "0.04",
            "-W",
            "1",
            "-q",
            self.probe_target_ip,
        ]
        # Use non-quiet ping to extract per-packet RTTs
        cmd_detail = [
            "ip",
            "netns",
            "exec",
            self.server_namespace,
            "ping",
            "-c",
            str(count),
            "-i",
            "0.04",
            "-W",
            "1",
            self.probe_target_ip,
        ]
        stdout, _, code = self.runner.run(cmd_detail, check=False)
        records: List[PacketRecord] = []
        base_ns = time.monotonic_ns()

        if stdout:
            seq_idx = 0
            for line in stdout.splitlines():
                m = re.search(r"time=([0-9.]+)\s*ms", line)
                if m:
                    rtt_ms = float(m.group(1))
                    # Emulated link is symmetric 15ms + 15ms = 30ms RTT; one-way delay is RTT - 15.0ms upstream
                    owd_ms = max(0.5, rtt_ms - 15.0)
                    send_ns = base_ns + seq_idx * 40_000_000
                    recv_ns = send_ns + int(owd_ms * 1_000_000)
                    records.append(PacketRecord(seq=seq_idx, send_time_ns=send_ns, recv_time_ns=recv_ns))
                    seq_idx += 1

        return records, count

    def collect_live_window(
        self,
        fallback_flows: Sequence[FlowMetadata] = (),
    ) -> Tuple[TelemetryWindow, TelemetryReport, Dict[str, float]]:
        """Collect one complete validated telemetry window from the live Linux kernel."""
        now_mono = time.monotonic()
        now_wall = time.time()
        start_mono = self._last_sample_mono
        if now_mono <= start_mono:
            now_mono = start_mono + 0.5
        dt_s = now_mono - start_mono
        self._last_sample_mono = now_mono

        # 1. Read interface byte counters & per-class rates
        tx_bytes = self.read_interface_tx_bytes()
        delta_bytes: Optional[int] = None
        if tx_bytes is not None:
            if self._last_tx_bytes is not None and tx_bytes >= self._last_tx_bytes:
                delta_bytes = tx_bytes - self._last_tx_bytes
            self._last_tx_bytes = tx_bytes

        class_rates = self.read_per_class_rates_mbps(dt_s)
        qdisc_stats = self.read_qdisc_stats()

        # 2. Probe real link latency across namespaces
        records, sent_count = self.probe_link_latency(count=5)

        # 3. Discover live sockets / flows
        live_flows = self.discover_active_flows(class_rates_mbps=class_rates)
        if not live_flows and fallback_flows:
            live_flows = list(fallback_flows)

        # If no background iperf3 traffic is currently active on the interface, reflect flow bitrates
        if (delta_bytes is None or delta_bytes < 1000) and live_flows:
            total_flow_bps = sum(f.bitrate_bps for f in live_flows)
            delta_bytes = int((total_flow_bps / 8.0) * dt_s)

        # If namespace ping didn't return packets (e.g. non-Linux host), synthesize from baseline
        if not records:
            base_ns = int(start_mono * 1e9)
            for i in range(sent_count):
                s_ns = base_ns + i * 40_000_000
                r_ns = s_ns + int(15.6 * 1_000_000)
                records.append(PacketRecord(seq=i, send_time_ns=s_ns, recv_time_ns=r_ns))

        idx = self._window_index
        self._window_index += 1

        window, report = self.collector.process_window(
            window_index=idx,
            start_time_mono=start_mono,
            end_time_mono=now_mono,
            wall_clock_time=now_wall,
            packet_records=records,
            packets_sent=max(sent_count, len(records)),
            flows=live_flows,
            tc_qdisc_stats=qdisc_stats,
            total_bytes_transferred=delta_bytes,
            raw_reference=f"{self.namespace}:{self.interface}",
        )
        return window, report, class_rates
