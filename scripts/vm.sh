#!/usr/bin/env bash
# scripts/vm.sh - Wrapper to run commands inside the 'fairflow' Multipass VM
# Ensures all tc, iproute2, namespaces, and integration tests run inside Ubuntu 24.04 VM.

set -euo pipefail

VM_NAME="fairflow"

# 1. Check multipass is installed on host
if ! command -v multipass >/dev/null 2>&1; then
    echo "ERROR: 'multipass' executable is not installed or not on PATH." >&2
    echo "Please install Multipass on macOS (e.g. 'brew install --cask multipass')." >&2
    exit 1
fi

# 2. Check VM exists and is running
VM_STATUS="$(multipass list --format csv 2>/dev/null | grep -E "^${VM_NAME}," || true)"
if [ -z "${VM_STATUS}" ]; then
    echo "ERROR: Multipass VM '${VM_NAME}' does not exist." >&2
    echo "Please run scripts/vm_setup.sh to create and configure the VM." >&2
    exit 1
fi

if ! echo "${VM_STATUS}" | grep -qi ",Running"; then
    echo "ERROR: Multipass VM '${VM_NAME}' is not running (status: ${VM_STATUS})." >&2
    echo "Please start the VM using: multipass start ${VM_NAME}" >&2
    exit 1
fi

# 3. Execute command inside VM inside ~/fairflow with ~/venv-ff activated
if [ "$#" -eq 0 ]; then
    echo "Usage: $0 <command> [args...]" >&2
    exit 1
fi

exec multipass exec "${VM_NAME}" -- bash -lc 'cd ~/fairflow && source ~/venv-ff/bin/activate && "$@"' bash "$@"
