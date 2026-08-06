"""SQLite store for approval cards (same DB file as OKF)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agent_anystack.hitl.card import ApprovalCard, ApprovalDecision, ApprovalStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_cards (
    id TEXT PRIMARY KEY,
    tag TEXT NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    team TEXT NOT NULL,
    project_id TEXT,
    summary TEXT NOT NULL,
    action_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT,
    decision TEXT,
    note TEXT,
    effective_autonomy INTEGER,
    gate TEXT
);
CREATE INDEX IF NOT EXISTS idx_appr_status ON approval_cards(status);
CREATE INDEX IF NOT EXISTS idx_appr_created ON approval_cards(created_at);
"""

_ALTERS = (
    "ALTER TABLE approval_cards ADD COLUMN effective_autonomy INTEGER",
    "ALTER TABLE approval_cards ADD COLUMN gate TEXT",
)


class ApprovalStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            for stmt in _ALTERS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.commit()
        finally:
            conn.close()

    def upsert(self, card: ApprovalCard) -> ApprovalCard:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO approval_cards (
                    id, tag, status, run_id, agent_id, user_id, team, project_id,
                    summary, action_type, created_at, decided_at, decided_by,
                    decision, note, effective_autonomy, gate
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    tag=excluded.tag,
                    status=excluded.status,
                    run_id=excluded.run_id,
                    agent_id=excluded.agent_id,
                    user_id=excluded.user_id,
                    team=excluded.team,
                    project_id=excluded.project_id,
                    summary=excluded.summary,
                    action_type=excluded.action_type,
                    created_at=excluded.created_at,
                    decided_at=excluded.decided_at,
                    decided_by=excluded.decided_by,
                    decision=excluded.decision,
                    note=excluded.note,
                    effective_autonomy=excluded.effective_autonomy,
                    gate=excluded.gate
                """,
                (
                    card.id,
                    card.tag,
                    card.status.value,
                    card.run_id,
                    card.agent_id,
                    card.user_id,
                    card.team,
                    card.project_id,
                    card.summary,
                    card.action_type,
                    card.created_at,
                    card.decided_at,
                    card.decided_by,
                    card.decision.value if card.decision else None,
                    card.note,
                    card.effective_autonomy,
                    card.gate,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return card

    def get(self, approval_id: str) -> ApprovalCard | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM approval_cards WHERE id = ?",
                (approval_id,),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_card(row) if row else None

    def list_cards(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 50,
    ) -> list[ApprovalCard]:
        sql = "SELECT * FROM approval_cards"
        params: list[object] = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [_row_to_card(r) for r in rows]


def _row_to_card(row: sqlite3.Row) -> ApprovalCard:
    decision_raw = row["decision"]
    keys = row.keys()
    eff = row["effective_autonomy"] if "effective_autonomy" in keys else None
    gate = row["gate"] if "gate" in keys else None
    return ApprovalCard(
        id=row["id"],
        tag=row["tag"],
        status=ApprovalStatus(row["status"]),
        run_id=row["run_id"],
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        team=row["team"],
        project_id=row["project_id"],
        summary=row["summary"],
        action_type=row["action_type"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        decision=ApprovalDecision(decision_raw) if decision_raw else None,
        note=row["note"],
        effective_autonomy=int(eff) if eff is not None else None,
        gate=gate,
    )
