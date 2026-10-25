"""UDP Call Simulator and Analysis for FairFlow.

Simulates an interactive voice/video call session:
- Generates packets at 20 ms intervals using absolute-time scheduling (next_send += 0.02).
- Tags each packet with a monotonically increasing sequence number and time.monotonic_ns().
- Computes exact one-way delay (all namespaces share the host clock), RFC 3550 jitter, and packet loss.
"""

import csv
import socket
import struct
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

# Wire format: "!IQ" -> 4-byte unsigned int (seq), 8-byte unsigned long long (timestamp_ns)
HEADER_FORMAT = "!IQ"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
DEFAULT_PACKET_INTERVAL_S = 0.020  # 20 milliseconds (50 packets per second)
DEFAULT_PAYLOAD_SIZE = 160         # 160 bytes payload + 12 byte header = 172 bytes (typical G.711 / Opus)


@dataclass(frozen=True)
class UDPCallPacket:
    """Parsed packet data from the UDP call simulator."""

    seq: int
    send_time_ns: int
    payload: bytes


@dataclass(frozen=True)
class PacketRecord:
    """Log record of a successfully received call packet."""

    seq: int
    send_time_ns: int
    recv_time_ns: int

    @property
    def one_way_delay_ms(self) -> float:
        """One-way transit delay in milliseconds."""
        return (self.recv_time_ns - self.send_time_ns) / 1_000_000.0


def pack_call_packet(seq: int, send_time_ns: int, payload_len: int = DEFAULT_PAYLOAD_SIZE) -> bytes:
    """Serialize a call packet into binary bytes.

    Inputs:
        seq: Packet sequence number (uint32).
        send_time_ns: Monotonic timestamp in nanoseconds (uint64).
        payload_len: Number of padding bytes.
    Outputs:
        Binary bytes representing packet.
    """
    header = struct.pack(HEADER_FORMAT, seq, send_time_ns)
    padding = b"\x00" * payload_len
    return header + padding


def unpack_call_packet(data: bytes) -> UDPCallPacket:
    """Deserialize binary data into a UDPCallPacket.

    Inputs:
        data: Raw UDP packet bytes.
    Outputs:
        UDPCallPacket dataclass.
    Failure handling:
        Raises ValueError if data is shorter than the minimum header size.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Packet data too short: {len(data)} bytes, expected at least {HEADER_SIZE}")
    seq, send_time_ns = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    payload = data[HEADER_SIZE:]
    return UDPCallPacket(seq=seq, send_time_ns=send_time_ns, payload=payload)


def generate_packet_schedule(total_packets: int, interval_s: float = DEFAULT_PACKET_INTERVAL_S) -> List[float]:
    """Generate target absolute timestamps for packet transmissions.

    Inputs:
        total_packets: Number of packets to schedule.
        interval_s: Interval between consecutive transmissions (default 20ms).
    Outputs:
        List of target absolute offsets in seconds from t=0.
    """
    schedule: List[float] = []
    t = 0.0
    for _ in range(total_packets):
        schedule.append(t)
        t += interval_s
    return schedule


def compute_call_metrics(records: List[PacketRecord], total_sent: int) -> Dict[str, Any]:
    """Calculate latency, loss, and RFC 3550 interarrival jitter from packet records.

    Inputs:
        records: List of received PacketRecord objects.
        total_sent: Total number of packets transmitted by sender.
    Outputs:
        Dictionary containing:
        - packets_sent
        - packets_received
        - loss_count
        - loss_pct
        - p50_delay_ms
        - p99_delay_ms
        - mean_delay_ms
        - jitter_ms (RFC 3550)
    """
    num_received = len(records)
    loss_count = max(0, total_sent - num_received)
    loss_pct = (loss_count / total_sent * 100.0) if total_sent > 0 else 0.0

    if not records:
        return {
            "packets_sent": total_sent,
            "packets_received": 0,
            "loss_count": loss_count,
            "loss_pct": loss_pct,
            "p50_delay_ms": 0.0,
            "p99_delay_ms": 0.0,
            "mean_delay_ms": 0.0,
            "jitter_ms": 0.0,
        }

    delays = sorted(r.one_way_delay_ms for r in records)
    mean_delay = sum(delays) / len(delays)

    # Percentiles
    p50_idx = int(0.50 * (len(delays) - 1))
    p99_idx = int(0.99 * (len(delays) - 1))
    p50_delay = delays[p50_idx]
    p99_delay = delays[p99_idx]

    # RFC 3550 Jitter calculation:
    # D(i, j) = (R_j - S_j) - (R_i - S_i)
    # J = J + (|D| - J) / 16
    jitter_ms = 0.0
    for i in range(1, len(records)):
        prev = records[i - 1]
        curr = records[i]
        d_transit = curr.one_way_delay_ms - prev.one_way_delay_ms
        jitter_ms += (abs(d_transit) - jitter_ms) / 16.0

    return {
        "packets_sent": total_sent,
        "packets_received": num_received,
        "loss_count": loss_count,
        "loss_pct": round(loss_pct, 4),
        "p50_delay_ms": round(p50_delay, 3),
        "p99_delay_ms": round(p99_delay, 3),
        "mean_delay_ms": round(mean_delay, 3),
        "jitter_ms": round(jitter_ms, 3),
    }


class UDPCallSender:
    """Sender for the UDP call simulator using absolute-time scheduling."""

    def __init__(
        self,
        dest_host: str,
        dest_port: int,
        interval_s: float = DEFAULT_PACKET_INTERVAL_S,
        payload_len: int = DEFAULT_PAYLOAD_SIZE,
    ) -> None:
        self.dest_host = dest_host
        self.dest_port = dest_port
        self.interval_s = interval_s
        self.payload_len = payload_len

    def run(self, duration_s: float) -> int:
        """Transmit UDP call packets at regular intervals for the given duration.

        Uses absolute time stepping (next_send += interval_s) to avoid cumulative drift.

        Inputs:
            duration_s: Duration of the run in seconds.
        Outputs:
            Total number of packets transmitted.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        seq = 0
        t_start = time.monotonic()
        t_end = t_start + duration_s
        next_send = t_start

        try:
            while next_send < t_end:
                now = time.monotonic()
                sleep_time = next_send - now
                if sleep_time > 0:
                    time.sleep(sleep_time)

                send_time_ns = time.monotonic_ns()
                packet = pack_call_packet(seq=seq, send_time_ns=send_time_ns, payload_len=self.payload_len)
                sock.sendto(packet, (self.dest_host, self.dest_port))
                seq += 1
                next_send += self.interval_s
        finally:
            sock.close()

        return seq


class UDPCallReceiver:
    """Receiver for the UDP call simulator logging packet arrivals."""

    def __init__(self, bind_host: str, bind_port: int) -> None:
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.records: List[PacketRecord] = []

    def run(self, duration_s: float, timeout_s: float = 2.0) -> List[PacketRecord]:
        """Listen on the specified UDP port and log all received call packets.

        Inputs:
            duration_s: Expected active transmission duration in seconds.
            timeout_s: Additional grace period in seconds to capture in-flight packets.
        Outputs:
            List of PacketRecord objects.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.bind_host, self.bind_port))
        sock.settimeout(0.5)

        self.records = []
        t_start = time.monotonic()
        t_stop = t_start + duration_s + timeout_s

        try:
            while time.monotonic() < t_stop:
                try:
                    data, _ = sock.recvfrom(2048)
                    recv_time_ns = time.monotonic_ns()
                    packet = unpack_call_packet(data)
                    self.records.append(
                        PacketRecord(
                            seq=packet.seq,
                            send_time_ns=packet.send_time_ns,
                            recv_time_ns=recv_time_ns,
                        )
                    )
                except socket.timeout:
                    continue
        finally:
            sock.close()

        return self.records

    def write_csv(self, output_path: str) -> None:
        """Write raw received packet records to a CSV file.

        Inputs:
            output_path: Destination path for the CSV.
        """
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["seq", "send_time_ns", "recv_time_ns", "one_way_delay_ms"])
            for r in self.records:
                writer.writerow([r.seq, r.send_time_ns, r.recv_time_ns, round(r.one_way_delay_ms, 4)])


def parse_csv_records(csv_path: str) -> List[PacketRecord]:
    """Parse PacketRecord list from an existing raw packet CSV."""
    records: List[PacketRecord] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(
                PacketRecord(
                    seq=int(row["seq"]),
                    send_time_ns=int(row["send_time_ns"]),
                    recv_time_ns=int(row["recv_time_ns"]),
                )
            )
    return records


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="FairFlow UDP Call Simulator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Receiver subparser
    recv_p = subparsers.add_parser("recv", help="Run UDP call receiver")
    recv_p.add_argument("--bind", default="0.0.0.0", help="Bind IP address")
    recv_p.add_argument("--port", type=int, default=5005, help="Bind UDP port")
    recv_p.add_argument("--duration", type=float, default=60.0, help="Expected duration in seconds")
    recv_p.add_argument("--csv", required=True, help="Path to write raw packet CSV")

    # Sender subparser
    send_p = subparsers.add_parser("send", help="Run UDP call sender")
    send_p.add_argument("--dest", required=True, help="Destination IP address")
    send_p.add_argument("--port", type=int, default=5005, help="Destination UDP port")
    send_p.add_argument("--duration", type=float, default=60.0, help="Duration in seconds")
    send_p.add_argument("--count-out", default="", help="Optional file to write sent packet count")

    # Summary subparser
    sum_p = subparsers.add_parser("summary", help="Analyze packet CSV and compute metrics")
    sum_p.add_argument("--csv", required=True, help="Path to raw packet CSV")
    sum_p.add_argument("--total-sent", type=int, required=True, help="Total packets transmitted")
    sum_p.add_argument("--out", default="", help="Optional path to output summary JSON")

    args = parser.parse_args()

    if args.command == "recv":
        receiver = UDPCallReceiver(bind_host=args.bind, bind_port=args.port)
        records = receiver.run(duration_s=args.duration)
        receiver.write_csv(args.csv)
        print(f"Receiver finished. Logged {len(records)} packets to {args.csv}")

    elif args.command == "send":
        sender = UDPCallSender(dest_host=args.dest, dest_port=args.port)
        total = sender.run(duration_s=args.duration)
        print(f"Sender finished. Transmitted {total} packets.")
        if args.count_out:
            with open(args.count_out, "w", encoding="utf-8") as f:
                f.write(str(total))

    elif args.command == "summary":
        recs = parse_csv_records(args.csv)
        metrics = compute_call_metrics(records=recs, total_sent=args.total_sent)

        print("\n=== Idle Noise Floor Call Metrics Summary ===")
        print(f"Packets Sent:     {metrics['packets_sent']}")
        print(f"Packets Received: {metrics['packets_received']}")
        print(f"Packets Lost:     {metrics['loss_count']} ({metrics['loss_pct']}%)")
        print(f"p50 Delay:        {metrics['p50_delay_ms']} ms")
        print(f"p99 Delay:        {metrics['p99_delay_ms']} ms")
        print(f"Mean Delay:       {metrics['mean_delay_ms']} ms")
        print(f"RFC 3550 Jitter:  {metrics['jitter_ms']} ms")

        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(metrics, f, indent=2)
            print(f"Saved summary metrics to {args.out}")
