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

ETHTOOL_PATH="$(command -v ethtool 2>/dev/null || echo "missing")"
ETHTOOL_VER="missing"
if [ "${ETHTOOL_PATH}" != "missing" ]; then
    ETHTOOL_VER="$(ethtool --version 2>&1 | head -n 1 || echo "present")"
fi

echo "tc:      ${TC_PATH} (${TC_VER})"
echo "ip:      ${IP_PATH} (${IP_VER})"
echo "iperf3:  ${IPERF_PATH} (${IPERF_VER})"
echo "ethtool: ${ETHTOOL_PATH} (${ETHTOOL_VER})"

# 4. Check Kernel modules (qdiscs & impairments)
check_module() {
    local mod="$1"
    if modinfo "${mod}" >/dev/null 2>&1; then
        echo "true"
    elif [ "$(id -u)" -eq 0 ] && modprobe -n "${mod}" >/dev/null 2>&1; then
        echo "true"
    elif sudo -n modprobe -n "${mod}" >/dev/null 2>&1; then
        echo "true"
    else
        echo "false"
    fi
}

echo "=== Checking Kernel Modules ==="
MOD_HTB="$(check_module sch_htb)"
MOD_FQ_CODEL="$(check_module sch_fq_codel)"
MOD_CAKE="$(check_module sch_cake)"
MOD_NETEM="$(check_module sch_netem)"
MOD_TBF="$(check_module sch_tbf)"

echo "sch_htb:      ${MOD_HTB}"
echo "sch_fq_codel: ${MOD_FQ_CODEL}"
echo "sch_cake:     ${MOD_CAKE}"
echo "sch_netem:    ${MOD_NETEM}"
echo "sch_tbf:      ${MOD_TBF}"

# 5. Compute SHA-256 of contract.yaml so env.json records which contract was active.
CONTRACT_SHA256="none"
if [ -f "${REPO_ROOT}/contract.yaml" ]; then
    CONTRACT_SHA256="$(sha256sum "${REPO_ROOT}/contract.yaml" | awk '{print $1}')"
fi
echo "contract_sha256: ${CONTRACT_SHA256}"

# 6. Check Linux network namespace capability
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

# Report missing dependencies loudly
MISSING=()
if [ "${TC_PATH}" = "missing" ]; then MISSING+=("tc"); fi
if [ "${IP_PATH}" = "missing" ]; then MISSING+=("ip"); fi
if [ "${IPERF_PATH}" = "missing" ]; then MISSING+=("iperf3"); fi
if [ "${ETHTOOL_PATH}" = "missing" ]; then MISSING+=("ethtool"); fi
if [ "${MOD_HTB}" != "true" ]; then MISSING+=("sch_htb"); fi
if [ "${MOD_FQ_CODEL}" != "true" ]; then MISSING+=("sch_fq_codel"); fi
if [ "${MOD_CAKE}" != "true" ]; then MISSING+=("sch_cake"); fi
if [ "${MOD_NETEM}" != "true" ]; then MISSING+=("sch_netem"); fi
if [ "${MOD_TBF}" != "true" ]; then MISSING+=("sch_tbf"); fi

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "ERROR: Missing required system dependencies/modules: ${MISSING[*]}" >&2
fi

# 7. Write results/env.json
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
        "ethtool": {"path": "${ETHTOOL_PATH}", "version": "${ETHTOOL_VER}"},
    },
    "kernel_modules": {
        "sch_htb": "${MOD_HTB}".lower() == "true",
        "sch_fq_codel": "${MOD_FQ_CODEL}".lower() == "true",
        "sch_cake": "${MOD_CAKE}".lower() == "true",
        "sch_netem": "${MOD_NETEM}".lower() == "true",
        "sch_tbf": "${MOD_TBF}".lower() == "true",
    },
    "netns_capable": "${NETNS_CAPABLE}".lower() == "true",
    "contract_sha256": "${CONTRACT_SHA256}",
}

with open("${ENV_JSON}", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(f"Recorded environment snapshot to ${ENV_JSON}")
EOF

if [ ${#MISSING[@]} -gt 0 ]; then
    exit 1
fi

echo "=== Environment Check Finished ==="
