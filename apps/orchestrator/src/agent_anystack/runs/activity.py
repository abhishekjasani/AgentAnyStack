"""Short-lived run presence shared by server workers, without storing prompts."""

import json
import sqlite3
import time
from pathlib import Path


class ActivityStore:
    LEASE_SECONDS = 35

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS activity (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, heartbeat REAL NOT NULL)"
            )

    def _connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def put(self, run: dict):
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO activity VALUES (?, ?, ?)",
                (run["run_id"], json.dumps(run), time.time()),
            )

    def remove(self, run_id: str):
        with self._connect() as db:
            db.execute("DELETE FROM activity WHERE run_id = ?", (run_id,))

    def active(self) -> list[dict]:
        with self._connect() as db:
            db.execute(
                "DELETE FROM activity WHERE heartbeat < ?",
                (time.time() - self.LEASE_SECONDS,),
            )
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM activity ORDER BY heartbeat DESC"
                )
            ]
