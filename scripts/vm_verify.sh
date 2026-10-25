#!/usr/bin/env bash
# scripts/vm_verify.sh - Complete M1 verification executed inside the Multipass VM
# Runs strictly through scripts/vm.sh and tees all output to results/vm_verification_<UTC timestamp>.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"

mkdir -p "${RESULTS_DIR}"

TIMESTAMP="$(date -u +"%Y%m%d_%H%M%S")"
VERIF_LOG="${RESULTS_DIR}/vm_verification_${TIMESTAMP}.txt"

echo "=== Logging VM verification run to ${VERIF_LOG} ==="

run_step() {
    local desc="$1"
    shift
    echo ""
    echo "======================================================================"
    echo "STEP: ${desc}"
    echo "COMMAND: $*"
    echo "======================================================================"
    "$@"
}

{
    echo "FAIRFLOW VM VERIFICATION RUN"
    echo "Started at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "Host: $(uname -a)"

    # a. Check system versions inside VM
    run_step "System versions" "${SCRIPT_DIR}/vm.sh" uname -a
    run_step "tc version" "${SCRIPT_DIR}/vm.sh" tc -V
    run_step "python version" "${SCRIPT_DIR}/vm.sh" python --version
    run_step "iperf3 version" "${SCRIPT_DIR}/vm.sh" iperf3 --version

    # b. Unit tests (plain pytest -q)
    echo ""
    echo "======================================================================"
    echo "STEP: pytest -q (unit tests)"
    echo "======================================================================"
    PYTEST_OUT="$("${SCRIPT_DIR}/vm.sh" pytest -q)"
    echo "${PYTEST_OUT}"
    if echo "${PYTEST_OUT}" | grep -qi "skipped"; then
        echo "ERROR: Unit tests had skipped tests!" >&2
        exit 1
    fi

    # c. Integration tests with sudo
    echo ""
    echo "======================================================================"
    echo "STEP: Integration tests with sudo"
    echo "======================================================================"
    INTEG_OUT="$("${SCRIPT_DIR}/vm.sh" sudo ~/venv-ff/bin/python -m pytest -m integration -v)"
    echo "${INTEG_OUT}"
    if echo "${INTEG_OUT}" | grep -qi "SKIPPED"; then
        echo "ERROR: Integration tests were skipped! All integration tests must execute and pass in the VM." >&2
        exit 1
    fi

    # d. 00_check_env.sh and verify results/env.json
    run_step "00_check_env.sh" "${SCRIPT_DIR}/vm.sh" bash scripts/00_check_env.sh
    run_step "cat results/env.json" "${SCRIPT_DIR}/vm.sh" cat results/env.json

    # e. 5 repetitions of run_idle_noise_floor.sh
    for i in 1 2 3 4 5; do
        run_step "Noise Floor Run ${i}/5" "${SCRIPT_DIR}/vm.sh" sudo bash scripts/run_idle_noise_floor.sh
    done

    echo ""
    echo "======================================================================"
    echo "All 5 noise floor runs completed successfully."
    echo "Finished at UTC: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "======================================================================"

} 2>&1 | tee "${VERIF_LOG}"

echo ""
echo "Verification finished cleanly. Raw log saved at: ${VERIF_LOG}"
