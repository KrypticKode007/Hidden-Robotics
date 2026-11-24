#!/usr/bin/env bash
set -euo pipefail

SUITE_DIR="${HOME}/KaiSuite"
VENV_DIR="${SUITE_DIR}/.venv"

echo "========================================================"
echo " Kai-007 x Hidden-Robotics | Full Stack Mac Installer"
echo "========================================================"

# 1. Verify macOS & Xcode Command Line Tools
if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Warning: Native MLX acceleration requires macOS Apple Silicon."
fi

if ! xcode-select -p >/dev/null 2>&1; then
    echo "[1/6] Installing Xcode Command Line Tools..."
    xcode-select --install || true
fi

# 2. Clone or update both repositories side-by-side
mkdir -p "${SUITE_DIR}"
cd "${SUITE_DIR}"

echo "[2/6] Fetching Kai-007 & Hidden-Robotics repositories..."
if [[ ! -d "kai-007" ]]; then
    git clone https://github.com
else
    git -C kai-007 pull --ff-only
fi

if [[ ! -d "Hidden-Robotics" ]]; then
    git clone https://github.com
else
    git -C Hidden-Robotics pull --ff-only
fi

# 3. Create unified Python 3.11+ virtual environment
echo "[3/6] Setting up Python virtual environment..."
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip

# 4. Install dependencies for both repositories
echo "[4/6] Installing MLX, BLE, Cryptography, Vault & Robotics packages..."
if [[ -f "kai-007/requirements.txt" ]]; then
    pip install -r kai-007/requirements.txt
fi
pip install bleak cryptography sqlite-vec mlx-lm mlx-whisper pyobjc-framework-CoreBluetooth \
            libzim beautifulsoup4 meshtastic pypubsub pyserial pyyaml pytest platformio

# 5. Compile C++11 Zero-Copy Shared Memory Engine
echo "[5/6] Compiling C++11 zero-copy perception loop..."
mkdir -p kai-007/bin
if [[ -f "kai-007/Interaction_loop.c++11" ]]; then
    clang++ -std=c++11 -O3 -Ikai-007/core kai-007/Interaction_loop.c++11 -o kai-007/bin/interaction_loop
fi

# 6. Run automated verification across both repos
echo "[6/6] Running End-to-End Safety & System Verification..."
if [[ -f "Hidden-Robotics/test_omni_e2e.sh" ]]; then
    (cd Hidden-Robotics && chmod +x test_omni_e2e.sh && ./test_omni_e2e.sh)
fi

echo "========================================================"
echo " Installation Complete!"
echo " Workspace: ${SUITE_DIR}"
echo " Activate environment: source ${VENV_DIR}/bin/activate"
echo "========================================================"
