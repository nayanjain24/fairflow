#!/usr/bin/env bash
# scripts/run_m2.sh — Entry point for FairFlow M2 experiment execution
# Usage:
#   bash scripts/run_m2.sh [smoke|full]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

MODE="${1:-smoke}"
if [[ "${MODE}" != "smoke" && "${MODE}" != "full" ]]; then
    echo "Usage: $0 [smoke|full]" >&2
    exit 1
fi

TIMESTAMP="$(date -u +"%Y%m%d_%H%M%S")"
RUN_ID="${MODE}_${TIMESTAMP}"
RUN_DIR="${REPO_ROOT}/results/m2/${RUN_ID}"
mkdir -p "${RUN_DIR}"
CONSOLE_LOG="${RUN_DIR}/console.txt"

echo "=== Starting FairFlow M2 Scenario A (${MODE} run: ${RUN_ID}) ==="
echo "Logging all console output to: ${CONSOLE_LOG}"

# Run inside the VM wrapper and tee output to console.txt
bash "${REPO_ROOT}/scripts/vm.sh" sudo PYTHONPATH=/home/ubuntu/fairflow ~/venv-ff/bin/python src/fairflow/harness.py "${MODE}" --run-id "${RUN_ID}" 2>&1 | tee "${CONSOLE_LOG}"

# Check exit code of harness
STATUS="${PIPESTATUS[0]}"
if [ "${STATUS}" -ne 0 ]; then
    echo "ERROR: Experiment run failed with exit code ${STATUS}." >&2
    exit "${STATUS}"
fi

echo "=== M2 ${MODE} Run Finished Successfully ==="
echo "Artifacts saved under: ${RUN_DIR}"
