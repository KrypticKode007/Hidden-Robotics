import json
import os
import zenoh
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

ZENOH_ENDPOINT = os.getenv("ZENOH_ROUTER_ENDPOINT", "tcp/127.0.0.1:7447")
app = FastAPI(title="Android 15+ KaiBleWebTunnel Sensor Gateway", version="1.0.0")

cfg = zenoh.Config.from_json5(json.dumps({"connect": {"endpoints": [ZENOH_ENDPOINT]}}))
zenoh_session = zenoh.open(cfg)

class MobileTelemetry(BaseModel):
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 9.81
    proximity_cm: float = 100.0
    arm_requested: bool = False

def quantize_to_discrete_obs(data: MobileTelemetry) -> tuple[int, int]:
    """Maps continuous Android 15+ IMU and proximity sensors into 4-state discrete observations."""
    motion_mag = abs(data.accel_x) + abs(data.accel_y) + abs(data.accel_z - 9.81)
    if motion_mag < 0.5:
        obs_0 = 0  # Stationary
    elif motion_mag < 2.5:
        obs_0 = 1  # Gentle movement
    elif motion_mag < 6.0:
        obs_0 = 2  # Active motion
    else:
        obs_0 = 3  # High impact / rapid shift

    if data.proximity_cm < 10.0:
        obs_1 = 0  # Immediate obstacle
    elif data.proximity_cm < 40.0:
        obs_1 = 1  # Near object
    elif data.proximity_cm < 120.0:
        obs_1 = 2  # Mid-range clear
    else:
        obs_1 = 3  # Open space

    return obs_0, obs_1

@app.post("/mobile/telemetry")
async def ingest_http_telemetry(telemetry: MobileTelemetry):
    obs_0, obs_1 = quantize_to_discrete_obs(telemetry)
    zenoh_session.put("kryptic/agent/policy_control/heartbeat", json.dumps({"arm": telemetry.arm_requested}))
    zenoh_session.put("kryptic/agent/sensors/discrete", json.dumps({"obs_0": obs_0, "obs_1": obs_1}))
    return {"status": "streamed_to_zenoh", "discrete_obs": [obs_0, obs_1]}

@app.websocket("/ws/ble_tunnel")
async def ble_tunnel_websocket(ws: WebSocket):
    """Persistent low-latency tunnel for KaiBleWebTunnel.kt on Android 15+."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            payload = MobileTelemetry(**json.loads(raw))
            obs_0, obs_1 = quantize_to_discrete_obs(payload)
            zenoh_session.put("kryptic/agent/policy_control/heartbeat", json.dumps({"arm": payload.arm_requested}))
            zenoh_session.put("kryptic/agent/sensors/discrete", json.dumps({"obs_0": obs_0, "obs_1": obs_1}))
            await ws.send_text(json.dumps({"ack": True, "obs": [obs_0, obs_1]}))
    except WebSocketDisconnect:
        zenoh_session.put("kryptic/agent/policy_control/heartbeat", json.dumps({"arm": False}))
  
