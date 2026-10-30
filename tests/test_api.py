"""tests/test_api.py — Unit and integration tests for FairFlow REST API."""

import pytest
from fastapi.testclient import TestClient

from src.fairflow.api import create_app
from src.fairflow.store import AuditStore


@pytest.fixture
def api_client(tmp_path):
    """Create a test client with an isolated in-memory or temporary store."""
    db_file = tmp_path / "test_api.db"
    store = AuditStore(db_file)
    app = create_app(store=store)
    client = TestClient(app)
    yield client
    store.close()


def test_health_endpoint(api_client: TestClient) -> None:
    resp = api_client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "fairflow-backend"
    assert "controller_enabled" in data


def test_status_endpoint(api_client: TestClient) -> None:
    resp = api_client.get("/api/v1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "controller_enabled" in data
    assert "interface" in data
    assert "namespace" in data
    assert "enforcement_state" in data


def test_policy_validate_endpoint(api_client: TestClient) -> None:
    # 1. Valid policy
    payload = {
        "policy": {
            "classes": [
                {
                    "name": "interactive",
                    "rate_mbps": 15.0,
                    "floor_mbps": 5.0,
                    "ceil_mbps": 50.0,
                    "priority": 1,
                    "leaf_qdisc": "fq_codel",
                },
                {
                    "name": "streaming",
                    "rate_mbps": 25.0,
                    "floor_mbps": 8.0,
                    "ceil_mbps": 70.0,
                    "priority": 2,
                    "leaf_qdisc": "fq_codel",
                },
                {
                    "name": "bulk",
                    "rate_mbps": 55.0,
                    "floor_mbps": 2.0,
                    "ceil_mbps": 95.0,
                    "priority": 3,
                    "leaf_qdisc": "fq_codel",
                },
            ]
        },
        "capacity_mbps": 100.0,
        "capacity_is_raw": True,
    }
    resp = api_client.post("/api/v1/policies/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is True
    assert data["is_feasible"] is True
    assert data["usable_capacity_mbps"] == 95.0
    assert data["required_minimum_mbps"] == 15.0  # 5 + 8 + 2

    # 2. Infeasible policy (floors exceed capacity)
    infeasible_payload = {
        "policy": {
            "classes": [
                {
                    "name": "interactive",
                    "rate_mbps": 60.0,
                    "floor_mbps": 60.0,
                    "priority": 1,
                    "leaf_qdisc": "fq_codel",
                },
                {
                    "name": "bulk",
                    "rate_mbps": 50.0,
                    "floor_mbps": 50.0,
                    "priority": 3,
                    "leaf_qdisc": "fq_codel",
                },
            ]
        },
        "capacity_mbps": 50.0,
        "capacity_is_raw": False,
    }
    resp2 = api_client.post("/api/v1/policies/validate", json=infeasible_payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["is_feasible"] is False
    assert len(data2["reasons"]) > 0


def test_controller_enable_disable(api_client: TestClient) -> None:
    resp = api_client.post("/api/v1/controller/disable")
    assert resp.status_code == 200
    assert resp.json()["controller_enabled"] is False

    resp2 = api_client.post("/api/v1/controller/enable")
    assert resp2.status_code == 200
    assert resp2.json()["controller_enabled"] is True


def test_controller_evaluate_step(api_client: TestClient) -> None:
    resp = api_client.post(
        "/api/v1/controller/evaluate",
        json={"force": True, "synthetic_base_delay_ms": 14.5, "synthetic_throughput_mbps": 90.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "step_index" in data
    assert "action" in data
    assert "explanation" in data


def test_telemetry_history_and_latest(api_client: TestClient) -> None:
    # First evaluate to generate telemetry
    api_client.post(
        "/api/v1/controller/evaluate",
        json={"force": True, "synthetic_base_delay_ms": 12.0},
    )

    resp_latest = api_client.get("/api/v1/telemetry/latest")
    assert resp_latest.status_code == 200
    data_latest = resp_latest.json()
    assert data_latest is not None
    assert data_latest["rtt_ms"] == 12.0

    resp_hist = api_client.get("/api/v1/telemetry/history?limit=10")
    assert resp_hist.status_code == 200
    assert len(resp_hist.json()) >= 1


def test_events_and_rollback_history(api_client: TestClient) -> None:
    resp = api_client.get("/api/v1/events")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    resp_rb = api_client.get("/api/v1/rollback/history")
    assert resp_rb.status_code == 200
    assert isinstance(resp_rb.json(), list)


def test_experiment_endpoints(api_client: TestClient) -> None:
    resp = api_client.get("/api/v1/experiments")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Launch experiment
    resp_start = api_client.post(
        "/api/v1/experiments",
        json={"scenario_id": "scenario_a", "duration_s": 10.0},
    )
    assert resp_start.status_code == 200
    exp_data = resp_start.json()
    assert "run_id" in exp_data
    assert exp_data["status"] == "pending"

    # Query experiment
    exp_id = exp_data["run_id"]
    resp_get = api_client.get(f"/api/v1/experiments/{exp_id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["run_id"] == exp_id

    # Query results
    resp_res = api_client.get(f"/api/v1/experiments/{exp_id}/results")
    assert resp_res.status_code == 200
    assert resp_res.json()["run_id"] == exp_id


def test_contract_and_flows_override_endpoints(api_client: TestClient) -> None:
    resp_c = api_client.get("/api/v1/contract")
    assert resp_c.status_code == 200
    contract_data = resp_c.json()
    assert contract_data["interactive"]["added_delay_guardrail_ms"] == 80.0
    assert contract_data["interactive"]["floor_mbps"] == 2.0

    # List classified flows
    resp_f = api_client.get("/api/v1/flows")
    assert resp_f.status_code == 200
    flows = resp_f.json()
    assert len(flows) >= 4

    # Override a bulk flow to interactive
    target_flow_id = "tcp:10.0.2.2:5201->10.0.1.2:54102"
    resp_ov = api_client.post(
        "/api/v1/flows/override",
        json={"flow_id": target_flow_id, "target_class": "interactive", "duration_s": 300.0},
    )
    assert resp_ov.status_code == 200
    assert resp_ov.json()["target_class"] == "interactive"

    # Confirm override took effect in classifier
    flows_after = api_client.get("/api/v1/flows").json()
    matched = [f for f in flows_after if f["flow_id"] == target_flow_id]
    assert len(matched) == 1
    assert matched[0]["effective_class"] == "interactive"
    assert matched[0]["is_override"] is True


def test_propose_policy_gate_and_canary_rollback(api_client: TestClient) -> None:
    # 1. Rejected by Pre-Apply Safety Gate (interactive floor 0.5 < 2.0 Mbps)
    bad_payload = {
        "policy": {
            "classes": [
                {"name": "interactive", "rate_mbps": 95.0, "floor_mbps": 0.5, "priority": 1, "leaf_qdisc": "fq_codel"},
                {"name": "bulk", "rate_mbps": 95.0, "floor_mbps": 2.0, "priority": 3, "leaf_qdisc": "fq_codel"},
            ]
        },
        "capacity_mbps": 100.0,
        "capacity_is_raw": True,
    }
    r1 = api_client.post("/api/v1/policies/propose", json=bad_payload)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["verdict"] == "REJECTED"
    assert d1["gate_passed"] is False
    assert "report_markdown" in d1
    assert "Completion / Rejection Reason & Explanation" in d1["report_markdown"]

    # 2. Accepted by Gate, Canary Breached -> Rolled back & Verified
    canary_breach_payload = {
        "policy": {
            "classes": [
                {"name": "interactive", "rate_mbps": 95.0, "floor_mbps": 2.0, "priority": 1, "leaf_qdisc": "pfifo"},
                {"name": "streaming", "rate_mbps": 95.0, "floor_mbps": 8.0, "priority": 2, "leaf_qdisc": "pfifo"},
                {"name": "bulk", "rate_mbps": 95.0, "floor_mbps": 2.0, "priority": 3, "leaf_qdisc": "pfifo"},
            ]
        },
        "capacity_mbps": 100.0,
        "capacity_is_raw": True,
        "simulate_canary_breach": True,
    }
    r2 = api_client.post("/api/v1/policies/propose", json=canary_breach_payload)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["verdict"] == "ROLLED_BACK"
    assert d2["rollback_performed"] is True
    assert d2["rollback_verified"] is True
    assert "report_markdown" in d2

    # 3. Accepted and committed
    good_payload = {
        "policy": {
            "classes": [
                {"name": "interactive", "rate_mbps": 95.0, "floor_mbps": 2.2, "priority": 1, "leaf_qdisc": "fq_codel"},
                {"name": "streaming", "rate_mbps": 95.0, "floor_mbps": 8.5, "priority": 2, "leaf_qdisc": "fq_codel"},
                {"name": "bulk", "rate_mbps": 95.0, "floor_mbps": 2.2, "priority": 3, "leaf_qdisc": "fq_codel"},
            ]
        },
        "capacity_mbps": 100.0,
        "capacity_is_raw": True,
        "simulate_canary_breach": False,
    }
    r3 = api_client.post("/api/v1/policies/propose", json=good_payload)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["verdict"] == "ACCEPTED"
    assert d3["gate_passed"] is True
    assert "report_markdown" in d3


def test_kernel_qdisc_and_traffic_status_endpoints(api_client: TestClient) -> None:
    rq = api_client.get("/api/v1/kernel/qdisc")
    assert rq.status_code == 200
    assert "qdiscs" in rq.json()
    assert "classes" in rq.json()

    rt = api_client.get("/api/v1/traffic/status")
    assert rt.status_code == 200
    assert "running" in rt.json()


def test_system_reset_clears_data_and_restores_baseline(api_client: TestClient) -> None:
    # Propose a rejected policy first
    bad_payload = {
        "policy": {
            "classes": [
                {"name": "interactive", "rate_mbps": 95.0, "floor_mbps": 0.5, "priority": 1, "leaf_qdisc": "fq_codel"},
            ]
        },
        "capacity_mbps": 100.0,
    }
    api_client.post("/api/v1/policies/propose", json=bad_payload)
    assert len(api_client.get("/api/v1/policies").json()) == 1

    # Reset all data
    r_reset = api_client.post("/api/v1/system/reset")
    assert r_reset.status_code == 200
    reset_json = r_reset.json()
    assert reset_json["status"] == "reset_complete"
    assert reset_json["active_policy_id"] == "pol_v1_baseline"
    assert reset_json["capacity_mbps"] == 100.0

    # Verify only pol_v1_baseline remains and rollbacks are empty
    policies_after = api_client.get("/api/v1/policies").json()
    assert len(policies_after) == 1
    assert policies_after[0]["policy_id"] == "pol_v1_baseline"
    assert len(api_client.get("/api/v1/rollback/history").json()) == 0


