import os
import sqlite3

DB_PATH = os.path.expanduser("~/kryptic_omni_suite/shared_vault/omni_memory.db")

def consolidate_vault(retention_days: int = 7):
    if not os.path.exists(DB_PATH):
        print("Vault database not initialized yet.")
        return

    with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
        before_count = conn.execute("SELECT COUNT(*) FROM omni_episodic_log").fetchone()[0]

        # Prune high-frequency raw telemetry older than retention_days while keeping goals and manual notes
        conn.execute(
            """
            DELETE FROM omni_episodic_log
            WHERE topic = 'active_inference_step'
              AND ts < datetime('now', ?)
            """,
            (f"-{retention_days} days",),
        )

        # Rebuild FTS5 index to reclaim dead space
        conn.execute("INSERT INTO omni_fts(omni_fts) VALUES('rebuild');")

        # Truncate WAL journal to keep 256GB SSD footprint minimal
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.execute("PRAGMA optimize;")

        after_count = conn.execute("SELECT COUNT(*) FROM omni_episodic_log").fetchone()[0]

    print(f"[VaultConsolidator] Rows before: {before_count} | Rows after: {after_count} | WAL truncated.")

if __name__ == "__main__":
    consolidate_vault()
