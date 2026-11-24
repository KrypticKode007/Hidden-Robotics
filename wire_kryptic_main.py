cat << 'EOF' > ~/kryptic_omni_suite/wire_kryptic_main.py
import ast
import os
import pathlib
import shutil
import sys

SUITE_DIR = pathlib.Path(os.path.expanduser("~/kryptic_omni_suite"))
MAIN_PY = SUITE_DIR / "kryptic-agent" / "main.py"
BACKUP_PY = SUITE_DIR / "kryptic-agent" / "main.py.bak"

HOOK_MARKER = "# === KRYPTIC OMNI-SUITE AUTO-WIRED CLIENT ==="

FASTAPI_APPENDIX = f"""

{HOOK_MARKER}
import os as _omni_os
import sys as _omni_sys
_omni_sys.path.insert(0, _omni_os.path.expanduser("~/kryptic_omni_suite"))

from pydantic import BaseModel as _OmniBaseModel
from kryptic_agent_client import KrypticAgentClient as _KrypticAgentClient

_kryptic_client = _KrypticAgentClient()

class _GoalPayload(_OmniBaseModel):
    preferred_obs: list[list[float]]

class _ObsPayload(_OmniBaseModel):
    obs_0: int
    obs_1: int

@app.post("/robotics/arm")
async def _omni_arm_robotics():
    _kryptic_client.start_heartbeat(interval_sec=0.5)
    return {{"status": "ARMED", "watchdog": "active"}}

@app.post("/robotics/disarm")
async def _omni_disarm_robotics():
    _kryptic_client.stop_heartbeat()
    return {{"status": "DISARMED"}}

@app.post("/robotics/goal")
async def _omni_set_goal(payload: _GoalPayload):
    _kryptic_client.send_goal(payload.preferred_obs)
    return {{"status": "GOAL_DISPATCHED", "preferred_obs": payload.preferred_obs}}

@app.post("/robotics/observe")
async def _omni_publish_obs(payload: _ObsPayload):
    _kryptic_client.publish_sensor_reading(payload.obs_0, payload.obs_1)
    return {{"status": "OBSERVATION_SENT", "obs": [payload.obs_0, payload.obs_1]}}
"""

def detect_fastapi_app(source: str) -> str | None:
    """Finds the variable name assigned to FastAPI() in main.py."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            func_name = getattr(func, "id", None) or getattr(func, "attr", None)
            if func_name == "FastAPI" and node.targets:
                target = node.targets
                if isinstance(target, ast.Name):
                    return target.id
    return None

def wire_main():
    if not MAIN_PY.exists():
        print(f"Error: {MAIN_PY} not found. Verify kryptic-agent is cloned.", file=sys.stderr)
        sys.exit(1)

    source = MAIN_PY.read_text(encoding="utf-8")
    if HOOK_MARKER in source:
        print("kryptic-agent/main.py is already wired with KrypticAgentClient.")
        return

    shutil.copy2(MAIN_PY, BACKUP_PY)
    print(f"Backup created at {BACKUP_PY}")

    app_var = detect_fastapi_app(source)
    if app_var:
        patched_appendix = FASTAPI_APPENDIX.replace("@app.", f"@{app_var}.")
        # Insert before `if __name__ == "__main__":` so Uvicorn picks up the new routes
        guard = 'if __name__ == "__main__":'
        if guard in source:
            head, tail = source.split(guard, 1)
            new_source = head + patched_appendix + "\n\n" + guard + tail
        else:
            new_source = source + patched_appendix

        MAIN_PY.write_text(new_source, encoding="utf-8")
        print(f"Successfully wired KrypticAgentClient onto FastAPI `{app_var}` in {MAIN_PY}")
    else:
        # Fallback if main.py uses a custom loop instead of FastAPI
        header = (
            f"{HOOK_MARKER}\n"
            "import os as _omni_os, sys as _omni_sys\n"
            '_omni_sys.path.insert(0, _omni_os.path.expanduser("~/kryptic_omni_suite"))\n'
            "from kryptic_agent_client import KrypticAgentClient as _KrypticAgentClient\n"
            "kryptic_client = _KrypticAgentClient()\n\n"
        )
        MAIN_PY.write_text(header + source, encoding="utf-8")
        print(f"Injected `kryptic_client` instance at top of {MAIN_PY} (non-FastAPI loop detected).")

if __name__ == "__main__":
    wire_main()
EOF

source ~/kryptic_omni_suite/venv/bin/activate
python ~/kryptic_omni_suite/wire_kryptic_main.py
omni restart
