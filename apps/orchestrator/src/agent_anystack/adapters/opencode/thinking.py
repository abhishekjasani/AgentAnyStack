"""Thinking persistence for harness runs (not OKF / not gold)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_anystack.adapters.bedrock_store import bedrock_data_dir


def runs_root(database_url: str) -> Path:
    root = bedrock_data_dir(database_url) / "runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def thinking_path(database_url: str, run_id: str) -> Path:
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_")[:128]
    d = runs_root(database_url) / safe
    d.mkdir(parents=True, exist_ok=True)
    return d / "thinking.jsonl"


def append_thinking(database_url: str, run_id: str, text: str) -> None:
    chunk = (text or "").strip("\n")
    if not chunk:
        return
    path = thinking_path(database_url, run_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"text": chunk}, ensure_ascii=False) + "\n")


def read_thinking(database_url: str, run_id: str) -> dict:
    path = thinking_path(database_url, run_id)
    chunks: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                chunks.append(line)
                continue
            if isinstance(row, dict) and row.get("text"):
                chunks.append(str(row["text"]))
    return {
        "run_id": run_id,
        "chunks": chunks,
        "text": "".join(chunks),
    }
