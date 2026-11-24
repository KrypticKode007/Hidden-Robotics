#!/usr/bin/env bash
set -euo pipefail

SUITE_DIR="$HOME/kryptic_omni_suite"
HUB_DIR="$SUITE_DIR/Hidden-Robotics"

mkdir -p "$SUITE_DIR"
cd "$SUITE_DIR"

echo "=== [1/4] Syncing KrypticKode007/Hidden-Robotics Master Hub ==="
if [ ! -d "$HUB_DIR" ]; then
    git clone https://github.com
else
    git -C "$HUB_DIR" pull --ff-only
fi

echo "=== [2/4] Staging Integration Scripts & Configs into Omni-Suite ==="
cp -f "$HUB_DIR"/*.sh "$SUITE_DIR/"
cp -f "$HUB_DIR"/*.py "$SUITE_DIR/"
[ -d "$HUB_DIR/config" ] && mkdir -p "$SUITE_DIR/config" && cp -rf "$HUB_DIR/config/"* "$SUITE_DIR/config/"
chmod +x "$SUITE_DIR"/*.sh

echo "=== [3/4] Running Peak Deployment, MacBook Neo Tuning & Robotics Upgrade ==="
"$SUITE_DIR/deploy_peak_kryptic_omni.sh"
"$SUITE_DIR/finalize_neo_omni_suite.sh"
"$SUITE_DIR/upgrade_kryptic_robotics.sh"

echo "=== [4/4] Auto-Wiring kryptic-agent/main.py & Verifying Status ==="
source "$SUITE_DIR/venv/bin/activate"
python "$SUITE_DIR/wire_kryptic_main.py"
"$SUITE_DIR/bin/omni" restart

echo "=== All Three Repositories (Hidden-Robotics + kai-007 + kryptic-agent) Unified! ==="
