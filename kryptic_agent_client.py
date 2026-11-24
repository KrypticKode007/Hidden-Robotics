import json
import os
import threading
import time
import zenoh

ZENOH_ENDPOINT = os.getenv("ZENOH_ROUTER_ENDPOINT", "tcp/127.0.0.1:7447")

class KrypticAgentClient:
    """Drop-in client linking kai-007 and kryptic-agent/main.py over Zenoh."""

    def __init__(self):
        cfg = zenoh.Config.from_json5(json.dumps({"connect": {"endpoints": [ZENOH_ENDPOINT]}}))
        self.session = zenoh.open(cfg)
        self._hb_running = False
        self._hb_thread = None

    def start_heartbeat(self, interval_sec: float = 0.5):
        """Starts background safety heartbeat so physical actuators remain armed."""
        if self._hb_running:
            return
        self._hb_running = True

        def _pulse():
            while self._hb_running:
                self.session.put(
                    "kryptic/agent/policy_control/heartbeat",
                    json.dumps({"arm": True, "ts": time.time()}),
                )
                time.sleep(interval_sec)

        self._hb_thread = threading.Thread(target=_pulse, daemon=True)
        self._hb_thread.start()

    def stop_heartbeat(self):
        """Immediately disarms actuators via watchdog timeout."""
        self._hb_running = False
        self.session.put("kryptic/agent/policy_control/heartbeat", json.dumps({"arm": False}))

    def send_goal(self, preferred_obs: list[list[float]]):
        """Dispatches a high-level Active Inference target preference from kai-007."""
        self.session.put(
            "kryptic/agent/active_inference/goal",
            json.dumps({"preferred_obs": preferred_obs}),
        )

    def publish_sensor_reading(self, obs_0: int, obs_1: int):
        """Feeds discrete sensor states into the 1000Hz / JAX inference loop."""
        self.session.put(
            "kryptic/agent/sensors/discrete",
            json.dumps({"obs_0": obs_0, "obs_1": obs_1}),
        )

    def close(self):
        self.stop_heartbeat()
        self.session.close()
                  
