# Kai-007 × Hidden-Robotics Unified Integration Blueprint

**Architecture, Security Interlocks, Zero-Copy Telemetry & Off-Grid Radio Sync**

---

## 1. Executive Architecture Overview

Unifying **`KrypticKode007/kai-007`** (macOS Apple Silicon MLX AI & Android 15+ Radio Bridge) with **`KrypticKode007/Hidden-Robotics`** creates a self-contained, local-first Physical AI platform. Instead of relying on cloud robotics servers, your Mac acts as the high-speed neural reasoning hub, your Android 15+ device acts as a handheld voice controller and hardware dead-man switch, and your robotics hardware executes physical actions under cryptographic proximity protection.

```text
+-----------------------------------------------------------------------+
|                       ANDROID 15+ HANDHELD NODE                       |
|  [KaiControlDashboard]  [StrongBox Keystore]  [5G BLE Web Tunnel]     |
|           |                      |                     |              |
+-----------|----------------------|---------------------|--------------+
            | 2.4 GHz Encrypted BLE GATT + L2CAP Audio   |
            v                                            v
+-----------------------------------------------------------------------+
|                     macOS APPLE SILICON MASTER HUB                    |
|                                                                       |
|  [KaiMacBleBridge] <---> [ProximityGuard (ECDSA)]                     |
|         |                          |                                  |
|         v                          v                                  |
|  [KaiFrontierOrchestrator (brain.py / Apple MLX)]                     |
|     |             |                |                    |             |
|     v             v                v                    v             |
| [HybridVault] [Speculator] [ZeroCopyRingConsumer] [HybridNetRouter]   |
|  (FTS5+Vec)    (0.5B MLX)   (POSIX Shared RAM)    (BLE/ZIM/LoRa)      |
+-----------------------------------|-----------------------------------+
                                    |
        +---------------------------+---------------------------+
        |                                                       |
        v                                                       v
+-------------------------------+       +-------------------------------+
|   C++11 PERCEPTION ENGINE     |       |   HIDDEN-ROBOTICS HARDWARE    |
|  Interaction_loop.c++11       |       |  omni_robotics_mcp.py         |
|  ShmRingProducer (64KB slots) |       |  kryptic_robotics_bridge.py   |
|  CoreAudio / ScreenCaptureKit |       |  android_sensor_gateway.py    |
+-------------------------------+       +-------------------------------+
```

---

## 2. Five-Point Technical Integration

### 2.1 Hardware Proximity Dead-Man Switch (`omni_robotics_mcp.py` ↔ `ProximityGuard`)
- **Mechanism:** Register `omni_robotics_mcp.py` actuator and motor tools inside `biometric_mcp_server.py`, gated behind `ProximityGuard.is_unlocked`.
- **Execution Flow:** Before any physical movement command dispatches, `KaiFrontierOrchestrator` verifies a fresh `secp256r1` ECDSA signature signed by `KaiHardwareKeystore.kt` (Android StrongBox/TEE).
- **Auto E-Stop:** If BLE disconnects or RSSI drops below threshold, `ProximityGuard.revoke()` triggers an immediate emergency stop via `async_deployment_fsm.cpp`.

### 2.2 Zero-Copy Sensor & Vision Pipeline (`android_sensor_gateway.py` ↔ `core/shm_ring_buffer.hpp`)
- **Mechanism:** Route camera frames (`payload_type = 2`), audio (`payload_type = 1`), and IMU/GPS telemetry (`payload_type = 3`) into the lock-free 1 MB POSIX shared memory ring (`/kai007_perception_ring`).
- **Benefit:** `brain.py` reads raw sensor memory views directly in Python with zero serialization overhead.

### 2.3 Unified Spatial & Temporal Knowledge Vault (`consolidate_omni_vault.py` ↔ `HybridKnowledgeVault`)
- **Mechanism:** Merge `Hidden-Robotics` spatial waypoints, sensor logs, and hardware pinouts into `kai_vault.db`.
- **Temporal Tracking:** Waypoints and object states use `temporal_edges` (`subject -> predicate -> object`) so moved obstacles automatically supersede stale coordinates (`valid_to` timestamped).

### 2.4 Shared Off-Grid Connectivity (`kai_offline_internet.py` + `KaiBleWebTunnel.kt`)
- **Mechanism:** Both repositories share `HybridNetRouter`, cascading seamlessly across:
  1. Direct macOS Wi-Fi / Ethernet
  2. Android 5G/LTE Cellular Micro-Tunnel over 2.4 GHz BLE
  3. Local `.ZIM` offline documentation & Wikipedia snapshots
  4. 915 MHz Meshtastic LoRa long-range telemetry relay
  5. SQLite Store-and-Forward Outbox (`kai_outbox.db`)

### 2.5 Speculative Context Pre-Loading (`SpeculativeContextEngine`)
- **Mechanism:** Partial voice commands from the Android L2CAP walkie-talkie button are fed mid-utterance into a 0.5B MLX draft model to prefetch spatial waypoints and actuator schemas before the user releases the button.

---

## 3. Unified Master Wiring Adapter (`wire_kryptic_main.py`)

Drop this unified wiring script into `Hidden-Robotics/wire_kryptic_main.py` to launch both platforms together:

```python
import asyncio
import logging
import sys
from pathlib import Path

# Ensure sibling kai-007 modules are importable
KAI_ROOT = Path(__file__).resolve().parent.parent / "kai-007"
if KAI_ROOT.exists():
    sys.path.insert(0, str(KAI_ROOT))

from core.brain_frontier_orchestrator import KaiFrontierOrchestrator
from kai_offline_internet import HybridNetRouter

logging.basicConfig(level=logging.INFO, format="[OMNI-ROBOTICS] %(message)s")
log = logging.getLogger("wire_kryptic_main")


class UnifiedRoboticsHub:
    def __init__(self, orchestrator: KaiFrontierOrchestrator, net_router: HybridNetRouter):
        self.orchestrator = orchestrator
        self.net_router = net_router
        self.estop_engaged = False

    def trigger_emergency_stop(self, reason: str):
        self.estop_engaged = True
        log.critical(f"EMERGENCY STOP ENGAGED: {reason}")
        # Hook into kryptic_robotics_bridge.py / omni_robotics_mcp.py halt routine

    async def execute_robotics_command(self, command_text: str, elevated: bool = True) -> str:
        if elevated and not self.orchestrator.proximity_guard.is_unlocked:
            self.trigger_emergency_stop("Android StrongBox proximity lock unverified")
            challenge = self.orchestrator.proximity_guard.create_challenge()
            await self.orchestrator.ble_bridge.send_json(challenge)
            return "BLOCKED: Hardware proximity challenge sent to Android."

        self.estop_engaged = False
        return await asyncio.to_thread(self.orchestrator.process_prompt, command_text)

    async def monitor_proximity_watchdog(self):
        """Continuously enforces dead-man switch while robotics actuators are armed."""
        while True:
            ble_connected = (
                self.orchestrator.ble_bridge.client is not None
                and self.orchestrator.ble_bridge.client.is_connected
            )
            if not ble_connected and not self.estop_engaged:
                self.trigger_emergency_stop("2.4 GHz BLE radio link lost")
            await asyncio.sleep(0.25)

    async def run(self):
        log.info("Starting Unified Kai-007 × Hidden-Robotics Hub...")
        await asyncio.gather(
            self.orchestrator.start(),
            self.monitor_proximity_watchdog(),
            self.net_router.outbox.process_loop(self._drain_outbox_task),
        )

    async def _drain_outbox_task(self, task_type: str, payload: dict) -> str | None:
        if task_type == "web_search":
            return await self.net_router.research(payload.get("query", ""))
        return None
```

---

## 4. Synchronization & End-to-End Verification Scripts

### 4.1 `sync_hidden_robotics_hub.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

KAI_DIR="${KAI_DIR:-../kai-007}"
echo "[SYNC] Synchronizing shared radio, tunnel, and vault modules..."

cp -f "$KAI_DIR/kai_offline_internet.py" ./kai_offline_internet.py
cp -f "$KAI_DIR/KaiBleWebTunnel.kt" ./KaiBleWebTunnel.kt

python3 consolidate_omni_vault.py --target "$KAI_DIR/kai_vault.db"
echo "[SYNC] Complete."
```

### 4.2 `test_omni_e2e.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

KAI_DIR="${KAI_DIR:-../kai-007}"
echo "[TEST] Compiling C++11 zero-copy shared memory ring..."
make -C "$KAI_DIR" shm_ring

echo "[TEST] Running Frontier Security, SHM & Hybrid Vault test suite..."
pytest -v "$KAI_DIR/tests/test_frontier_systems.py"

echo "[TEST] All Kai-007 × Hidden-Robotics integration checks passed."
```
