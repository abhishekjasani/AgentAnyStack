"""Run journal — append-only JSONL for analytics later."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
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


class RunJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: JournalEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def recent(self, limit: int = 20, *, team: str | None = None) -> list[JournalEntry]:
        """Newest-last slice of journal (ops status for office Q&A)."""
        if not self.path.is_file() or limit <= 0:
            return []
        rows: list[JournalEntry] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
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
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if team is not None and entry.team != team:
                    continue
                rows.append(entry)
        return rows[-limit:]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
