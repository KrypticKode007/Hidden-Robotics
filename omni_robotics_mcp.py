import json
import os
import sqlite3
import sys
import time
import httpx
from mcp.server.fastmcp import FastMCP

SUITE_DIR = os.path.expanduser("~/kryptic_omni_suite")
sys.path.insert(0, SUITE_DIR)

from kryptic_agent_client import KrypticAgentClient

mcp = FastMCP("Kryptic-Hidden-Robotics-MCP")
NEURAL_BUS_URL = os.getenv("OMNI_NEURAL_BUS_URL", "http://127.0.0.1:8001")
DB_PATH = os.path.join(SUITE_DIR, "shared_vault", "omni_memory.db")

_client = KrypticAgentClient()

@mcp.tool()
def arm_robotics_system(heartbeat_interval_sec: float = 0.5) -> str:
    """Arms physical actuators and starts the dead-man Zenoh safety heartbeat."""
    _client.start_heartbeat(interval_sec=heartbeat_interval_sec)
    return f"Robotics system ARMED. Safety heartbeat pulsing every {heartbeat_interval_sec}s."

@mcp.tool()
def disarm_robotics_system() -> str:
    """Immediately halts all physical actuators and stops the safety heartbeat."""
    _client.stop_heartbeat()
    return "Robotics system DISARMED and placed in safe standby."

@mcp.tool()
def set_active_inference_goal(preferred_obs_json: str) -> str:
    """
    Sets preferred target observations (C-matrix) for the pymdp Active Inference loop.
    Example JSON: '[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]'
    """
    prefs = json.loads(preferred_obs_json)
    _client.send_goal(prefs)
    return f"Dispatched Active Inference goal preferences: {prefs}"

@mcp.tool()
def step_sensor_observation(obs_0: int, obs_1: int) -> str:
    """Feeds discrete sensor states into kryptic-agent's Active Inference loop."""
    _client.publish_sensor_reading(obs_0=obs_0, obs_1=obs_1)
    time.sleep(0.15)
    with sqlite3.connect(DB_PATH, timeout=3.0) as conn:
        row = conn.execute(
            "SELECT payload, ts FROM omni_episodic_log WHERE topic = 'active_inference_step' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row:
        return f"Latest inference output ({row[1]}): {row[0]}"
    return "Observation published; awaiting telemetry confirmation."

@mcp.tool()
def recall_omni_memory(query: str, limit: int = 5) -> str:
    """Searches the unified SQLite WAL + FTS5 memory vault across kai-007, kryptic-agent, and Hidden-Robotics."""
    with sqlite3.connect(DB_PATH, timeout=3.0) as conn:
        rows = conn.execute(
            "SELECT source, topic, payload, ts FROM omni_fts JOIN omni_episodic_log ON omni_fts.rowid = omni_episodic_log.id WHERE omni_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
    if not rows:
        return f"No memory entries matched '{query}'."
    return json.dumps(
        [{"source": r[0], "topic": r[1], "payload": r[2], "ts": r[3]} for r in rows],
        indent=2,
    )

if __name__ == "__main__":
    mcp.run()
  
