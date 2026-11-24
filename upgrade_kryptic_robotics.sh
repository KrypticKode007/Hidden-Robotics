#!/usr/bin/env bash
set -euo pipefail

SUITE_DIR="$HOME/kryptic_omni_suite"
source "$SUITE_DIR/venv/bin/activate"

echo "=== [1/4] Installing JAX Active Inference (pymdp) & LeRobot ==="
pip install -U inferactively-pymdp lerobot pyyaml

echo "=== [2/4] Cloning ROS 2 Policy Controller (sacovo/lerobot_ros) ==="
cd "$SUITE_DIR"
[ ! -d "lerobot_ros" ] && git clone https://github.com

echo "=== [3/4] Registering Robotics Bridge in Supervisord ==="
CONF="$SUITE_DIR/config/supervisord.conf"
if [ -f "$CONF" ] && ! grep -q "kryptic_robotics_bridge" "$CONF"; then
    cat << EOF >> "$CONF"

[program:kryptic_robotics_bridge]
command=$SUITE_DIR/venv/bin/python $SUITE_DIR/kryptic_robotics_bridge.py
directory=$SUITE_DIR
environment=CYCLONEDDS_URI="file://$SUITE_DIR/config/cyclonedds.xml",PYTHONUNBUFFERED="1",JAX_PLATFORMS="cpu"
priority=25
autostart=true
autorestart=true
startsecs=2
stdout_logfile=$SUITE_DIR/logs/robotics_bridge.log
stderr_logfile=$SUITE_DIR/logs/robotics_bridge.err.log
EOF
fi

echo "=== [4/4] Restarting Omni Suite ==="
if command -v omni >/dev/null 2>&1; then
    omni restart
else
    "$SUITE_DIR/bin/omni" restart
fi
echo "Robotics upgrade active!"
