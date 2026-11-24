import json
import os
import sqlite3
import threading
import time
import zenoh
from jax import numpy as jnp, random as jr
from pymdp import utils
from pymdp.agent import Agent

SUITE_DIR = os.path.expanduser("~/kryptic_omni_suite")
DB_PATH = os.path.join(SUITE_DIR, "shared_vault", "omni_memory.db")
ZENOH_ENDPOINT = os.getenv("ZENOH_ROUTER_ENDPOINT", "tcp/127.0.0.1:7447")
HEARTBEAT_TIMEOUT_SEC = float(os.getenv("ROBOT_HEARTBEAT_TIMEOUT", "1.5"))

class KrypticActiveInferenceNode:
    def __init__(self, num_obs=(4, 4), num_states=(4, 2), num_controls=(4, 1)):
        key = jr.PRNGKey(42)
        keys = jr.split(key, 3)
        A = utils.random_A_array(keys, list(num_obs), list(num_states))
        B = utils.random_B_array(keys, list(num_states), list(num_controls))
        C = utils.list_array_uniform([[no] for no in num_obs])

        self.agent = Agent(A=A, B=B, C=C, batch_size=1)
        self.qs = self.agent.D
        self.rng_key = jr.PRNGKey(0)
        self.last_heartbeat = time.monotonic()
        self.armed = False

        cfg = zenoh.Config.from_json5(json.dumps({"connect": {"endpoints": [ZENOH_ENDPOINT]}}))
        self.session = zenoh.open(cfg)

    def _log_vault(self, topic: str, payload: str):
        try:
            with sqlite3.connect(DB_PATH, timeout=3.0) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                cur = conn.execute(
                    "INSERT INTO omni_episodic_log (source, topic, payload) VALUES (?, ?, ?)",
                    ("kryptic-robotics", topic, payload),
                )
                conn.execute(
                    "INSERT INTO omni_fts (rowid, source, topic, payload) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, "kryptic-robotics", topic, payload),
                )
        except Exception:
            pass

    def on_heartbeat(self, sample):
        self.last_heartbeat = time.monotonic()
        try:
            data = json.loads(sample.payload.to_string())
            self.armed = bool(data.get("arm", True))
        except Exception:
            self.armed = True

    def on_preference_goal(self, sample):
        """Updates preferred observations (C-matrix) from kai-007 high-level goals."""
        try:
            data = json.loads(sample.payload.to_string())
            if "preferred_obs" in data:
                self.agent.C = [jnp.array([p], dtype=jnp.float32) for p in data["preferred_obs"]]
                self._log_vault("goal_update", json.dumps(data))
        except Exception as exc:
            self.session.put("kryptic/agent/active_inference/error", f"Goal error: {exc}")

    def on_sensor_obs(self, sample):
        if not self.armed or (time.monotonic() - self.last_heartbeat) > HEARTBEAT_TIMEOUT_SEC:
            self.armed = False
            self.session.put(
                "kryptic/agent/active_inference/action",
                json.dumps({"status": "HALTED_WATCHDOG", "action": [0, 0]}),
            )
            return

        try:
            data = json.loads(sample.payload.to_string())
            obs = [
                jnp.array([int(data.get("obs_0", 0))]),
                jnp.array([int(data.get("obs_1", 0))]),
            ]
            self.qs, info = self.agent.infer_states(obs, empirical_prior=self.qs, return_info=True)
            q_pi, efe = self.agent.infer_policies(self.qs)
            self.rng_key, subkey = jr.split(self.rng_key)
            action = self.agent.sample_action(q_pi, rng_key=subkey)

            out = {
                "status": "ACTIVE",
                "vfe": float(info["vfe"]),
                "efe": [float(x) for x in jnp.ravel(efe)],
                "action": [int(a) for a in action],
            }
            serialized = json.dumps(out)
            self.session.put("kryptic/agent/active_inference/action", serialized)
            self._log_vault("active_inference_step", serialized)
        except Exception as exc:
            self.session.put("kryptic/agent/active_inference/error", str(exc))

    def run(self):
        subs = [
            self.session.declare_subscriber("kryptic/agent/policy_control/heartbeat", self.on_heartbeat),
            self.session.declare_subscriber("kryptic/agent/active_inference/goal", self.on_preference_goal),
            self.session.declare_subscriber("kryptic/agent/sensors/discrete", self.on_sensor_obs),
        ]
        print(f"[KrypticRoboticsBridge] Online at {ZENOH_ENDPOINT} (Watchdog: {HEARTBEAT_TIMEOUT_SEC}s)")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            for s in subs:
                s.undeclare()
            self.session.close()

if __name__ == "__main__":
    KrypticActiveInferenceNode().run()
      
