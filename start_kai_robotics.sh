#!/usr/bin/env bash
set -euo pipefail

SUITE_DIR="${HOME}/KaiSuite"
VENV_DIR="${SUITE_DIR}/.venv"
KAI_DIR="${SUITE_DIR}/kai-007"
ROBOTICS_DIR="${SUITE_DIR}/Hidden-Robotics"

PIDS=()

cleanup() {
    echo ""
    echo "[KAI-SUITE] Shutting down all subsystems safely..."
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    wait || true
    echo "[KAI-SUITE] All processes stopped cleanly."
}
trap cleanup INT TERM EXIT

echo "========================================================"
echo " Launching Kai-007 x Hidden-Robotics Embodied AI Stack"
echo "========================================================"

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
    source "${VENV_DIR}/bin/activate"
fi

# 1. Start C++11 Zero-Copy Shared Memory Perception Engine
if [[ -x "${KAI_DIR}/bin/interaction_loop" ]]; then
    echo "[1/3] Starting C++11 zero-copy perception engine..."
    "${KAI_DIR}/bin/interaction_loop" &
    PIDS+=($!)
    sleep 0.5
else
    echo "[1/3] C++11 binary not found at ${KAI_DIR}/bin/interaction_loop (skipping)"
fi

# 2. Start Kai-007 Apple MLX Brain & 2.4 GHz BLE Radio Bridge
if [[ -f "${KAI_DIR}/brain.py" ]]; then
    echo "[2/3] Starting Kai-007 MLX Brain & BLE Radio Bridge..."
    (cd "${KAI_DIR}" && python3 brain.py) &
    PIDS+=($!)
    sleep 1.0
fi

# 3. Start Hidden-Robotics Master Orchestrator (Foreground)
echo "[3/3] Starting Hidden-Robotics Master Wiring & Safety Guard..."
cd "${ROBOTICS_DIR}"
export PYTHONPATH="${KAI_DIR}:${ROBOTICS_DIR}:${PYTHONPATH:-}"
python3 wire_kryptic_main.py
