#!/usr/bin/env bash
# run_idle_noise_floor.sh - 60-second idle baseline measurement between namespaces
# Uses Linux network namespaces: client (ff_client) -> router (ff_router) -> server (ff_server)
# Hardware behaviour: software emulation via network namespaces and veth pairs.

set -euo pipefail

if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: run via scripts/vm.sh inside the Ubuntu VM" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"
SCENARIO_YAML="${REPO_ROOT}/experiments/idle_noise_floor.yaml"

# Detect Python for the Ubuntu VM (prefer /home/ubuntu/venv-ff/bin/python)
if [ -x "/home/ubuntu/venv-ff/bin/python" ]; then
    PYTHON_BIN="/home/ubuntu/venv-ff/bin/python"
elif [ -x "${HOME}/venv-ff/bin/python" ]; then
    PYTHON_BIN="${HOME}/venv-ff/bin/python"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "ERROR: python3 not found!" >&2
    exit 1
fi

DURATION="${1:-60}"
RAW_CSV="${RESULTS_DIR}/idle_noise_floor_packets.csv"
COUNT_FILE="${RESULTS_DIR}/idle_noise_floor_sent.txt"
SUMMARY_JSON="${RESULTS_DIR}/noise_floor_summary.json"

mkdir -p "${RESULTS_DIR}"

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

# Compute SHA-256 of contract.yaml so every run's metadata is tied to the exact contract.
CONTRACT_HASH="none"
if [ -f "${REPO_ROOT}/contract.yaml" ]; then
    CONTRACT_HASH="$(sha256sum "${REPO_ROOT}/contract.yaml" | awk '{print $1}')"
fi

TIMESTAMP="$(date -u +"%Y%m%d_%H%M%S")"
TIMESTAMPED_JSON="${RESULTS_DIR}/noise_floor_${TIMESTAMP}.json"

echo "=== Analyzing Raw CSV and Generating Summary ==="
PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" -m src.fairflow.traffic summary \
    --csv "${RAW_CSV}" \
    --total-sent "${TOTAL_SENT}" \
    --out "${SUMMARY_JSON}"

# Inject contract_sha256 into the summary JSON using Python so we don't need jq.
PYTHONPATH="${REPO_ROOT}" "${PYTHON_BIN}" - << EOF
import json
from pathlib import Path

path = Path("${SUMMARY_JSON}")
data = json.loads(path.read_text(encoding="utf-8"))
data["contract_sha256"] = "${CONTRACT_HASH}"
path.write_text(json.dumps(data, indent=2), encoding="utf-8")
EOF

cp "${SUMMARY_JSON}" "${TIMESTAMPED_JSON}"
echo "Saved timestamped run summary to ${TIMESTAMPED_JSON}"

echo "=== Idle Noise Floor Run Complete ==="
