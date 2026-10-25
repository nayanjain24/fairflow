#!/usr/bin/env bash
# 00_check_env.sh - Environment verification for FairFlow
# Checks Python >= 3.12, system tools, and records exact versions in results/env.json

set -euo pipefail

if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: run via scripts/vm.sh inside the Ubuntu VM" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${REPO_ROOT}/results"
ENV_JSON="${RESULTS_DIR}/env.json"

mkdir -p "${RESULTS_DIR}"

echo "=== Checking FairFlow Environment ==="

# 1. Check Python
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

PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
echo "Python: ${PYTHON_BIN} (${PY_VERSION})"

# 2. Check Python packages
PYTEST_VER="$("${PYTHON_BIN}" -c 'import pytest; print(pytest.__version__)' 2>/dev/null || echo "not_installed")"
PYYAML_VER="$("${PYTHON_BIN}" -c 'import yaml; print(yaml.__version__)' 2>/dev/null || echo "not_installed")"
echo "pytest: ${PYTEST_VER}"
echo "pyyaml: ${PYYAML_VER}"

# 3. Check System tools
TC_PATH="$(command -v tc 2>/dev/null || echo "missing")"
TC_VER="missing"
if [ "${TC_PATH}" != "missing" ]; then
    TC_VER="$(tc -V 2>/dev/null || echo "present")"
fi

IP_PATH="$(command -v ip 2>/dev/null || echo "missing")"
IP_VER="missing"
if [ "${IP_PATH}" != "missing" ]; then
    IP_VER="$(ip -V 2>/dev/null || echo "present")"
fi

IPERF_PATH="$(command -v iperf3 2>/dev/null || echo "missing")"
IPERF_VER="missing"
if [ "${IPERF_PATH}" != "missing" ]; then
    IPERF_VER="$(iperf3 -v 2>&1 | head -n 1 || echo "present")"
fi

echo "tc:     ${TC_PATH} (${TC_VER})"
echo "ip:     ${IP_PATH} (${IP_VER})"
echo "iperf3: ${IPERF_PATH} (${IPERF_VER})"

# 4. Check Linux network namespace capability
NETNS_CAPABLE="false"
if [ "$(uname -s)" = "Linux" ]; then
    if [ "${IP_PATH}" != "missing" ]; then
        if [ "$(id -u)" -eq 0 ]; then
            if ip netns add ff_env_test 2>/dev/null; then
                ip netns del ff_env_test 2>/dev/null || true
                NETNS_CAPABLE="true"
            fi
        elif sudo -n true 2>/dev/null; then
            if sudo ip netns add ff_env_test 2>/dev/null; then
                sudo ip netns del ff_env_test 2>/dev/null || true
                NETNS_CAPABLE="true"
            fi
        fi
    fi
fi
echo "netns_capable: ${NETNS_CAPABLE}"

# 5. Write results/env.json
"${PYTHON_BIN}" - <<EOF
import json
import platform
import time

data = {
    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "platform": {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    },
    "python": {
        "executable": "${PYTHON_BIN}",
        "version": "${PY_VERSION}",
    },
    "packages": {
        "pytest": "${PYTEST_VER}",
        "pyyaml": "${PYYAML_VER}",
    },
    "system_tools": {
        "tc": {"path": "${TC_PATH}", "version": "${TC_VER}"},
        "ip": {"path": "${IP_PATH}", "version": "${IP_VER}"},
        "iperf3": {"path": "${IPERF_PATH}", "version": "${IPERF_VER}"},
    },
    "netns_capable": "${NETNS_CAPABLE}".lower() == "true"
}

with open("${ENV_JSON}", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(f"Recorded environment snapshot to ${ENV_JSON}")
EOF

echo "=== Environment Check Finished ==="
