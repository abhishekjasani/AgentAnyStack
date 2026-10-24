import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_anystack.adapters.llm import ChatTurnResult, ToolCallRequest
from agent_anystack.domain.agent import AgentAutonomy, CreateAgentRequest
from agent_anystack.hitl import ApprovalStatus, ApprovalStore
from agent_anystack.memory.store import sqlite_path_from_database_url
from agent_anystack.office.repository import OfficeRepository
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import ChatRunService


def _office_with_gold_approval(
    tmp_path: Path,
    approval_mode: str,
    *,
    autonomy_default: int = 50,
):
    source = Path(__file__).resolve().parents[3] / "office"
    shutil.copytree(source / "catalog", tmp_path / "catalog")
    append_descriptor = tmp_path / "catalog" / "tools" / "gold.append.yaml"
    append_descriptor.write_text(
        append_descriptor.read_text(encoding="utf-8").replace(
            "approval_mode: never", f"approval_mode: {approval_mode}"
        ),
        encoding="utf-8",
    )
    (tmp_path / "org.yaml").write_text(
        "id: demo\nname: Demo Org\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    repo = OfficeRepository(tmp_path)
    agent = repo.create_agent(
        CreateAgentRequest(
            id="approval-agent",
            name="Approval Agent",
            team="eng",
            stack="openai-compatible",
            model="test-model",
            autonomy=AgentAutonomy(default=autonomy_default),
            workspace={"project_id": "proj-1", "path": "/projects/proj-1"},
        ),
        user_id="requester",
    )
    return repo, agent


def test_legacy_journal_tool_name_loads_as_callable_name(tmp_path):
    journal_path = tmp_path / "legacy-journal.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "run_id": "run-old",
                "agent_id": "desk",
                "user_id": "user",
                "team": "eng",
                "project_id": None,
                "channel": "office_ui",
                "stack": "capability",
                "model": "",
                "effective_autonomy": 50,
                "status": "capability_call",
                "started_at": "2026-10-25T00:00:00Z",
                "entry_type": "capability_call",
                "tool_name": "inventory_lookup",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    entry = RunJournal(journal_path)._read_all()[0]

    assert entry.callable_name == "inventory_lookup"


@pytest.mark.asyncio
@pytest.mark.parametrize("approval_mode", ["always", "autonomy"])
async def test_human_approval_blocks_gold_dispatch_and_creates_pending_card(
    tmp_path,
    approval_mode,
):
    repo, agent = _office_with_gold_approval(tmp_path, approval_mode)
    database_url = f"sqlite:///{tmp_path}/office.db"
    journal = RunJournal(tmp_path / "journal.jsonl")
    service = ChatRunService(
        repo=repo,
        journal=journal,
        openai_compatible_base_url="http://unused.invalid/v1",
        okf=MagicMock(),
        database_url=database_url,
    )
    adapter = MagicMock()
    adapter.complete_chat_turn = AsyncMock(
        return_value=ChatTurnResult(
            tool_calls=[
                ToolCallRequest(
                    id="call-1",
                    name="append_gold",
                    arguments='{"text":"requires approval"}',
                )
            ]
        )
    )

    events = [
        event
        async for event in service._run_with_gold_tools(
            adapter=adapter,
            model="test-model",
            messages=[{"role": "user", "content": "save a note"}],
            agent=agent,
            user_id="requester",
            run_id="run-approval-test",
        )
    ]

    cards = ApprovalStore(sqlite_path_from_database_url(database_url)).list_cards()
    assert len(cards) == 1
    assert cards[0].status == ApprovalStatus.pending_human
    assert cards[0].run_id == "run-approval-test"
    assert "requires approval" not in repo.read_gold(agent, "requester")
    assert next(event for event in events if event.get("type") == "error")["message"].startswith(
        "capability call requires approval:"
    )
    assert adapter.complete_chat_turn.await_count == 1


@pytest.mark.asyncio
async def test_never_mode_dispatches_and_journals_call_without_approval(tmp_path):
    repo, agent = _office_with_gold_approval(tmp_path, "never")
    database_url = f"sqlite:///{tmp_path}/office.db"
    journal = RunJournal(tmp_path / "journal.jsonl")
    service = ChatRunService(
        repo=repo,
        journal=journal,
        openai_compatible_base_url="http://unused.invalid/v1",
        okf=MagicMock(),
        database_url=database_url,
    )
    adapter = MagicMock()
    adapter.complete_chat_turn = AsyncMock(
        side_effect=[
            ChatTurnResult(
                tool_calls=[
                    ToolCallRequest(
                        id="call-never",
                        name="append_gold",
                        arguments='{"text":"direct write"}',
                    )
                ]
            ),
            ChatTurnResult(content="Saved"),
        ]
    )

    async for _event in service._run_with_gold_tools(
        adapter=adapter,
        model="test-model",
        messages=[{"role": "user", "content": "save this"}],
        agent=agent,
        user_id="requester",
        run_id="run-never-test",
    ):
        pass

    assert "direct write" in repo.read_gold(agent, "requester")
    assert ApprovalStore(sqlite_path_from_database_url(database_url)).list_cards() == []
    call_entries = [entry for entry in journal._read_all() if entry.entry_type == "capability_call"]
    assert len(call_entries) == 1
    assert call_entries[0].capability_id == "gold.append"
    assert call_entries[0].callable_name == "append_gold"
    assert call_entries[0].approval_mode == "never"
    assert call_entries[0].call_status == "succeeded"
    assert journal.recent_runs() == []


@pytest.mark.asyncio
async def test_autonomy_mode_auto_allows_and_links_journal_to_approval(tmp_path):
    repo, agent = _office_with_gold_approval(
        tmp_path,
        "autonomy",
        autonomy_default=90,
    )
    database_url = f"sqlite:///{tmp_path}/office.db"
    journal = RunJournal(tmp_path / "journal.jsonl")
    service = ChatRunService(
        repo=repo,
        journal=journal,
        openai_compatible_base_url="http://unused.invalid/v1",
        okf=MagicMock(),
        database_url=database_url,
    )
    adapter = MagicMock()
    adapter.complete_chat_turn = AsyncMock(
        side_effect=[
            ChatTurnResult(
                tool_calls=[
                    ToolCallRequest(
                        id="call-autonomy",
                        name="append_gold",
                        arguments='{"text":"autonomy allowed"}',
                    )
                ]
            ),
            ChatTurnResult(content="Saved"),
        ]
    )

    async for _event in service._run_with_gold_tools(
        adapter=adapter,
        model="test-model",
        messages=[{"role": "user", "content": "save this"}],
        agent=agent,
        user_id="requester",
        run_id="run-autonomy-test",
    ):
        pass

    cards = ApprovalStore(sqlite_path_from_database_url(database_url)).list_cards()
    assert len(cards) == 1
    assert cards[0].status == ApprovalStatus.accepted
    assert cards[0].gate == "allow"
    assert "autonomy allowed" in repo.read_gold(agent, "requester")
    call_entry = next(
        entry for entry in journal._read_all() if entry.entry_type == "capability_call"
    )
    assert call_entry.approval_id == cards[0].id
    assert call_entry.call_status == "succeeded"
    assert call_entry.approval_mode == "autonomy"


@pytest.mark.asyncio
async def test_autonomy_mode_denies_before_dispatch_and_journals_outcome(tmp_path):
    repo, agent = _office_with_gold_approval(
        tmp_path,
        "autonomy",
        autonomy_default=10,
    )
    database_url = f"sqlite:///{tmp_path}/office.db"
    journal = RunJournal(tmp_path / "journal.jsonl")
    service = ChatRunService(
        repo=repo,
        journal=journal,
        openai_compatible_base_url="http://unused.invalid/v1",
        okf=MagicMock(),
        database_url=database_url,
    )
    adapter = MagicMock()
    adapter.complete_chat_turn = AsyncMock(
        return_value=ChatTurnResult(
            tool_calls=[
                ToolCallRequest(
                    id="call-denied",
                    name="append_gold",
                    arguments='{"text":"must not be written"}',
                )
            ]
        )
    )

    events = [
        event
        async for event in service._run_with_gold_tools(
            adapter=adapter,
            model="test-model",
            messages=[{"role": "user", "content": "save this"}],
            agent=agent,
            user_id="requester",
            run_id="run-denied-test",
        )
    ]

    cards = ApprovalStore(sqlite_path_from_database_url(database_url)).list_cards()
    assert len(cards) == 1
    assert cards[0].status == ApprovalStatus.denied
    assert "must not be written" not in repo.read_gold(agent, "requester")
    assert next(event for event in events if event.get("type") == "error")["code"] == "capability_denied"
    call_entry = next(
        entry for entry in journal._read_all() if entry.entry_type == "capability_call"
    )
    assert call_entry.approval_id == cards[0].id
    assert call_entry.call_status == "denied"