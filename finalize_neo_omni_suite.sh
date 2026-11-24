#!/usr/bin/env bash
set -euo pipefail

SUITE_DIR="$HOME/kryptic_omni_suite"
BREW_PREFIX="$(brew --prefix)"

mkdir -p "$SUITE_DIR"/{shared_vault,bin,config,logs,run}
mkdir -p "$SUITE_DIR/kai-007" "$SUITE_DIR/kryptic-agent"

echo "=== [1/5] Writing MacBook Neo (A18 Pro / 8GB / 256GB) Unified .env ==="
cat << 'EOF' > "$SUITE_DIR/.env"
# Hardware Profile: MacBook Neo (Apple A18 Pro / 8GB Unified RAM / 256GB SSD)
HARDWARE_PROFILE=macbook_neo_a18pro
MAX_UNIFIED_RAM_MB=5120
MLX_METAL_CACHE_LIMIT_MB=512

# Quantized 4-Bit Apple MLX Multimodal Roster
MLX_LLM_MODEL=mlx-community/Qwen2.5-3B-Instruct-4bit
MLX_VLM_MODEL=mlx-community/Qwen2-VL-2B-Instruct-4bit
MLX_STT_MODEL=mlx-community/whisper-tiny-mlx
MLX_TTS_MODEL=mlx-community/Kokoro-82M-bf16
MLX_VLM_UNLOAD_AFTER_USE=true

# Hybrid Local + Cloud Bursting (Set HYBRID_CLOUD_BURST=false for strict air-gapped offline mode)
HYBRID_CLOUD_BURST=true
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Zero-Copy IPC & Shared Tri-Modal Vault
ZENOH_ROUTER_ENDPOINT=tcp/127.0.0.1:7447
KRYPTIC_AGENT_URL=http://127.0.0.1:8000
OMNI_NEURAL_BUS_URL=http://127.0.0.1:8001
SHARED_VAULT_DB=~/kryptic_omni_suite/shared_vault/omni_memory.db
SQLITE_CACHE_KB=32000
EOF

ln -sf "$SUITE_DIR/.env" "$SUITE_DIR/kai-007/.env"
ln -sf "$SUITE_DIR/.env" "$SUITE_DIR/kryptic-agent/.env"

echo "=== [2/5] Installing A18 Pro Metal Memory Governor & Hybrid Router ==="
cat << 'EOF' > "$SUITE_DIR/mlx_neo_governor.py"
import gc
import os
import sys

def enforce_neo_memory_limits():
    """Caps MLX Metal cache for 8GB MacBook Neo unified memory safety."""
    try:
        import mlx.core as mx
        cache_mb = int(os.getenv("MLX_METAL_CACHE_LIMIT_MB", "512"))
        max_ram_mb = int(os.getenv("MAX_UNIFIED_RAM_MB", "5120"))
        mx.metal.set_cache_limit(cache_mb * 1024 * 1024)
        mx.metal.set_memory_limit(max_ram_mb * 1024 * 1024)
    except Exception as exc:
        print(f"[NeoGovernor] Warning: MLX Metal limit skipped ({exc})", file=sys.stderr)

def flush_mlx_buffers():
    """Reclaims Metal unified memory immediately after VLM screen/camera inference."""
    gc.collect()
    try:
        import mlx.core as mx
        mx.metal.clear_cache()
    except Exception:
        pass

if __name__ == "__main__":
    enforce_neo_memory_limits()
    print("[NeoGovernor] A18 Pro memory limits active.")
EOF

# Idempotently inject Neo Governor at the top of kai-007/brain.py
BRAIN_FILE="$SUITE_DIR/kai-007/brain.py"
if [ -f "$BRAIN_FILE" ] && ! grep -q "mlx_neo_governor" "$BRAIN_FILE"; then
    python3 -c '
import pathlib, os
brain = pathlib.Path(os.path.expanduser("~/kryptic_omni_suite/kai-007/brain.py"))
hook = (
    "import os as _os, sys as _sys\n"
    "_sys.path.insert(0, _os.path.expanduser(\"~/kryptic_omni_suite\"))\n"
    "try:\n"
    "    from mlx_neo_governor import enforce_neo_memory_limits as _enforce_neo\n"
    "    _enforce_neo()\n"
    "except Exception:\n"
    "    pass\n\n"
)
brain.write_text(hook + brain.read_text())
print("Injected A18 Pro Metal governor into kai-007/brain.py")
'
fi

echo "=== [3/5] Configuring Deterministic Supervisord (Zenoh -> main.py -> Neural Bus) ==="
cat << EOF > "$SUITE_DIR/config/supervisord.conf"
[unix_http_server]
file=$SUITE_DIR/run/supervisor.sock

[supervisord]
logfile=$SUITE_DIR/logs/supervisord.log
pidfile=$SUITE_DIR/run/supervisord.pid
childlogdir=$SUITE_DIR/logs

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://$SUITE_DIR/run/supervisor.sock

[program:zenoh_router]
command=$BREW_PREFIX/bin/zenohd -c $SUITE_DIR/config/zenoh_router.json5
priority=10
autostart=true
autorestart=true
startsecs=2
stdout_logfile=$SUITE_DIR/logs/zenohd.log
stderr_logfile=$SUITE_DIR/logs/zenohd.err.log

[program:kryptic_agent]
command=$SUITE_DIR/venv/bin/python main.py
directory=$SUITE_DIR/kryptic-agent
environment=CYCLONEDDS_URI="file://$SUITE_DIR/config/cyclonedds.xml",PYTHONUNBUFFERED="1",PYTHONPATH="$SUITE_DIR"
priority=15
autostart=true
autorestart=true
startsecs=3
stdout_logfile=$SUITE_DIR/logs/kryptic_agent.log
stderr_logfile=$SUITE_DIR/logs/kryptic_agent.err.log

[program:omni_neural_bus]
command=$SUITE_DIR/venv/bin/uvicorn omni_neural_bus:app --host 0.0.0.0 --port 8001
directory=$SUITE_DIR
environment=CYCLONEDDS_URI="file://$SUITE_DIR/config/cyclonedds.xml",PYTHONUNBUFFERED="1"
priority=20
autostart=true
autorestart=true
startsecs=2
stdout_logfile=$SUITE_DIR/logs/neural_bus.log
stderr_logfile=$SUITE_DIR/logs/neural_bus.err.log
EOF

echo "=== [4/5] Building Unified 'omni' Control CLI ==="
cat << 'EOF' > "$SUITE_DIR/bin/omni"
#!/usr/bin/env bash
set -e
SUITE_DIR="$HOME/kryptic_omni_suite"
CONF="$SUITE_DIR/config/supervisord.conf"
SOCK="$SUITE_DIR/run/supervisor.sock"

ensure_daemon() {
    if [ ! -S "$SOCK" ]; then
        supervisord -c "$CONF"
        sleep 2
    fi
}

case "${1:-status}" in
    up|start)
        ensure_daemon
        supervisorctl -c "$CONF" start all
        supervisorctl -c "$CONF" status
        ;;
    down|stop)
        [ -S "$SOCK" ] && supervisorctl -c "$CONF" stop all
        ;;
    restart)
        ensure_daemon
        supervisorctl -c "$CONF" reread
        supervisorctl -c "$CONF" update
        supervisorctl -c "$CONF" restart all
        supervisorctl -c "$CONF" status
        ;;
    status)
        ensure_daemon
        supervisorctl -c "$CONF" status
        echo "--- Neural Bus Health ---"
        curl -s http://127.0.0.1:8001/health || echo "Neural Bus starting..."
        echo ""
        ;;
    logs)
        tail -n 40 -f "$SUITE_DIR/logs/"*.log
        ;;
    chat)
        ensure_daemon
        source "$SUITE_DIR/venv/bin/activate"
        export PYTHONPATH="$SUITE_DIR:${PYTHONPATH:-}"
        cd "$SUITE_DIR/kai-007"
        python text_chat_loop.py
        ;;
    *)
        echo "Usage: omni {up|down|restart|status|logs|chat}"
        exit 1
        ;;
esac
EOF
chmod +x "$SUITE_DIR/bin/omni"

if ! grep -q "kryptic_omni_suite/bin" "$HOME/.zshrc" 2>/dev/null; then
    echo 'export PATH="$HOME/kryptic_omni_suite/bin:$PATH"' >> "$HOME/.zshrc"
fi

echo "=== [5/5] Starting All Services & Running Verification ==="
"$SUITE_DIR/bin/omni" restart
echo "=== Setup Complete! Open a new terminal tab (or run 'source ~/.zshrc') and type: omni chat ==="
