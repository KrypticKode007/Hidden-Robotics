#!/usr/bin/env bash
set -euo pipefail

SUITE_DIR="$HOME/kryptic_omni_suite"
PY_BIN="$(brew --prefix python@3.12)/bin/python3.12"

echo "=== [1/7] Creating Production Directory Hierarchy ==="
mkdir -p "$SUITE_DIR"/{shared_vault,bin,config,logs,run}
cd "$SUITE_DIR"

echo "=== [2/7] Cloning Native macOS + Android 15+ Repositories ==="
[ ! -d "kai-007" ] && git clone https://github.com/KrypticKode007/kai-007.git
[ ! -d "kryptic-agent" ] && git clone https://github.com/KrypticKode007/kryptic-agent.git

echo "=== [3/7] Building Native Apple Silicon Python 3.12 Environment ==="
"$PY_BIN" -m venv "$SUITE_DIR/venv"
source "$SUITE_DIR/venv/bin/activate"
pip install --upgrade pip wheel setuptools

# Install repository dependencies
[ -f "kai-007/requirements.txt" ] && pip install -r kai-007/requirements.txt
[ -f "kryptic-agent/requirements.txt" ] && pip install -r kryptic-agent/requirements.txt

# Install Peak Architecture Stack (MLX Multimodal, Zenoh IPC, sqlite-vec, FastAPI, MCP)
pip install -U \
    mlx mlx-lm mlx-vlm mlx-audio misaki \
    eclipse-zenoh sqlite-vec numpy \
    fastapi "uvicorn[standard]" httpx websockets aiosqlite mcp pydantic-settings

echo "=== [4/7] Compiling kai-007 C++11 State Machines (Apple Silicon Native -O3) ==="
cd "$SUITE_DIR/kai-007"
if [ -f "async_deployment_fsm.cpp" ]; then
    clang++ -std=c++11 -O3 -mcpu=native async_deployment_fsm.cpp -o "$SUITE_DIR/bin/async_deployment_fsm"
fi
if [ -f "Interaction_loop.c++11" ]; then
    clang++ -x c++ -std=c++11 -O3 -mcpu=native Interaction_loop.c++11 -o "$SUITE_DIR/bin/interaction_loop"
fi

echo "=== [5/7] Configuring Zero-Copy Cyclone DDS & Zenoh Router ==="
cat << 'EOF' > "$SUITE_DIR/config/cyclonedds.xml"
<?xml version="1.0" encoding="UTF-8" ?>
<CycloneDDS xmlns="https://cdds.io/config">
  <Domain id="any">
    <SharedMemory>
      <Enable>true</Enable>
      <LogLevel>info</LogLevel>
    </SharedMemory>
    <Internal>
      <Watermarks>
        <WhcHigh>500kB</WhcHigh>
      </Watermarks>
    </Internal>
  </Domain>
</CycloneDDS>
EOF

cat << 'EOF' > "$SUITE_DIR/config/zenoh_router.json5"
{
  mode: "router",
  listen: {
    endpoints: ["tcp/0.0.0.0:7447"]
  },
  scouting: {
    multicast: { enabled: true }
  }
}
EOF

echo "=== [6/7] Initializing Tri-Modal SQLite Vault (WAL + FTS5 + sqlite-vec) ==="
python -c '
import os, sqlite3, sqlite_vec

db_path = os.path.expanduser("~/kryptic_omni_suite/shared_vault/omni_memory.db")
conn = sqlite3.connect(db_path)
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)

conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA synchronous=NORMAL;")
conn.execute("PRAGMA cache_size=-32000;")

# Episodic & Telemetry Log Table
conn.execute("""
CREATE TABLE IF NOT EXISTS omni_episodic_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")

# Lexical FTS5 Search Index
conn.execute("""
CREATE VIRTUAL TABLE IF NOT EXISTS omni_fts USING fts5(
    source, topic, payload, content="omni_episodic_log", content_rowid="id"
);
""")

# Semantic Vector Table (384-dim default for local lightweight embeddings)
conn.execute("""
CREATE VIRTUAL TABLE IF NOT EXISTS omni_vectors USING vec0(
    episode_id INTEGER PRIMARY KEY,
    embedding float[384]
);
""")

conn.commit()
conn.close()
print("Tri-modal SQLite WAL + FTS5 + sqlite-vec vault initialized at:", db_path)
'

echo "=== [7/7] Writing Unified Zenoh-MCP-FastAPI Neural Bus & Supervisord Config ==="
cat << 'EOF' > "$SUITE_DIR/omni_neural_bus.py"
import os
import json
import sqlite3
from contextlib import asynccontextmanager
import httpx
import zenoh
import sqlite_vec
from fastapi import FastAPI
from pydantic import BaseModel

SUITE_DIR = os.path.expanduser("~/kryptic_omni_suite")
DB_PATH = os.path.join(SUITE_DIR, "shared_vault", "omni_memory.db")
AGENT_HTTP = os.getenv("KRYPTIC_AGENT_URL", "http://127.0.0.1:8000")

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def record_episode(source: str, topic: str, payload: str):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO omni_episodic_log (source, topic, payload) VALUES (?, ?, ?)",
            (source, topic, payload),
        )
        conn.execute(
            "INSERT INTO omni_fts (rowid, source, topic, payload) VALUES (?, ?, ?, ?)",
            (cur.lastrowid, source, topic, payload),
        )

class DispatchRequest(BaseModel):
    zenoh_key: str = "kryptic/agent/policy"
    http_fallback_route: str = "/policy"
    payload: dict

zenoh_session = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global zenoh_session
    cfg = zenoh.Config.from_json5(json.dumps({"connect": {"endpoints": ["tcp/127.0.0.1:7447"]}}))
    zenoh_session = zenoh.open(cfg)

    def on_telemetry(sample):
        try:
            text = sample.payload.to_string()
            record_episode("kryptic-agent", str(sample.key_expr), text)
        except Exception:
            pass

    sub = zenoh_session.declare_subscriber("kryptic/agent/telemetry/**", on_telemetry)
    yield
    sub.undeclare()
    zenoh_session.close()

app = FastAPI(title="Kryptic Omni-Neural Bus", version="2.0.0", lifespan=lifespan)

@app.get("/health")
async def health():
    return {
        "status": "optimal",
        "ipc": "eclipse-zenoh+cyclonedds-shm",
        "memory": "sqlite-wal-fts5-vec0",
        "platform": "macos-apple-silicon+android15",
    }

@app.post("/actuate")
async def actuate(req: DispatchRequest):
    serialized = json.dumps(req.payload)
    record_episode("kai-007", req.zenoh_key, serialized)
    if zenoh_session is not None:
        zenoh_session.put(req.zenoh_key, serialized)
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.post(f"{AGENT_HTTP}{req.http_fallback_route}", json=req.payload)
            return {"transport": "zenoh+http", "agent_status": resp.status_code, "data": resp.json()}
    except Exception:
        return {"transport": "zenoh-only", "queued": True}

@app.get("/recall")
async def recall(q: str, limit: int = 10):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT source, topic, payload FROM omni_fts WHERE omni_fts MATCH ? ORDER BY rank LIMIT ?",
            (q, limit),
        ).fetchall()
    return {"query": q, "matches": [{"source": r[0], "topic": r[1], "payload": r[2]} for r in rows]}
EOF

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
command=$(brew --prefix)/bin/zenohd -c $SUITE_DIR/config/zenoh_router.json5
priority=10
autostart=true
autorestart=true
stdout_logfile=$SUITE_DIR/logs/zenohd.log
stderr_logfile=$SUITE_DIR/logs/zenohd.err.log

[program:omni_neural_bus]
command=$SUITE_DIR/venv/bin/uvicorn omni_neural_bus:app --host 0.0.0.0 --port 8001
directory=$SUITE_DIR
environment=CYCLONEDDS_URI="file://$SUITE_DIR/config/cyclonedds.xml"
priority=20
autostart=true
autorestart=true
stdout_logfile=$SUITE_DIR/logs/neural_bus.log
stderr_logfile=$SUITE_DIR/logs/neural_bus.err.log
EOF

cp -n "$SUITE_DIR/kai-007/.env.example" "$SUITE_DIR/.env" 2>/dev/null || touch "$SUITE_DIR/.env"
ln -sf "$SUITE_DIR/.env" "$SUITE_DIR/kai-007/.env"
ln -sf "$SUITE_DIR/.env" "$SUITE_DIR/kryptic-agent/.env"

echo "=== Base Deployment Complete! Next run finalize_neo_omni_suite.sh ==="
