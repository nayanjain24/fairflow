#!/usr/bin/env bash
# start.sh — One-command launcher for FairFlow (Linux Kernel Backend + Vite Secure Frontend)
# Usage: ./start.sh   OR   npm start

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

BACKEND_PID=""

cleanup() {
  echo ""
  echo "Stopping FairFlow services..."
  if [ -n "${BACKEND_PID}" ] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
  fi
  exit 0
}

trap cleanup SIGINT SIGTERM

echo "============================================================"
echo "  FairFlow — Safety-Verified Adaptive QoS Controller"
echo "============================================================"

# 1. Ensure frontend dependencies are installed
if [ ! -d "node_modules" ]; then
  echo "[1/3] Installing npm dependencies..."
  npm install
else
  echo "[1/3] Frontend dependencies verified."
fi

# 2. Build production bundle so dist/ is always up-to-date
echo "[2/3] Building latest frontend bundle..."
npm run build

# 3. Start FastAPI + Linux Kernel tc Backend (in Multipass VM if available)
if command -v multipass >/dev/null 2>&1; then
  VM_STATUS="$(multipass list --format csv 2>/dev/null | grep -E '^fairflow,' || true)"
  if [ -n "${VM_STATUS}" ]; then
    if ! echo "${VM_STATUS}" | grep -qi ",Running"; then
      echo "[3/3] Starting 'fairflow' Ubuntu Linux VM..."
      multipass start fairflow
    fi
    echo "[3/3] Starting FastAPI + Linux Kernel tc Backend inside 'fairflow' VM (port 8000)..."
    multipass exec fairflow -- bash -lc "pkill -f 'uvicorn src.fairflow.api:app' || true" >/dev/null 2>&1 || true
    ./scripts/vm.sh uvicorn src.fairflow.api:app --host 0.0.0.0 --port 8000 >/tmp/fairflow-backend.log 2>&1 &
    BACKEND_PID=$!
    sleep 2
    echo "      ✓ Kernel Backend active (logs: /tmp/fairflow-backend.log)"
  else
    echo "[3/3] Multipass VM 'fairflow' not found — running in Interactive Engine Mode."
  fi
else
  echo "[3/3] Multipass not installed — running in Interactive Engine Mode."
fi

echo ""
echo "============================================================"
echo "  FairFlow is LIVE!"
echo "  -> Open in Browser : http://localhost:5173"
echo "  -> Live Dashboard  : http://localhost:5173/dashboard"
echo "  -> Scenario Lab    : http://localhost:5173/lab"
echo "  -> Judge Report    : http://localhost:5173/report"
echo "  (Press Ctrl+C to stop all services)"
echo "============================================================"
echo ""

npx vite --host localhost --port 5173
