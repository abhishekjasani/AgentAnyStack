from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_anystack.runs.journal import JournalEntry, RunJournal


def test_journal_recent_for_connection_isolates_by_connection(tmp_path: Path):
    journal_path = tmp_path / "journal.jsonl"
    journal = RunJournal(journal_path)

    # 1. Ollama run (stack: openai-compatible, connection_id: ollama)
    journal.append(
        JournalEntry(
            run_id="run-ollama-1",
            agent_id="agent-1",
            user_id="admin",
            team="eng",
            project_id="proj-1",
            channel="office_ui",
            stack="openai-compatible",
            model="llama3",
            effective_autonomy=50,
            status="ok",
            started_at="2026-08-26T10:00:00+00:00",
            connection_id="ollama",
        )
    )

    # 2. Zen-dev run (stack: openai-compatible, connection_id: zen-dev)
    journal.append(
        JournalEntry(
            run_id="run-zen-1",
            agent_id="agent-2",
            user_id="admin",
            team="eng",
            project_id="proj-1",
            channel="office_ui",
            stack="openai-compatible",
            model="hy3-free",
            effective_autonomy=50,
            status="ok",
            started_at="2026-08-26T10:05:00+00:00",
            connection_id="zen-dev",
        )
    )

    # 3. Another Ollama run using alias in connection_id
    journal.append(
        JournalEntry(
            run_id="run-ollama-2",
            agent_id="agent-1",
            user_id="admin",
            team="eng",
            project_id="proj-1",
            channel="office_ui",
            stack="openai-compatible",
            model="llama3",
            effective_autonomy=50,
            status="ok",
            started_at="2026-08-26T10:10:00+00:00",
            connection_id="ollama-local",
        )
    )

    # Query ollama runs
    ollama_runs = journal.recent_for_connection(
        "ollama",
        aliases=["ollama-local"],
        stack="openai-compatible",
    )
    ollama_run_ids = [r.run_id for r in ollama_runs]
    assert ollama_run_ids == ["run-ollama-2", "run-ollama-1"]
    assert "run-zen-1" not in ollama_run_ids

    # Query zen-dev runs
    zen_runs = journal.recent_for_connection(
        "zen-dev",
        aliases=[],
        stack="openai-compatible",
    )
    zen_run_ids = [r.run_id for r in zen_runs]
    assert zen_run_ids == ["run-zen-1"]
    assert "run-ollama-1" not in zen_run_ids
    assert "run-ollama-2" not in zen_run_ids


def test_journal_legacy_entries_backward_compatibility(tmp_path: Path):
    journal_path = tmp_path / "journal.jsonl"
    
    # Write raw legacy JSONL entries without connection_id
    legacy_entry = {
        "run_id": "run-legacy-1",
        "agent_id": "agent-legacy",
        "user_id": "admin",
        "team": "eng",
        "project_id": "proj-1",
        "channel": "office_ui",
        "stack": "openai-compatible",
        "model": "mistral",
        "effective_autonomy": 50,
        "status": "ok",
        "started_at": "2026-08-26T09:00:00+00:00",
    }
    with open(journal_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(legacy_entry) + "\n")

    journal = RunJournal(journal_path)

    # Legacy openai-compatible entry attributes to default stack connection (ollama)
    ollama_runs = journal.recent_for_connection(
        "ollama",
        aliases=["ollama-local"],
        stack="openai-compatible",
    )
    assert [r.run_id for r in ollama_runs] == ["run-legacy-1"]

    # Legacy entry should not leak to zen-dev
    zen_runs = journal.recent_for_connection(
        "zen-dev",
        aliases=[],
        stack="openai-compatible",
    )
    assert zen_runs == []


@pytest.mark.asyncio
async def test_connection_runtimes_endpoint_filters_properly(tmp_path: Path):
    from agent_anystack.adapters.connections import ConnectionStore, StackConnection
    from agent_anystack.api.connections import connection_runtimes

    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="ollama",
            kind="inference",
            product="ollama",
            label="Ollama",
            aliases=["ollama-local"],
        )
    )
    store.upsert(
        StackConnection(
            id="zen-dev",
            kind="inference",
            product="openai-compatible",
            label="Zen Dev",
            aliases=[],
        )
    )

    journal = RunJournal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEntry(
            run_id="run-ollama-1",
            agent_id="agent-1",
            user_id="admin",
            team="eng",
            project_id=None,
            channel="office_ui",
            stack="openai-compatible",
            model="llama3",
            effective_autonomy=50,
            status="ok",
            started_at="2026-08-26T10:00:00+00:00",
            connection_id="ollama",
        )
    )
    journal.append(
        JournalEntry(
            run_id="run-zen-1",
            agent_id="agent-2",
            user_id="admin",
            team="eng",
            project_id=None,
            channel="office_ui",
            stack="openai-compatible",
            model="hy3-free",
            effective_autonomy=50,
            status="ok",
            started_at="2026-08-26T10:05:00+00:00",
            connection_id="zen-dev",
        )
    )

    ollama_res = await connection_runtimes(
        connection_id="ollama",
        store=store,
        journal=journal,
        _user_id="admin",
    )
    assert ollama_res["connection_id"] == "ollama"
    assert len(ollama_res["runs"]) == 1
    assert ollama_res["runs"][0]["run_id"] == "run-ollama-1"

    zen_res = await connection_runtimes(
        connection_id="zen-dev",
        store=store,
        journal=journal,
        _user_id="admin",
    )
    assert zen_res["connection_id"] == "zen-dev"
    assert len(zen_res["runs"]) == 1
    assert zen_res["runs"][0]["run_id"] == "run-zen-1"

