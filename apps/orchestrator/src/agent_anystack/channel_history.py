"""Per-user unified channel transcript — one thread per X-User-Id."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_SAFE_USER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_message_id() -> str:
    return f"msg-{uuid4().hex[:16]}"


@dataclass
class ChannelMessage:
    id: str
    role: str  # user | assistant | office
    text: str
    created_at: str
    mode: str  # office | agent
    agent_id: str | None = None
    kind: str | None = None  # office ask kind
    run_id: str | None = None


class ChannelHistoryStore:
    """Append-only JSONL under data/channel/<user_id>.jsonl."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        if not _SAFE_USER.match(user_id):
            raise ValueError(f"invalid user_id for history: {user_id}")
        return self.root / f"{user_id}.jsonl"

    def append(self, user_id: str, message: ChannelMessage) -> ChannelMessage:
        path = self._path(user_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(message), ensure_ascii=False) + "\n")
        return message

    def list_messages(self, user_id: str, *, limit: int = 200) -> list[ChannelMessage]:
        path = self._path(user_id)
        if not path.is_file() or limit <= 0:
            return []
        rows: list[ChannelMessage] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    rows.append(
                        ChannelMessage(
                            id=str(data.get("id") or new_message_id()),
                            role=str(data.get("role") or "assistant"),
                            text=str(data.get("text") or ""),
                            created_at=str(data.get("created_at") or ""),
                            mode=str(data.get("mode") or "office"),
                            agent_id=data.get("agent_id"),
                            kind=data.get("kind"),
                            run_id=data.get("run_id"),
                        )
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return rows[-limit:]

    def list_recent(
        self,
        user_id: str,
        *,
        days: int = 7,
        limit: int = 1000,
        exclude_text: str | None = None,
    ) -> list[ChannelMessage]:
        """Messages from the last `days` (UTC), oldest→newest within window."""
        if days <= 0:
            return []
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        rows = self.list_messages(user_id, limit=limit)
        recent: list[ChannelMessage] = []
        for m in rows:
            ts = _parse_created_at(m.created_at)
            if ts is None or ts >= cutoff:
                recent.append(m)
        if (
            exclude_text is not None
            and recent
            and recent[-1].role == "user"
            and recent[-1].text.strip() == exclude_text.strip()
        ):
            recent = recent[:-1]
        return recent


def _parse_created_at(raw: str) -> float | None:
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def channel_history_root_from_database_url(
    database_url: str,
    data_fallback: Path,
) -> Path:
    if database_url.startswith("sqlite:///"):
        raw = database_url.removeprefix("sqlite:///")
        db = Path(raw)
        return db.parent / "channel"
    return data_fallback / "channel"
