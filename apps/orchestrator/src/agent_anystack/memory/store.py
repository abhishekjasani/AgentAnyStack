"""SQLite OKF store — hot path for shared team facts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from agent_anystack.memory.fact import OkfFact


_SCHEMA = """
CREATE TABLE IF NOT EXISTS okf_facts (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    scope TEXT NOT NULL,
    projects_json TEXT NOT NULL DEFAULT '[]',
    body TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    domain TEXT NOT NULL DEFAULT 'general',
    created_by_user TEXT NOT NULL,
    created TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    sensitivity TEXT NOT NULL DEFAULT 'internal',
    source_run TEXT
);
CREATE INDEX IF NOT EXISTS idx_okf_scope_arch ON okf_facts(scope, archived);
"""


def sqlite_path_from_database_url(database_url: str) -> Path:
    """sqlite:///./data/office.db → Path; also handles sqlite:////data/office.db."""
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"unsupported DATABASE_URL for OKF (need sqlite): {database_url}")
    raw = database_url.removeprefix("sqlite:///")
    return Path(raw)


class OkfStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def upsert(self, fact: OkfFact) -> OkfFact:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO okf_facts (
                    id, type, scope, projects_json, body, tags_json, domain,
                    created_by_user, created, pinned, archived, sensitivity, source_run
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type=excluded.type,
                    scope=excluded.scope,
                    projects_json=excluded.projects_json,
                    body=excluded.body,
                    tags_json=excluded.tags_json,
                    domain=excluded.domain,
                    created_by_user=excluded.created_by_user,
                    created=excluded.created,
                    pinned=excluded.pinned,
                    archived=excluded.archived,
                    sensitivity=excluded.sensitivity,
                    source_run=excluded.source_run
                """,
                (
                    fact.id,
                    fact.type.value,
                    fact.scope,
                    json.dumps(fact.projects),
                    fact.body,
                    json.dumps(fact.tags),
                    fact.domain,
                    fact.created_by_user,
                    fact.created,
                    1 if fact.pinned else 0,
                    1 if fact.archived else 0,
                    fact.sensitivity.value,
                    fact.source_run,
                ),
            )
            conn.commit()
        return fact

    def get(self, fact_id: str) -> OkfFact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM okf_facts WHERE id = ?",
                (fact_id,),
            ).fetchone()
        return _row_to_fact(row) if row else None

    def list_team_facts(
        self,
        team: str,
        *,
        include_archived: bool = False,
    ) -> list[OkfFact]:
        scope = f"team:{team}"
        sql = "SELECT * FROM okf_facts WHERE scope = ?"
        params: list[object] = [scope]
        if not include_archived:
            sql += " AND archived = 0"
        sql += " ORDER BY pinned DESC, created DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_fact(r) for r in rows]

    def archive(self, fact_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE okf_facts SET archived = 1 WHERE id = ?",
                (fact_id,),
            )
            conn.commit()
            return cur.rowcount > 0


def _row_to_fact(row: sqlite3.Row) -> OkfFact:
    return OkfFact(
        id=row["id"],
        type=row["type"],
        scope=row["scope"],
        projects=json.loads(row["projects_json"] or "[]"),
        body=row["body"],
        tags=json.loads(row["tags_json"] or "[]"),
        domain=row["domain"],
        created_by_user=row["created_by_user"],
        created=row["created"],
        pinned=bool(row["pinned"]),
        archived=bool(row["archived"]),
        sensitivity=row["sensitivity"],
        source_run=row["source_run"],
    )
