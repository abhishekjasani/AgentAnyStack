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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
