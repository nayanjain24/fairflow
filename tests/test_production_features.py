"""Unit tests for FairFlow production hardening features."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.fairflow.api import create_app
from src.fairflow.contract import (
    compute_file_sha256,
    get_contract_integrity,
    verify_contract_sha256,
)
from src.fairflow.controller import PolicyEngine
from src.fairflow.dynamic_controller import (
    AdaptiveCapacityEstimator,
    DynamicController,
    TelemetryWindow,
)
from src.fairflow.enforce import MockCommandRunner, TCDriver
from src.fairflow.enforcement_coordinator import EnforcementCoordinator
from src.fairflow.policy import ClassPolicy, Policy
from src.fairflow.store import AuditStore
from src.fairflow.traffic import PacketRecord


def _sample_policy(cap_mbps: float = 95.0) -> Policy:
    return Policy(
        link_capacity_mbps=cap_mbps,
        classes={
            "interactive": ClassPolicy(
                rate_floor_mbps=2.0,
                rate_ceiling_mbps=cap_mbps,
                priority=1,
                leaf_qdisc="fq_codel",
            ),
            "streaming": ClassPolicy(
                rate_floor_mbps=8.0,
                rate_ceiling_mbps=cap_mbps,
                priority=2,
                leaf_qdisc="fq_codel",
            ),
            "bulk": ClassPolicy(
                rate_floor_mbps=2.0,
                rate_ceiling_mbps=cap_mbps,
                priority=3,
                leaf_qdisc="fq_codel",
            ),
        },
    )


def test_contract_sha256_integrity_and_mismatch(tmp_path: Path) -> None:
    status = get_contract_integrity(REPO_ROOT / "contract.yaml", REPO_ROOT / "contract.sha256")
    assert status["verified"] is True
    assert status["sha256"] is not None
    assert len(status["sha256"]) == 64

    bad_sha = tmp_path / "bad.sha256"
    bad_sha.write_text("0" * 64, encoding="utf-8")
    bad_status = get_contract_integrity(REPO_ROOT / "contract.yaml", bad_sha)
    assert bad_status["verified"] is False
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        verify_contract_sha256(REPO_ROOT / "contract.yaml", bad_sha)

    assert compute_file_sha256(REPO_ROOT / "contract.yaml") == status["sha256"]


def test_router_script_export_and_live_safety_invariant() -> None:
    pol = _sample_policy(95.0)
    sha = "deadbeef" * 8

    linux_script = TCDriver.export_router_script(
        pol, target="linux_tc", wan_iface="eth0", lan_iface="br-lan", contract_sha256=sha
    )
    assert "#!/usr/bin/env bash" in linux_script
    assert sha in linux_script
    assert 'LAN_IF="br-lan"' in linux_script
    assert "tc class replace" in linux_script
    assert "fq_codel" in linux_script

    owrt_script = TCDriver.export_router_script(
        pol, target="openwrt_sqm", wan_iface="pppoe-wan", lan_iface="br-lan", contract_sha256=sha
    )
    assert "uci set sqm.fairflow_pilot=queue" in owrt_script
    assert "pppoe-wan" in owrt_script
    assert sha in owrt_script

    with pytest.raises(ValueError):
        TCDriver.export_router_script(pol, target="linux_tc", wan_iface="eth0;rm -rf /")

    # Live kernel driver invariant remains strictly scoped to ^ff_
    driver = TCDriver(runner=MockCommandRunner(), dry_run=True)
    with pytest.raises(ValueError, match="ff_"):
        driver.apply("eth0", "ff_router", pol)


def test_controller_overhead_and_estimator_tracking() -> None:
    estimator = AdaptiveCapacityEstimator(nominal_capacity_mbps=100.0)
    estimator.set_capacity(22.0)
    err = estimator.record_ground_truth(20.0)
    assert err == 2.0
    assert estimator.mean_abs_error_mbps == 2.0

    driver = TCDriver(runner=MockCommandRunner())
    coordinator = EnforcementCoordinator(
        engine=PolicyEngine(),
        driver=driver,
        interface="ff_veth1",
        namespace="ff_router",
    )
    controller = DynamicController(
        engine=PolicyEngine(),
        coordinator=coordinator,
        capacity_provider=estimator,
    )

    window = TelemetryWindow(
        window_index=0,
        start_time_monotonic=1.0,
        end_time_monotonic=3.0,
        wall_clock_time=1700000000.0,
        packet_records=(
            PacketRecord(seq=1, send_time_ns=1_000_000_000, recv_time_ns=1_016_000_000),
            PacketRecord(seq=2, send_time_ns=1_020_000_000, recv_time_ns=1_037_000_000),
        ),
        packets_sent=2,
        packets_received=2,
        baseline_delay_ms=15.0,
    )
    controller.process_observation_window(window)

    overhead = controller.get_overhead_metrics()
    assert overhead["steps_evaluated"] == 1
    assert overhead["last_step_wall_ms"] >= 0.0
    assert overhead["last_step_cpu_ms"] >= 0.0
    assert overhead["process_rss_mb"] >= 0.0
    assert overhead["estimator"]["mae_mbps"] == 2.0
    assert overhead["estimator"]["capacity_mbps"] == 22.0


def test_production_endpoints_and_lkg_persistence(tmp_path: Path) -> None:
    db_path = tmp_path / "prod_test.db"
    lkg_path = tmp_path / "lkg_state.json"

    store1 = AuditStore(db_path)
    app1 = create_app(store=store1, lkg_state_path=lkg_path)

    with TestClient(app1) as client:
        # Health & readiness probes
        health = client.get("/api/v1/health").json()
        assert health["contract_verified"] is True
        assert len(health["contract_sha256"]) == 64

        assert client.get("/api/v1/health/live").status_code == 200
        ready = client.get("/api/v1/health/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        # Contract SHA-256
        contract_resp = client.get("/api/v1/contract").json()
        assert contract_resp["integrity_verified"] is True
        assert contract_resp["sha256"] == health["contract_sha256"]

        # Propose valid policy -> stamps contract SHA-256 & persists LKG to disk
        propose_resp = client.post(
            "/api/v1/policies/propose",
            json={
                "policy": {
                    "classes": [
                        {"name": "interactive", "rate_mbps": 50.0, "floor_mbps": 3.0, "priority": 1, "leaf_qdisc": "cake"},
                        {"name": "streaming", "rate_mbps": 50.0, "floor_mbps": 9.0, "priority": 2, "leaf_qdisc": "fq_codel"},
                        {"name": "bulk", "rate_mbps": 50.0, "floor_mbps": 2.0, "priority": 3, "leaf_qdisc": "fq_codel"},
                    ]
                },
                "capacity_mbps": 100.0,
                "capacity_is_raw": True,
                "simulate_canary_breach": False,
            },
        )
        assert propose_resp.status_code == 200
        body = propose_resp.json()
        assert body["verdict"] == "ACCEPTED"
        assert health["contract_sha256"] in body["report_markdown"]
        assert lkg_path.exists()

        saved_lkg = json.loads(lkg_path.read_text(encoding="utf-8"))
        assert saved_lkg["classes"]["interactive"]["rate_floor_mbps"] == 3.0

        # Status & overhead & Prometheus /metrics
        status_json = client.get("/api/v1/status").json()
        assert status_json["contract_verified"] is True
        assert status_json["overhead"]["steps_evaluated"] >= 1
        assert status_json["estimator"]["confidence"] > 0

        overhead_resp = client.get("/api/v1/metrics/overhead")
        assert overhead_resp.status_code == 200
        assert overhead_resp.json()["commits"] >= 1

        prom_resp = client.get("/metrics", headers={"Origin": "https://fairflow.vercel.app"})
        assert prom_resp.status_code == 200
        assert "fairflow_contract_verified 1" in prom_resp.text
        assert "fairflow_controller_steps_total" in prom_resp.text
        assert prom_resp.headers.get("access-control-allow-origin") == "*"
        assert prom_resp.headers.get("access-control-allow-credentials") != "true"

        # Hardware pilot script export JSON + download + invalid interface rejection
        script_json = client.get("/api/v1/enforce/export-script?target=openwrt_sqm&wan_iface=eth0").json()
        assert script_json["target"] == "openwrt_sqm"
        assert "uci set sqm.fairflow_pilot" in script_json["script"]

        dl_resp = client.get("/api/v1/enforce/export-script?target=linux_tc&download=true")
        assert dl_resp.status_code == 200
        assert "attachment; filename=" in dl_resp.headers.get("content-disposition", "")

        bad_iface = client.get("/api/v1/enforce/export-script?wan_iface=eth0;id")
        assert bad_iface.status_code == 422

    # Simulated process restart recovers persisted LKG policy cleanly
    store2 = AuditStore(db_path)
    app2 = create_app(store=store2, lkg_state_path=lkg_path)
    with TestClient(app2) as client2:
        restarted_status = client2.get("/api/v1/status").json()
        floors = {c["name"]: c["floor_mbps"] for c in restarted_status["active_policy"]["classes"]}
        assert floors["interactive"] == 3.0
        assert floors["streaming"] == 9.0

        # System reset clears persisted LKG file cleanly
        reset_resp = client2.post("/api/v1/system/reset")
        assert reset_resp.status_code == 200
        assert not lkg_path.exists()
