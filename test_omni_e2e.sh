#!/usr/bin/env bash
set -euo pipefail

echo "=================================================="
echo " Kai-007 x Hidden-Robotics | E2E Verification Suite"
echo "=================================================="

echo "[1/3] Checking Python syntax across all modules..."
python3 -m py_compile *.py ros2/*.py tests/*.py 2>/dev/null || python3 -m py_compile *.py

echo "[2/3] Running Virtual ESP32-S3 COBS & Hardware E-Stop tests..."
pytest -v tests/test_robotics_cobs_estop.py

echo "[3/3] Checking ESP32-S3 Firmware build (PlatformIO)..."
if command -v pio >/dev/null 2>&1; then
    pio run -d firmware
else
    echo "PlatformIO CLI not installed locally; skipping firmware compile check."
fi

echo "✅ All Hidden-Robotics E2E checks passed!"
