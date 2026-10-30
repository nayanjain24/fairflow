"""fairflow.store - SQLite-backed persistent audit and experiment store.

Provides durable, queryable storage for:
- Telemetry records and raw file references
- Capacity estimates
- Classification outputs and decisions
- Proposed and validated QoS policies
- Enforcement state transitions and kernel verifications
- Canary decisions, rollback triggers, and recovery results
- Experiment runs, configurations, metrics, and error logs
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class AuditStore:
    """Thread-safe SQLite persistent store for FairFlow events, telemetry, and experiments."""

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        """Initialize the store with given path (or in-memory for testing)."""
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,  # Autocommit mode; we manage explicit transactions
        )
        self._conn.row_factory = sqlite3.Row

        # Performance and integrity pragmas
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    timestamp_wall REAL NOT NULL,
                    timestamp_mono REAL,
                    event_type TEXT NOT NULL,
                    run_id TEXT,
                    summary TEXT,
                    details_json TEXT NOT NULL
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp_wall);")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT UNIQUE NOT NULL,
                    timestamp_wall REAL NOT NULL,
                    timestamp_mono REAL NOT NULL,
                    window_duration_s REAL NOT NULL,
                    is_valid INTEGER NOT NULL,
                    rtt_ms REAL,
                    p95_latency_ms REAL,
                    jitter_ms REAL,
                    packet_loss_pct REAL,
                    throughput_mbps REAL,
                    flows_json TEXT,
                    raw_ref TEXT
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_time ON telemetry_records(timestamp_wall);")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS capacity_estimates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_wall REAL NOT NULL,
                    timestamp_mono REAL,
                    capacity_mbps REAL NOT NULL,
                    confidence REAL NOT NULL,
                    is_available INTEGER NOT NULL,
                    reason TEXT
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_id TEXT UNIQUE NOT NULL,
                    created_at REAL NOT NULL,
                    policy_type TEXT NOT NULL,
                    is_valid INTEGER NOT NULL,
                    validation_error TEXT,
                    classes_json TEXT NOT NULL,
                    contract_snapshot_json TEXT,
                    explanation TEXT
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_policies_id ON policies(policy_id);")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS enforcement_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transition_id TEXT UNIQUE NOT NULL,
                    timestamp_wall REAL NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    policy_id TEXT,
                    kernel_verified INTEGER,
                    verification_details TEXT,
                    canary_passed INTEGER,
                    rollback_occurred INTEGER,
                    rollback_reason TEXT,
                    details_json TEXT
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transitions_time ON enforcement_transitions(timestamp_wall);")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    run_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL,
                    config_json TEXT NOT NULL,
                    metrics_summary_json TEXT,
                    raw_artifacts_dir TEXT,
                    error_message TEXT
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_experiments_scenario ON experiments(scenario_id);")

    # -------------------------------------------------------------------------
    # Event Management
    # -------------------------------------------------------------------------

    def record_event(
        self,
        event_type: str,
        details: Dict[str, Any],
        summary: str = "",
        run_id: Optional[str] = None,
        timestamp_wall: Optional[float] = None,
        timestamp_mono: Optional[float] = None,
    ) -> str:
        """Insert an immutable audit event."""
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        now_wall = timestamp_wall if timestamp_wall is not None else time.time()
        now_mono = timestamp_mono if timestamp_mono is not None else time.monotonic()
        details_str = json.dumps(details, default=str)

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO events (event_id, timestamp_wall, timestamp_mono, event_type, run_id, summary, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (event_id, now_wall, now_mono, event_type, run_id, summary, details_str),
            )
        return event_id

    def query_events(
        self,
        event_type: Optional[str] = None,
        run_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query stored events with optional filtering and pagination."""
        query = "SELECT * FROM events"
        params: List[Any] = []
        conditions: List[str] = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock:
            cur = self._conn.execute(query, params)
            rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "event_id": r["event_id"],
                "timestamp_wall": r["timestamp_wall"],
                "timestamp_mono": r["timestamp_mono"],
                "event_type": r["event_type"],
                "run_id": r["run_id"],
                "summary": r["summary"],
                "details": json.loads(r["details_json"]),
            })
        return results

    # -------------------------------------------------------------------------
    # Telemetry Management
    # -------------------------------------------------------------------------

    def record_telemetry(
        self,
        snapshot: Any,
        raw_ref: Optional[str] = None,
    ) -> str:
        """Record a telemetry snapshot or dict representation."""
        record_id = f"tel_{uuid.uuid4().hex[:12]}"
        
        def _get(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        now_wall = _get(snapshot, "wall_clock_time") or _get(snapshot, "timestamp") or time.time()
        now_mono = _get(snapshot, "end_time_monotonic") or _get(snapshot, "timestamp_monotonic") or time.monotonic()
        duration = _get(snapshot, "window_duration_s", 2.0)
        is_valid = 1 if _get(snapshot, "is_valid", True) else 0

        # Extract metrics if available
        rtt = _get(snapshot, "rtt_ms")
        p95 = _get(snapshot, "p95_latency_ms")
        jitter = _get(snapshot, "jitter_ms")
        loss = _get(snapshot, "loss_pct")
        if loss is None:
            loss = _get(snapshot, "packet_loss_pct")
        throughput = _get(snapshot, "throughput_mbps")

        flows = _get(snapshot, "flows", [])
        if flows and hasattr(flows[0], "__dict__"):
            flows_data = [f.__dict__ for f in flows]
        elif isinstance(flows, list):
            flows_data = flows
        else:
            flows_data = []

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO telemetry_records (
                    record_id, timestamp_wall, timestamp_mono, window_duration_s, is_valid,
                    rtt_ms, p95_latency_ms, jitter_ms, packet_loss_pct, throughput_mbps,
                    flows_json, raw_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record_id, now_wall, now_mono, duration, is_valid,
                    rtt, p95, jitter, loss, throughput,
                    json.dumps(flows_data, default=str), raw_ref
                ),
            )
        return record_id

    def get_latest_telemetry(self) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent telemetry record."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM telemetry_records ORDER BY id DESC LIMIT 1;"
            )
            row = cur.fetchone()
        if not row:
            return None
        return self._format_telemetry_row(row)

    def get_telemetry_history(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieve telemetry records sorted from newest to oldest."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM telemetry_records ORDER BY id DESC LIMIT ? OFFSET ?;",
                (limit, offset),
            )
            rows = cur.fetchall()
        return [self._format_telemetry_row(r) for r in rows]

    def _format_telemetry_row(self, r: sqlite3.Row) -> Dict[str, Any]:
        return {
            "record_id": r["record_id"],
            "timestamp_wall": r["timestamp_wall"],
            "timestamp_mono": r["timestamp_mono"],
            "window_duration_s": r["window_duration_s"],
            "is_valid": bool(r["is_valid"]),
            "rtt_ms": r["rtt_ms"],
            "p95_latency_ms": r["p95_latency_ms"],
            "jitter_ms": r["jitter_ms"],
            "packet_loss_pct": r["packet_loss_pct"],
            "throughput_mbps": r["throughput_mbps"],
            "flows": json.loads(r["flows_json"]) if r["flows_json"] else [],
            "raw_ref": r["raw_ref"],
        }

    # -------------------------------------------------------------------------
    # Capacity Estimates
    # -------------------------------------------------------------------------

    def record_capacity_estimate(self, estimate: Any) -> int:
        """Store a capacity estimation point."""
        def _get(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        now_wall = _get(estimate, "wall_clock_time") or time.time()
        now_mono = _get(estimate, "timestamp_monotonic") or time.monotonic()
        cap_mbps = _get(estimate, "capacity_mbps", 0.0)
        conf = _get(estimate, "confidence", 1.0)
        is_avail = 1 if _get(estimate, "is_available", True) else 0
        reason = _get(estimate, "reason", "")


        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO capacity_estimates (
                    timestamp_wall, timestamp_mono, capacity_mbps, confidence, is_available, reason
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (now_wall, now_mono, cap_mbps, conf, is_avail, reason),
            )
            return cur.lastrowid or 0

    # -------------------------------------------------------------------------
    # Policy Storage
    # -------------------------------------------------------------------------

    def record_policy(
        self,
        policy_id: str,
        policy_type: str,
        is_valid: bool,
        classes: List[Dict[str, Any]],
        explanation: str = "",
        validation_error: Optional[str] = None,
        contract_snapshot: Optional[Dict[str, Any]] = None,
        created_at: Optional[float] = None,
    ) -> str:
        """Record a proposed or active QoS policy."""
        ts = created_at if created_at is not None else time.time()
        classes_str = json.dumps(classes, default=str)
        contract_str = json.dumps(contract_snapshot, default=str) if contract_snapshot else None

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO policies (
                    policy_id, created_at, policy_type, is_valid, validation_error,
                    classes_json, contract_snapshot_json, explanation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    policy_id, ts, policy_type, 1 if is_valid else 0,
                    validation_error, classes_str, contract_str, explanation
                ),
            )
        return policy_id

    def get_policy(self, policy_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a policy by ID."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM policies WHERE policy_id = ? LIMIT 1;", (policy_id,)
            )
            row = cur.fetchone()
        if not row:
            return None
        return self._format_policy_row(row)

    def list_policies(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List policies ordered newest to oldest."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM policies ORDER BY id DESC LIMIT ?;", (limit,)
            )
            rows = cur.fetchall()
        return [self._format_policy_row(r) for r in rows]

    def _format_policy_row(self, r: sqlite3.Row) -> Dict[str, Any]:
        return {
            "policy_id": r["policy_id"],
            "created_at": r["created_at"],
            "policy_type": r["policy_type"],
            "is_valid": bool(r["is_valid"]),
            "validation_error": r["validation_error"],
            "classes": json.loads(r["classes_json"]),
            "contract_snapshot": json.loads(r["contract_snapshot_json"]) if r["contract_snapshot_json"] else None,
            "explanation": r["explanation"],
        }

    # -------------------------------------------------------------------------
    # Transitions & Rollback History
    # -------------------------------------------------------------------------

    def record_transition(
        self,
        from_state: str,
        to_state: str,
        trigger: str,
        policy_id: Optional[str] = None,
        kernel_verified: bool = False,
        verification_details: Optional[str] = None,
        canary_passed: Optional[bool] = None,
        rollback_occurred: bool = False,
        rollback_reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timestamp_wall: Optional[float] = None,
    ) -> str:
        """Record an enforcement lifecycle state transition."""
        trans_id = f"trn_{uuid.uuid4().hex[:12]}"
        ts = timestamp_wall if timestamp_wall is not None else time.time()
        details_str = json.dumps(details or {}, default=str)

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO enforcement_transitions (
                    transition_id, timestamp_wall, from_state, to_state, trigger,
                    policy_id, kernel_verified, verification_details, canary_passed,
                    rollback_occurred, rollback_reason, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    trans_id, ts, from_state, to_state, trigger,
                    policy_id, 1 if kernel_verified else 0, verification_details,
                    1 if canary_passed else (0 if canary_passed is not None else None),
                    1 if rollback_occurred else 0, rollback_reason, details_str
                ),
            )
        return trans_id

    def get_rollback_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve all rollback events ordered newest to oldest."""
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT * FROM enforcement_transitions
                WHERE rollback_occurred = 1 OR to_state IN ('ROLLING_BACK', 'ROLLED_BACK')
                ORDER BY id DESC LIMIT ?;
                """,
                (limit,),
            )
            rows = cur.fetchall()

        results = []
        for r in rows:
            results.append({
                "transition_id": r["transition_id"],
                "timestamp_wall": r["timestamp_wall"],
                "from_state": r["from_state"],
                "to_state": r["to_state"],
                "trigger": r["trigger"],
                "policy_id": r["policy_id"],
                "rollback_reason": r["rollback_reason"],
                "kernel_verified": bool(r["kernel_verified"]),
                "details": json.loads(r["details_json"]) if r["details_json"] else {},
            })
        return results

    # -------------------------------------------------------------------------
    # Experiment Management
    # -------------------------------------------------------------------------

    def create_experiment(
        self,
        run_id: str,
        scenario_id: str,
        config: Dict[str, Any],
        start_time: Optional[float] = None,
    ) -> str:
        """Create a new experiment run entry."""
        ts = start_time if start_time is not None else time.time()
        cfg_str = json.dumps(config, default=str)

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO experiments (
                    run_id, scenario_id, status, start_time, config_json
                ) VALUES (?, ?, 'pending', ?, ?);
                """,
                (run_id, scenario_id, ts, cfg_str),
            )
        return run_id

    def update_experiment(
        self,
        run_id: str,
        status: str,
        metrics: Optional[Dict[str, Any]] = None,
        artifacts_dir: Optional[str] = None,
        error: Optional[str] = None,
        end_time: Optional[float] = None,
    ) -> None:
        """Update status, metrics, and completion time of an experiment."""
        fields: List[str] = ["status = ?"]
        params: List[Any] = [status]

        if metrics is not None:
            fields.append("metrics_summary_json = ?")
            params.append(json.dumps(metrics, default=str))
        if artifacts_dir is not None:
            fields.append("raw_artifacts_dir = ?")
            params.append(artifacts_dir)
        if error is not None:
            fields.append("error_message = ?")
            params.append(error)
        if end_time is not None or status in ("succeeded", "failed", "cancelled"):
            fields.append("end_time = ?")
            params.append(end_time if end_time is not None else time.time())

        params.append(run_id)
        query = f"UPDATE experiments SET {', '.join(fields)} WHERE run_id = ?;"

        with self._lock:
            self._conn.execute(query, params)

    def get_experiment(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Fetch details of a single experiment run."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM experiments WHERE run_id = ? LIMIT 1;", (run_id,)
            )
            row = cur.fetchone()
        if not row:
            return None
        return self._format_experiment_row(row)

    def list_experiments(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List experiments ordered newest to oldest."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM experiments ORDER BY start_time DESC LIMIT ?;", (limit,)
            )
            rows = cur.fetchall()
        return [self._format_experiment_row(r) for r in rows]

    def _format_experiment_row(self, r: sqlite3.Row) -> Dict[str, Any]:
        return {
            "run_id": r["run_id"],
            "scenario_id": r["scenario_id"],
            "status": r["status"],
            "start_time": r["start_time"],
            "end_time": r["end_time"],
            "config": json.loads(r["config_json"]) if r["config_json"] else {},
            "metrics_summary": json.loads(r["metrics_summary_json"]) if r["metrics_summary_json"] else None,
            "raw_artifacts_dir": r["raw_artifacts_dir"],
            "error_message": r["error_message"],
        }

    def clear_all(self) -> Dict[str, int]:
        """Clear all audit, telemetry, policy, transition, capacity, and experiment records."""
        counts: Dict[str, int] = {}
        tables = (
            "events",
            "telemetry_records",
            "capacity_estimates",
            "policies",
            "enforcement_transitions",
            "experiments",
        )
        with self._lock:
            for tbl in tables:
                cur = self._conn.execute(f"DELETE FROM {tbl};")
                counts[tbl] = cur.rowcount
        return counts

    def close(self) -> None:
        """Close SQLite database connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
