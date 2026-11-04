# FairFlow

[![Build, Test & Publish FairFlow Docker Image](https://github.com/nayanjain24/fairflow/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/nayanjain24/fairflow/actions/workflows/docker-publish.yml)

Adaptive QoS Engine for Mixed Home Broadband Traffic (TELIPORT Season 4, Case Study 3).

## Overview
FairFlow is a constraint-aware QoS controller for a home broadband link, emulated in a Linux lab. It evaluates candidate policies against explicit performance, minimum-service and stability constraints, deploys eligible ones through a short canary, measures the actual outcome, and automatically rolls back to the last-known-good policy if guardrails are breached. If capacity makes the constraints infeasible, it reports the conflict instead of claiming success.

Hardware behaviour is emulated using Linux network namespaces, veth pairs, and tc (HTB/fq_codel).

## Quickstart with Docker Hub (`nayan2406/fairflow`) & GHCR

Every push to `main` automatically runs the test suite, builds the multi-stage Docker image ([`Dockerfile`](./Dockerfile)), and publishes it to **Docker Hub (`nayan2406/fairflow:latest`)** and **GitHub Container Registry (`ghcr.io/nayanjain24/fairflow:latest`)** via [`.github/workflows/docker-publish.yml`](./.github/workflows/docker-publish.yml).

```bash
# Option 1: Pull and run directly from Docker Hub (nayan2406)
docker pull nayan2406/fairflow:latest
docker run --rm --privileged -p 8000:8000 nayan2406/fairflow:latest

# Option 2: Pull and run from GitHub Container Registry
docker pull ghcr.io/nayanjain24/fairflow:latest
docker run --rm --privileged -p 8000:8000 ghcr.io/nayanjain24/fairflow:latest

# Option 3: Build and run locally with Docker Compose
docker compose up --build
```
Then open **http://localhost:8000** for the FairFlow 3D Frontend (`/`, `/dashboard`, `/lab`, `/report`) and **http://localhost:8000/docs** for the FastAPI Swagger documentation.

## VM Workflow

All network namespace operations, traffic shaping (`tc`), synthetic traffic generation (`iperf3`), and integration tests must execute inside the **Ubuntu 24.04 ARM64 Multipass VM** (`fairflow`). Never execute `sudo` or network configuration on the macOS host.

### 1. Initial VM Setup (One-time from macOS)
```bash
./scripts/vm_setup.sh
```
This script:
- Verifies or launches the `fairflow` Multipass VM (Ubuntu 24.04 ARM64).
- Mounts the workspace to `/home/ubuntu/fairflow` in the VM (with tar/transfer fallback).
- Provisions required system packages (`iproute2`, `iperf3`, `python3-venv`).
- Sets up an external virtual environment outside the repository at `~/venv-ff`.

### 2. Running Commands Inside the VM
All development scripts and test executions in the VM should run through the `scripts/vm.sh` wrapper:
```bash
./scripts/vm.sh <command> [args...]
```
Examples:
```bash
./scripts/vm.sh pytest -q
./scripts/vm.sh sudo ~/venv-ff/bin/python -m pytest -m integration -v
./scripts/vm.sh bash scripts/00_check_env.sh
```

### 3. Automated VM Verification Run
To run the complete verification suite and capture raw logs:
```bash
./scripts/vm_verify.sh
```
This executes:
1. Environment and tool version checks (`uname -a`, `tc -V`, `python --version`, `iperf3 --version`).
2. Unit tests (`pytest -q`).
3. Root integration tests (`sudo ~/venv-ff/bin/python -m pytest -m integration -v`).
4. Environment snapshot generation (`scripts/00_check_env.sh`).
5. Five consecutive 60-second idle noise-floor baseline runs (`scripts/run_idle_noise_floor.sh`).
All output is teed to `results/vm_verification_<timestamp>.txt`.

## Project Rules
- Interfaces touched must start with `ff_*` (max 15 chars) inside network namespaces.
- All numbers, plots, and percentages must originate from raw log analysis.
- `contract.yaml` is authored and maintained by the user.

---

## Production Frontend (React + Vite + TypeScript)

The FairFlow web frontend is located in `src/{pages,components,scene,charts,api,hooks,styles}` and communicates with the FastAPI backend (`src/fairflow/api.py`).

### 1. Install & Run Instructions

```bash
# 1. Install frontend dependencies
npm install

# 2. (Optional) Start the FastAPI backend inside the Multipass VM
./scripts/vm.sh uvicorn src.fairflow.api:app --host 0.0.0.0 --port 8000

# 3. Start the Vite development server
npm run dev

# 4. Build for production
npm run build
```

### 2. Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://192.168.252.2:8000` (or `http://127.0.0.1:8000`) | Base URL for the FairFlow FastAPI backend |
| `VITE_USE_MOCK` | `false` | Set to `true` (or toggle **MODE: MOCK / LIVE API** in the top navbar) to run the UI without the backend running |

### 3. Backend Endpoints Used by Screen

- **Landing (`/`)**:
  - `GET /api/v1/reports` (`TODO` thin adapter reading `results/` on-disk markdown & CSV/JSON artifacts for the Validation Plan section).
- **Live Dashboard (`/dashboard`)**:
  - `GET /api/v1/status` — Current enforcement state, interface/namespace, capacity estimate, active policy version, and last step outcome.
  - `GET /api/v1/telemetry/history` & `GET /api/v1/telemetry/latest` — 1 Hz live charts for p95 latency, RFC 3550 jitter, packet loss, per-class throughput, queue depth, and Jain's fairness index.
  - `GET /api/v1/contract` (`TODO` thin adapter) — Loads `contract.yaml` guardrails and minimum floors.
  - `GET /api/v1/flows` & `POST /api/v1/flows/override` (`TODO` thin adapter around `TrafficClassifier` & `UserIntentRegistry`) — Displays metadata-classified flows with confidence scores and user-correctable class overrides.
  - `GET /api/v1/policies`, `POST /api/v1/policies/validate`, `POST /api/v1/policies/propose` (`TODO` thin adapter) — Pre-Apply Gate validation, manual policy proposal, and policy safety timeline.
  - `GET /api/v1/rollback/history` & `GET /api/v1/events` — SQLite audit log and verified rollback history from `results/audit.db`.
  - `POST /api/v1/controller/enable`, `POST /api/v1/controller/disable`, `POST /api/v1/controller/evaluate`, `POST /api/v1/controller/capacity` — Controller pause/resume, manual step evaluation, and capacity simulation.
- **Scenario Lab (`/lab`)**:
  - `GET /api/v1/experiments`, `POST /api/v1/experiments`, `GET /api/v1/experiments/{id}/results` — Launch and monitor Scenarios S1 (`scenario_a`), S2 (`scenario_b`), S3 (`scenario_d`), and S4 (`scenario_c`).
  - `GET /api/v1/reports` — Side-by-side baseline arm comparisons (`R0_no_qos`, `B1_static_htb`, `B2a_fq_codel`, `B2b_cake`) from `summary_by_arm.csv`.
- **Report (`/report`)**:
  - `GET /api/v1/reports` — Renders `report.md` and `trial_metrics.csv` written by `src/fairflow/report.py` with one-click Markdown download and **Export to PDF**.

