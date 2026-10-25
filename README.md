# FairFlow

Adaptive QoS Engine for Mixed Home Broadband Traffic (TELIPORT Season 4, Case Study 3).

## Overview
FairFlow is a constraint-aware QoS controller for a home broadband link, emulated in a Linux lab. It evaluates candidate policies against explicit performance, minimum-service and stability constraints, deploys eligible ones through a short canary, measures the actual outcome, and automatically rolls back to the last-known-good policy if guardrails are breached. If capacity makes the constraints infeasible, it reports the conflict instead of claiming success.

Hardware behaviour is emulated using Linux network namespaces, veth pairs, and tc (HTB/fq_codel).

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
