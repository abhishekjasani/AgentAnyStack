"""Durable checkpoints for capability calls paused at human approval."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


def new_capability_call_id() -> str:
    return f"capcall-{uuid4().hex}"


@dataclass
class CapabilityCallRecord:
    capability_call_id: str
    approval_id: str | None
    run_id: str
    provider_tool_call_id: str
    agent_id: str
    user_id: str
    team: str
    project_id: str | None
    stack: str
    connection_id: str
    model: str
    max_tokens: int | None
    capability: dict
    binding_schema: dict
    callable_name: str
    arguments: str
    messages: list[dict]
    status: str = "pending"
    result: str | None = None
    error_stage: str | None = None
    error: str | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_calls (
    capability_call_id TEXT PRIMARY KEY,
    approval_id TEXT,
    run_id TEXT NOT NULL,
    provider_tool_call_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    team TEXT NOT NULL,
    project_id TEXT,
    stack TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    model TEXT NOT NULL,
    max_tokens INTEGER,
    capability_json TEXT NOT NULL,
    binding_schema_json TEXT NOT NULL,
    callable_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    messages_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error_stage TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_capability_calls_run ON capability_calls(run_id);
"""


class CapabilityCallStore:
    """Persists an approved invocation and its model conversation checkpoint."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def create_pending(self, record: CapabilityCallRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO capability_calls (
                    capability_call_id, approval_id, run_id, provider_tool_call_id, agent_id,
                    user_id, team, project_id, stack, connection_id, model,
                    max_tokens, capability_json, binding_schema_json, callable_name, arguments,
                    messages_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    record.capability_call_id,
                    record.approval_id,
                    record.run_id,
                    record.provider_tool_call_id,
                    record.agent_id,
                    record.user_id,
                    record.team,
                    record.project_id,
                    record.stack,
                    record.connection_id,
                    record.model,
                    record.max_tokens,
                    json.dumps(record.capability, ensure_ascii=False),
                    json.dumps(record.binding_schema, ensure_ascii=False),
                    record.callable_name,
                    record.arguments,
                    json.dumps(record.messages, ensure_ascii=False),
                ),
            )

    def claim(self, capability_call_id: str) -> CapabilityCallRecord | None:
        """Atomically claim once; already executing or completed calls cannot run again."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE capability_calls
                SET status = 'executing', updated_at = CURRENT_TIMESTAMP
                WHERE capability_call_id = ? AND status = 'pending'
                """,
                (capability_call_id,),
            )
            row = connection.execute(
                "SELECT * FROM capability_calls WHERE capability_call_id = ?",
                (capability_call_id,),
            ).fetchone()
            connection.commit()
        if updated.rowcount != 1 or row is None:
            return None
        return _to_record(row)

    def link_approval(self, capability_call_id: str, approval_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE capability_calls SET approval_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE capability_call_id = ? AND status = 'pending'
                """,
                (approval_id, capability_call_id),
            )

    def finish(
        self,
        capability_call_id: str,
        *,
        status: str,
        result: str | None = None,
        error_stage: str | None = None,
        error: str | None = None,
    ) -> None:
        if status not in {"succeeded", "failed", "uncertain"}:
            raise ValueError(f"invalid terminal capability call status: {status}")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE capability_calls
                SET status = ?, result = ?, error_stage = ?, error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE capability_call_id = ? AND status = 'executing'
                """,
                (status, result, error_stage, error, capability_call_id),
            )

    def get(self, capability_call_id: str) -> CapabilityCallRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM capability_calls WHERE capability_call_id = ?",
                (capability_call_id,),
            ).fetchone()
        return _to_record(row) if row is not None else None

    def fail_pending(self, capability_call_id: str, *, stage: str, error: str) -> None:
        """Terminally fail a call that was rejected before dispatch."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE capability_calls
                SET status = 'failed', error_stage = ?, error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE capability_call_id = ? AND status = 'pending'
                """,
                (stage, error, capability_call_id),
            )

    def mark_interrupted_executions_uncertain(self) -> int:
        """On single-process startup, never replay calls left mid-execution."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE capability_calls
                SET status = 'uncertain',
                    error_stage = 'orchestrator_restart',
                    error = 'Process stopped during execution; reconcile before retrying.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'executing'
                """
            )
            return cursor.rowcount


def _to_record(row: sqlite3.Row) -> CapabilityCallRecord:
    return CapabilityCallRecord(
        capability_call_id=row["capability_call_id"],
        approval_id=row["approval_id"],
        run_id=row["run_id"],
        provider_tool_call_id=row["provider_tool_call_id"],
        agent_id=row["agent_id"],
        user_id=row["user_id"],
        team=row["team"],
        project_id=row["project_id"],
        stack=row["stack"],
        connection_id=row["connection_id"],
        model=row["model"],
        max_tokens=row["max_tokens"],
        capability=json.loads(row["capability_json"]),
        binding_schema=json.loads(row["binding_schema_json"]),
        callable_name=row["callable_name"],
        arguments=row["arguments"],
        messages=json.loads(row["messages_json"]),
        status=row["status"],
        result=row["result"],
        error_stage=row["error_stage"],
        error=row["error"],
    )