#!/usr/bin/env bash
# scripts/vm_setup.sh - Idempotent setup for the 'fairflow' Multipass VM
# Run on macOS host to provision the VM, mount/transfer the repo, and prepare ~/venv-ff.

set -euo pipefail

VM_NAME="fairflow"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=== FairFlow Multipass VM Setup ==="

# 1. Check multipass is installed on macOS
if ! command -v multipass >/dev/null 2>&1; then
    echo "ERROR: 'multipass' CLI is not found on PATH." >&2
    echo "Install via Homebrew: brew install --cask multipass" >&2
    exit 1
fi

# 2. Check if VM exists; launch if missing
if ! multipass list --format csv | grep -E "^${VM_NAME}," >/dev/null 2>&1; then
    echo "VM '${VM_NAME}' not found. Launching Ubuntu 24.04 LTS instance..."
    multipass launch 24.04 --name "${VM_NAME}" --cpus 2 --memory 4G --disk 10G
fi

# 3. Ensure VM is running
VM_STATUS="$(multipass list --format csv | grep -E "^${VM_NAME}," || true)"
if ! echo "${VM_STATUS}" | grep -qi ",Running"; then
    echo "Starting VM '${VM_NAME}'..."
    multipass start "${VM_NAME}"
fi

echo "VM '${VM_NAME}' is active and running."

# 4. Mount repo into VM (or fallback to tar transfer)
echo "Ensuring repo is mounted at /home/ubuntu/fairflow..."
MOUNTED="false"
if multipass info "${VM_NAME}" | grep -q "/home/ubuntu/fairflow"; then
    echo "Mount already active."
    MOUNTED="true"
else
    if multipass mount "${REPO_ROOT}" "${VM_NAME}:/home/ubuntu/fairflow" 2>/dev/null; then
        echo "Successfully mounted ${REPO_ROOT} to /home/ubuntu/fairflow."
        MOUNTED="true"
    else
        echo "Direct multipass mount failed. Falling back to tar transfer..."
        ARCHIVE="/tmp/fairflow_vm_sync.tgz"
        COPYFILE_DISABLE=1 tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' \
            -czf "${ARCHIVE}" -C "$(dirname "${REPO_ROOT}")" "$(basename "${REPO_ROOT}")"
        multipass exec "${VM_NAME}" -- mkdir -p /home/ubuntu
        multipass transfer "${ARCHIVE}" "${VM_NAME}:/home/ubuntu/fairflow_sync.tgz"
        multipass exec "${VM_NAME}" -- tar -xzf /home/ubuntu/fairflow_sync.tgz -C /home/ubuntu/
        rm -f "${ARCHIVE}"
        echo "Transferred repository archive to VM at /home/ubuntu/fairflow."
    fi
fi

# 5. Provision packages and external venv (~/venv-ff) inside VM
echo "Provisioning packages inside VM..."
multipass exec "${VM_NAME}" -- bash -lc '
set -euo pipefail
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip iproute2 iperf3

if [ ! -d ~/venv-ff ]; then
    echo "Creating virtual environment at ~/venv-ff..."
    python3 -m venv ~/venv-ff
fi

source ~/venv-ff/bin/activate
pip install --upgrade pip
if [ -f ~/fairflow/requirements.txt ]; then
    pip install -r ~/fairflow/requirements.txt
fi
'

echo "=== VM Setup Complete ==="
echo "You can now execute commands via: scripts/vm.sh <command>"
