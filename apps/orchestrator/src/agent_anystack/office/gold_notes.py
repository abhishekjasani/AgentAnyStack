"""Structured gold notes — id-addressable rows under gold/<user_id>.jsonl."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

GOLD_RULES = (
    "Your personal working notes for this desk. "
    "Use append_gold for durable bullets; delete_gold(ids) to remove; clear_gold to wipe. "
    "Prefer read_gold before delete. Never dump the whole chat. Not shared OKF."
)


@dataclass(frozen=True)
class GoldNote:
    id: str
    text: str
    run_id: str | None = None
    created_at: str | None = None


def new_gold_id() -> str:
    return f"g_{secrets.token_hex(4)}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def render_gold_notes(notes: list[GoldNote]) -> str:
    """Human/agent-facing body (ids + text). Empty → '(empty)'."""
    if not notes:
        return "(empty)"
    lines: list[str] = []
    for n in notes:
        lines.append(f"- [{n.id}] {n.text.strip()}")
    return "\n".join(lines)


def format_gold_with_rules(notes: list[GoldNote]) -> str:
    """Rules header (orchestrator-owned) + note body — never stored as mutable file header."""
    return (
        f"## Gold (your working notes)\n\n"
        f"{GOLD_RULES}\n\n"
        f"{render_gold_notes(notes)}"
    )


def gold_jsonl_path(gold_dir: Path, user_id: str) -> Path:
    return gold_dir / f"{user_id}.jsonl"


def gold_legacy_md_path(gold_dir: Path, user_id: str) -> Path:
    return gold_dir / f"{user_id}.md"


def load_gold_notes(gold_dir: Path, user_id: str) -> list[GoldNote]:
    """Load notes; migrate legacy .md once into jsonl if needed."""
    path = gold_jsonl_path(gold_dir, user_id)
    legacy = gold_legacy_md_path(gold_dir, user_id)
    if path.is_file():
        return _read_jsonl(path)
    if legacy.is_file():
        text = legacy.read_text(encoding="utf-8").strip()
        if not text:
            legacy.unlink(missing_ok=True)
            return []
        note = GoldNote(
            id=new_gold_id(),
            text=text,
            run_id=None,
            created_at=utc_now_iso(),
        )
        save_gold_notes(gold_dir, user_id, [note], max_chars=10_000_000)
        legacy.unlink(missing_ok=True)
        return [note]
    return []


def save_gold_notes(
    gold_dir: Path,
    user_id: str,
    notes: list[GoldNote],
    *,
    max_chars: int,
) -> None:
    gold_dir.mkdir(parents=True, exist_ok=True)
    path = gold_jsonl_path(gold_dir, user_id)
    legacy = gold_legacy_md_path(gold_dir, user_id)
    if not notes:
        if path.is_file():
            path.unlink()
        if legacy.is_file():
            legacy.unlink()
        return
    payload = "\n".join(
        json.dumps(asdict(n), ensure_ascii=False) for n in notes
    ) + "\n"
    if len(payload) > max_chars:
        raise GoldNotesTooLargeError(
            f"gold exceeds {max_chars} characters ({len(payload)})"
        )
    path.write_text(payload, encoding="utf-8", newline="\n")
    if legacy.is_file():
        legacy.unlink()


def _read_jsonl(path: Path) -> list[GoldNote]:
    notes: list[GoldNote] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        nid = str(data.get("id") or "").strip()
        text = data.get("text")
        if not nid or not isinstance(text, str) or not text.strip():
            continue
        run_id = data.get("run_id")
        created_at = data.get("created_at")
        notes.append(
            GoldNote(
                id=nid,
                text=text.strip(),
                run_id=str(run_id) if run_id else None,
                created_at=str(created_at) if created_at else None,
            )
        )
    return notes


class GoldNotesTooLargeError(Exception):
    """Serialized gold over size cap."""
