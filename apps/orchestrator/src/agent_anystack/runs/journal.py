"""Run journal — append-only JSONL for analytics later."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def new_run_id() -> str:
    return f"run-{uuid4().hex[:16]}"


@dataclass
class JournalEntry:
    """Ops / trust log for one run — not chat history or business facts."""

    run_id: str
    agent_id: str
    user_id: str
    team: str
    project_id: str | None
    channel: str
    stack: str
    model: str
    effective_autonomy: int
    status: str
    started_at: str
    ended_at: str | None = None
    error: str | None = None
    # HITL decide audit (optional — run rows leave these null)
    approval_id: str | None = None
    decision: str | None = None
    decided_by: str | None = None
    connection_id: str | None = None
    # Token usage & cost
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost: float | None = None
    estimated: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.input_tokens is None and self.prompt_tokens is not None:
            self.input_tokens = self.prompt_tokens
        elif self.prompt_tokens is None and self.input_tokens is not None:
            self.prompt_tokens = self.input_tokens
        if self.output_tokens is None and self.completion_tokens is not None:
            self.output_tokens = self.completion_tokens
        elif self.completion_tokens is None and self.output_tokens is not None:
            self.completion_tokens = self.output_tokens


class RunJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: JournalEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def recent(self, limit: int = 20, *, team: str | None = None) -> list[JournalEntry]:
        """Newest-last slice of journal (ops status for office Q&A)."""
        rows = self._read_all()
        if team is not None:
            rows = [e for e in rows if e.team == team]
        if limit <= 0:
            return []
        return rows[-limit:]

    def recent_for_connection(
        self,
        connection_id: str,
        *,
        aliases: tuple[str, ...] | list[str] = (),
        stack: str | None = None,
        limit: int = 20,
    ) -> list[JournalEntry]:
        """Newest-first runs for a connection (excludes approval-only rows)."""
        cid = (connection_id or "").strip()
        all_ids = {cid, *(str(a).strip() for a in aliases if str(a).strip())} - {""}
        sid = (stack or "").strip()

        def _matches(e: JournalEntry) -> bool:
            if not e.agent_id or e.approval_id:
                return False
            if e.connection_id:
                return e.connection_id in all_ids
            from agent_anystack.adapters.connections import STACK_TO_PRODUCT

            return bool(sid and e.stack == sid and cid == STACK_TO_PRODUCT.get(sid, sid))

        rows = [e for e in self._read_all() if _matches(e)]
        rows.reverse()
        return rows[: max(0, limit)]

    def recent_for_stack(
        self,
        stack: str,
        *,
        limit: int = 20,
    ) -> list[JournalEntry]:
        """Newest-first runs for an inference stack (excludes approval-only rows)."""
        sid = (stack or "").strip()
        rows = [
            e
            for e in self._read_all()
            if e.stack == sid and e.agent_id and not e.approval_id
        ]
        rows.reverse()
        return rows[: max(0, limit)]

    def recent_runs(
        self,
        *,
        limit: int = 50,
        team: str | None = None,
        agent_id: str | None = None,
        project_id: str | None = None,
        stack: str | None = None,
        user_id: str | None = None,
    ) -> list[JournalEntry]:
        """Newest-first run entries with optional filters (excludes approval-only rows)."""
        rows = [e for e in self._read_all() if e.agent_id and not e.approval_id]
        if team:
            rows = [e for e in rows if e.team == team]
        if agent_id:
            rows = [e for e in rows if e.agent_id == agent_id]
        if project_id:
            rows = [e for e in rows if e.project_id == project_id]
        if stack:
            rows = [e for e in rows if e.stack == stack]
        if user_id:
            rows = [e for e in rows if e.user_id == user_id]
        rows.reverse()
        return rows[: max(0, limit)]

    def summary(self) -> dict[str, Any]:
        """Aggregated summary of runs, tokens (input/output), and cost across all runs."""
        rows = [e for e in self._read_all() if e.agent_id and not e.approval_id]
        total_runs = len(rows)
        total_input_tokens = sum(e.input_tokens or e.prompt_tokens or 0 for e in rows)
        total_output_tokens = sum(e.output_tokens or e.completion_tokens or 0 for e in rows)
        total_tokens = sum(e.total_tokens or 0 for e in rows)
        total_cost = sum(e.cost or 0.0 for e in rows)

        by_stack: dict[str, dict[str, Any]] = {}
        by_agent: dict[str, dict[str, Any]] = {}

        for e in rows:
            inp = e.input_tokens or e.prompt_tokens or 0
            out = e.output_tokens or e.completion_tokens or 0
            tot = e.total_tokens or (inp + out)

            # By stack
            s_key = e.stack or "unknown"
            s_data = by_stack.setdefault(
                s_key,
                {
                    "runs": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                },
            )
            s_data["runs"] += 1
            s_data["input_tokens"] += inp
            s_data["output_tokens"] += out
            s_data["total_tokens"] += tot
            s_data["cost"] = round(s_data["cost"] + (e.cost or 0.0), 6)

            # By agent
            a_key = e.agent_id or "unknown"
            a_data = by_agent.setdefault(
                a_key,
                {
                    "runs": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost": 0.0,
                },
            )
            a_data["runs"] += 1
            a_data["input_tokens"] += inp
            a_data["output_tokens"] += out
            a_data["total_tokens"] += tot
            a_data["cost"] = round(a_data["cost"] + (e.cost or 0.0), 6)

        return {
            "total_runs": total_runs,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_prompt_tokens": total_input_tokens,
            "total_completion_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "total_cost": round(total_cost, 6),
            "by_stack": by_stack,
            "by_agent": by_agent,
        }

    def _read_all(self) -> list[JournalEntry]:
        if not self.path.is_file():
            return []
        rows: list[JournalEntry] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    inp = data.get("input_tokens")
                    if inp is None:
                        inp = data.get("prompt_tokens")
                    out = data.get("output_tokens")
                    if out is None:
                        out = data.get("completion_tokens")
                    entry = JournalEntry(
                        run_id=str(data.get("run_id") or ""),
                        agent_id=str(data.get("agent_id") or ""),
                        user_id=str(data.get("user_id") or ""),
                        team=str(data.get("team") or ""),
                        project_id=data.get("project_id"),
                        channel=str(data.get("channel") or "office_ui"),
                        stack=str(data.get("stack") or ""),
                        model=str(data.get("model") or ""),
                        effective_autonomy=int(data.get("effective_autonomy") or 0),
                        status=str(data.get("status") or ""),
                        started_at=str(data.get("started_at") or ""),
                        ended_at=data.get("ended_at"),
                        error=data.get("error"),
                        approval_id=data.get("approval_id"),
                        decision=data.get("decision"),
                        decided_by=data.get("decided_by"),
                        connection_id=data.get("connection_id"),
                        input_tokens=inp,
                        output_tokens=out,
                        prompt_tokens=inp,
                        completion_tokens=out,
                        total_tokens=data.get("total_tokens"),
                        reasoning_tokens=data.get("reasoning_tokens"),
                        cost=data.get("cost"),
                        estimated=bool(data.get("estimated", False)),
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                rows.append(entry)
        return rows


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
