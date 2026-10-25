#!/usr/bin/env bash
# run_idle_noise_floor.sh - 60-second idle baseline measurement between namespaces
# Uses Linux network namespaces: client (ff_client) -> router (ff_router) -> server (ff_server)
# Hardware behaviour: software emulation via network namespaces and veth pairs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"
SCENARIO_YAML="${REPO_ROOT}/experiments/idle_noise_floor.yaml"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

DURATION="${1:-60}"
RAW_CSV="${RESULTS_DIR}/idle_noise_floor_packets.csv"
COUNT_FILE="${RESULTS_DIR}/idle_noise_floor_sent.txt"
SUMMARY_JSON="${RESULTS_DIR}/idle_noise_floor_summary.json"

mkdir -p "${RESULTS_DIR}"

if [ ! -x "${PYTHON_BIN}" ]; then
    echo "ERROR: Virtual environment Python (${PYTHON_BIN}) not found!" >&2
    exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: Network namespaces and veth emulation require a Linux environment." >&2
    echo "Current platform is $(uname -s). Please run on Ubuntu VM." >&2
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Network namespace provisioning requires root privileges. Please re-run with sudo." >&2
    exit 1
fi

echo "=== Provisioning Emulated Testbed from ${SCENARIO_YAML} ==="
# Python one-liner to bring testbed up
PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" - <<EOF
from src.fairflow.testbed import Testbed, ScenarioConfig
cfg = ScenarioConfig.from_yaml("${SCENARIO_YAML}")
tb = Testbed(cfg)
tb.up()
EOF

cleanup() {
    echo "=== Tearing Down Emulated Testbed ==="
    PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" - <<EOF || true
from src.fairflow.testbed import Testbed, ScenarioConfig
cfg = ScenarioConfig.from_yaml("${SCENARIO_YAML}")
tb = Testbed(cfg)
tb.down()
EOF
}
trap cleanup EXIT

echo "=== Starting UDP Call Receiver in server namespace (ff_server) ==="
ip netns exec ff_server "${PYTHON_BIN}" -m src.fairflow.traffic recv \
    --bind 10.0.2.2 \
    --port 5005 \
    --duration "${DURATION}" \
    --csv "${RAW_CSV}" &
RECV_PID=$!

# Give receiver a moment to bind socket
sleep 0.5

echo "=== Starting UDP Call Sender in client namespace (ff_client) for ${DURATION}s ==="
ip netns exec ff_client "${PYTHON_BIN}" -m src.fairflow.traffic send \
    --dest 10.0.2.2 \
    --port 5005 \
    --duration "${DURATION}" \
    --count-out "${COUNT_FILE}"

# Wait for receiver process to complete logging
wait ${RECV_PID}

TOTAL_SENT="$(cat "${COUNT_FILE}")"

echo "=== Analyzing Raw CSV and Generating Summary ==="
PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" -m src.fairflow.traffic summary \
    --csv "${RAW_CSV}" \
    --total-sent "${TOTAL_SENT}" \
    --out "${SUMMARY_JSON}"

echo "=== Idle Noise Floor Run Complete ==="
