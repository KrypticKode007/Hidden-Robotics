#!/usr/bin/env python3
"""
kai_offline_internet.py
Unified Offline-First Internet & Radio Connectivity Router for Kai-007.

Combines all four offline-internet strategies into a single cascading router:
  1. Direct Wi-Fi / Ethernet (when macOS is online)
  2. Bluetooth LE Cellular Micro-Tunnel (routes lightweight web fetches via paired Android 15+ 5G/LTE)
  3. Local .ZIM Snapshots (searches offline Wikipedia, StackOverflow & DevDocs archives on SSD)
  4. 915 MHz Meshtastic LoRa Relay (long-range off-grid radio queries to a home gateway node)
  5. Store-and-Forward Outbox (queues tasks in SQLite during total blackout & auto-drains on reconnect)
"""

import asyncio
import glob
import json
import logging
import re
import socket
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import uuid
from typing import Any, Awaitable, Callable

from bs4 import BeautifulSoup

# Optional hardware/archive libraries (loaded gracefully so the router works even if some aren't installed)
try:
    from libzim.reader import Archive
    from libzim.search import Query, Searcher
    HAS_LIBZIM = True
except ImportError:
    HAS_LIBZIM = False

try:
    from pubsub import pub
    import meshtastic.serial_interface
    HAS_MESHTASTIC = True
except ImportError:
    HAS_MESHTASTIC = False

logging.basicConfig(level=logging.INFO, format="[KAI-NET] %(message)s")
log = logging.getLogger("kai_offline_internet")


# ==============================================================================
# 1. BLUETOOTH LE CELLULAR MICRO-TUNNEL (Mac <-> Android 15+ 5G over 2.4 GHz BLE)
# ==============================================================================
class BleCellularTunnel:
    """Fetches live web pages through a paired Android phone's cellular data over BLE."""

    def __init__(self, ble_bridge: Any = None):
        self.ble_bridge = ble_bridge
        self._pending: dict[str, asyncio.Future] = {}

    def attach_bridge(self, ble_bridge: Any):
        self.ble_bridge = ble_bridge

    def resolve_response(self, msg: dict):
        """Hook into KaiMacBleBridge._notification_handler when msg.get('type') == 'web_fetch_result'."""
        req_id = msg.get("req_id")
        fut = self._pending.pop(req_id, None)
        if fut and not fut.done():
            fut.set_result(msg)

    async def fetch_url(self, url: str, timeout: float = 15.0) -> str | None:
        if not self.ble_bridge or not getattr(self.ble_bridge, "client", None):
            return None
        if not self.ble_bridge.client.is_connected:
            return None

        req_id = uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[req_id] = fut

        await self.ble_bridge.send_json({"type": "web_fetch", "req_id": req_id, "url": url})
        try:
            res = await asyncio.wait_for(fut, timeout=timeout)
            return res.get("text") if res.get("ok") else None
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return None

    async def search_web(self, query: str) -> str | None:
        encoded = urllib.parse.quote_plus(query)
        return await self.fetch_url(f"https://lite.duckduckgo.com/lite/?q={encoded}")


# ==============================================================================
# 2. LOCAL INTERNET SNAPSHOTS (Offline .ZIM Archives on Mac SSD)
# ==============================================================================
class LocalZimArchiveEngine:
    """Searches downloaded offline .zim archives (Wikipedia, StackOverflow, DevDocs)."""

    def __init__(self, zim_dir: str = "vault/zim_archives"):
        self.zim_dir = zim_dir
        self.archives: list[Any] = []
        if HAS_LIBZIM:
            for path in glob.glob(f"{zim_dir}/*.zim"):
                try:
                    self.archives.append(Archive(path))
                except Exception as exc:
                    log.warning(f"Could not open ZIM archive {path}: {exc}")

    def search(self, query_text: str, max_results: int = 3) -> list[dict[str, str]]:
        if not HAS_LIBZIM or not self.archives:
            return []

        hits: list[dict[str, str]] = []
        for archive in self.archives:
            try:
                searcher = Searcher(archive)
                search = searcher.search(Query().set_query(query_text))
                for path in search.getResults(0, max_results):
                    entry = archive.get_entry_by_path(path)
                    raw_html = bytes(entry.get_item().content).decode("utf-8", errors="ignore")
                    clean_text = re.sub(
                        r"\s+", " ", BeautifulSoup(raw_html, "html.parser").get_text()
                    ).strip()
                    hits.append({
                        "title": entry.title,
                        "snippet": clean_text[:2500],
                        "source": archive.filename,
                    })
                    if len(hits) >= max_results:
                        return hits
            except Exception as exc:
                log.warning(f"ZIM search error: {exc}")
        return hits


# ==============================================================================
# 3. LONG-RANGE 915 MHz LORA / MESHTASTIC RADIO RELAY
# ==============================================================================
class MeshtasticLoRaRelay:
    """Sends compressed queries over LoRa radio to a home Meshtastic internet gateway."""

    def __init__(self, home_node_id: str | None = None, serial_port: str | None = None):
        self.home_node_id = home_node_id
        self.serial_port = serial_port
        self.iface: Any = None
        self._pending: dict[str, asyncio.Future] = {}

    def connect(self) -> bool:
        if not HAS_MESHTASTIC or not self.home_node_id:
            return False
        try:
            self.iface = meshtastic.serial_interface.SerialInterface(devPath=self.serial_port)
            pub.subscribe(self._on_receive, "meshtastic.receive.text")
            log.info(f"Connected to Meshtastic LoRa radio (gateway={self.home_node_id}).")
            return True
        except Exception as exc:
            log.warning(f"Meshtastic radio unavailable: {exc}")
            self.iface = None
            return False

    def _on_receive(self, packet: dict, interface: Any = None):
        decoded = packet.get("decoded", {})
        text = decoded.get("text", "")
        # Expected reply format from home node: "KAI_ANS:<req_id>:<compressed_answer>"
        if text.startswith("KAI_ANS:"):
            parts = text.split(":", 2)
            if len(parts) == 3:
                req_id, answer = parts[1], parts[2]
                fut = self._pending.pop(req_id, None)
                if fut and not fut.done():
                    fut.get_loop().call_soon_threadsafe(fut.set_result, answer)

    async def query_over_lora(self, query: str, timeout: float = 25.0) -> str | None:
        if not self.iface or not self.home_node_id:
            return None

        req_id = uuid.uuid4().hex[:6]
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[req_id] = fut

        packet_str = f"KAI_REQ:{req_id}:{query[:160]}"
        try:
            self.iface.sendText(packet_str, destinationId=self.home_node_id, wantAck=True)
            return await asyncio.wait_for(fut, timeout=timeout)
        except Exception:
            self._pending.pop(req_id, None)
            return None


# ==============================================================================
# 4. STORE-AND-FORWARD SQLITE OUTBOX QUEUE
# ==============================================================================
class StoreAndForwardOutbox:
    """Queues internet tasks during total blackout and auto-executes them on reconnect."""

    def __init__(self, db_path: str = "kai_outbox.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                result TEXT,
                created_at REAL NOT NULL
            )
        """)
        self.conn.commit()

    def enqueue(self, task_type: str, payload: dict[str, Any]) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO outbox (task_type, payload, created_at) VALUES (?, ?, ?)",
            (task_type, json.dumps(payload), time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_completed_results(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, task_type, payload, result FROM outbox WHERE status = 'DONE' ORDER BY id ASC"
        ).fetchall()
        return [
            {
                "id": r[0],
                "task_type": r[1],
                "payload": json.loads(r[2]),
                "result": r[3],
            }
            for r in rows
        ]

    async def process_loop(
        self,
        executor_fn: Callable[[str, dict[str, Any]], Awaitable[str | None]],
        poll_interval: float = 10.0,
    ):
        """Continuously drains queued tasks whenever connectivity returns."""
        while True:
            rows = self.conn.execute(
                "SELECT id, task_type, payload FROM outbox WHERE status = 'PENDING' ORDER BY id ASC LIMIT 5"
            ).fetchall()

            for row_id, task_type, payload_str in rows:
                try:
                    res = await executor_fn(task_type, json.loads(payload_str))
                    if res is not None:
                        self.conn.execute(
                            "UPDATE outbox SET status = 'DONE', result = ? WHERE id = ?",
                            (res, row_id),
                        )
                        self.conn.commit()
                        log.info(f"Outbox task #{row_id} completed automatically.")
                except Exception:
                    pass  # Still offline; keep queued
            await asyncio.sleep(poll_interval)


# ==============================================================================
# 5. UNIFIED SMART CONNECTIVITY ROUTER
# ==============================================================================
class HybridNetRouter:
    """Cascades across Direct Web -> Android BLE -> Local ZIM -> LoRa -> Outbox Queue."""

    def __init__(
        self,
        ble_bridge: Any = None,
        zim_dir: str = "vault/zim_archives",
        lora_home_node_id: str | None = None,
        lora_serial_port: str | None = None,
        outbox_db_path: str = "kai_outbox.db",
    ):
        self.ble_tunnel = BleCellularTunnel(ble_bridge=ble_bridge)
        self.zim_engine = LocalZimArchiveEngine(zim_dir=zim_dir)
        self.lora_relay = MeshtasticLoRaRelay(
            home_node_id=lora_home_node_id, serial_port=lora_serial_port
        )
        self.outbox = StoreAndForwardOutbox(db_path=outbox_db_path)

    @staticmethod
    def has_direct_internet() -> bool:
        try:
            with socket.create_connection(("1.1.1.1", 53), timeout=1.5):
                return True
        except OSError:
            return False

    @staticmethod
    def _direct_web_search(query: str) -> str:
        url = f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote_plus(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Kai007/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            soup = BeautifulSoup(resp.read().decode("utf-8", errors="ignore"), "html.parser")
            clean = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
            return clean[:3500]

    async def research(self, query: str, allow_queue: bool = True) -> str:
        # Tier 1: Direct macOS Wi-Fi / Ethernet
        if self.has_direct_internet():
            try:
                text = await asyncio.to_thread(self._direct_web_search, query)
                return f"[Direct Web]\n{text}"
            except Exception as exc:
                log.warning(f"Direct web search failed, falling back: {exc}")

        # Tier 2: Android 15+ Cellular Micro-Tunnel over 2.4 GHz BLE
        ble_res = await self.ble_tunnel.search_web(query)
        if ble_res:
            return f"[Android BLE 5G Micro-Tunnel]\n{ble_res}"

        # Tier 3: Local Offline .ZIM Snapshot (Wikipedia / StackOverflow / Docs)
        zim_hits = await asyncio.to_thread(self.zim_engine.search, query, 2)
        if zim_hits:
            formatted = "\n".join(f"- {h['title']}: {h['snippet'][:800]}" for h in zim_hits)
            return f"[Offline ZIM Archive]\n{formatted}"

        # Tier 4: Long-Range 915 MHz Meshtastic LoRa Relay
        lora_res = await self.lora_relay.query_over_lora(query)
        if lora_res:
            return f"[915 MHz LoRa Radio Relay]\n{lora_res}"

        # Tier 5: Total Blackout -> Queue in Store-and-Forward Outbox
        if allow_queue:
            task_id = self.outbox.enqueue("web_search", {"query": query})
            return (
                f"[Offline Outbox Queued #{task_id}] No Wi-Fi, BLE, ZIM, or LoRa match available. "
                "Kai-007 will automatically fetch and save the answer when a signal returns."
            )
        return ""

    async def _drain_outbox_task(self, task_type: str, payload: dict[str, Any]) -> str | None:
        if task_type == "web_search":
            query = payload.get("query", "")
            res = await self.research(query, allow_queue=False)
            return res if res else None
        return None

    async def start_background_worker(self):
        """Starts the background outbox drain worker."""
        await self.outbox.process_loop(self._drain_outbox_task)


# ==============================================================================
# CLI QUICK TEST ENTRYPOINT
# ==============================================================================
async def _main():
    query = " ".join(sys.argv[1:]).strip() or "Apple MLX local inference"
    router = HybridNetRouter()
    print(f"Querying Kai-007 Hybrid Offline Router for: '{query}'\n")
    result = await router.research(query)
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
