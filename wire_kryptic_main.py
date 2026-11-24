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
