#!/usr/bin/env bash
set -euo pipefail

SUITE_DIR="$HOME/kryptic_omni_suite"
source "$SUITE_DIR/venv/bin/activate"
export PYTHONPATH="$SUITE_DIR:${PYTHONPATH:-}"

echo "=== [1/4] Checking Supervisord Daemons ==="
"$SUITE_DIR/bin/omni" status

echo "=== [2/4] Verifying A18 Pro Metal Memory Governor ==="
python "$SUITE_DIR/mlx_neo_governor.py"

echo "=== [3/4] Running End-to-End Zenoh + Active Inference + Watchdog Loop ==="
python - << 'EOF'
import json
import time
import zenoh
from kryptic_agent_client import KrypticAgentClient

received_actions = []

cfg = zenoh.Config.from_json5(json.dumps({"connect": {"endpoints": ["tcp/127.0.0.1:7447"]}}))
sub_session = zenoh.open(cfg)
sub = sub_session.declare_subscriber(
    "kryptic/agent/active_inference/action",
    lambda sample: received_actions.append(json.loads(sample.payload.to_string())),
)

client = KrypticAgentClient()
try:
    print(" -> Arming dead-man safety heartbeat...")
    client.start_heartbeat(interval_sec=0.3)
    time.sleep(0.6)

    print(" -> Dispatching high-level goal from kai-007...")
    client.send_goal([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
    time.sleep(0.3)

    print(" -> Streaming discrete sensor observation to kryptic-agent...")
    client.publish_sensor_reading(obs_0=1, obs_1=0)
    time.sleep(0.8)

    assert len(received_actions) > 0, "No Active Inference action received over Zenoh!"
    latest = received_actions[-1]
    assert latest.get("status") == "ACTIVE", f"Unexpected status: {latest}"
    print(f" -> SUCCESS! Received Action: {latest['action']} | Surprise (VFE): {latest['vfe']:.4f}")
finally:
    print(" -> Disarming safety heartbeat...")
    client.stop_heartbeat()
    time.sleep(0.3)
    sub.undeclare()
    sub_session.close()
    client.close()
EOF

echo "=== [4/4] Verifying SQLite WAL + FTS5 Shared Vault Recall ==="
curl -s "http://127.0.0"
echo ""
echo "=== ALL END-TO-END CHECKS PASSED ==="
