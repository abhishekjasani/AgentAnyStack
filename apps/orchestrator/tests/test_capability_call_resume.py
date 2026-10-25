import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_anystack.adapters.llm import ChatTurnResult, ToolCallRequest
from agent_anystack.capabilities.call_store import (
    CapabilityCallRecord,
    CapabilityCallStore,
)
from agent_anystack.domain.agent import AgentAutonomy, CreateAgentRequest
from agent_anystack.hitl import ApprovalDecision, ApprovalStatus
from agent_anystack.office.repository import OfficeRepository
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import ChatRunService


def _office(tmp_path: Path):
    source = Path(__file__).resolve().parents[3] / "office"
    shutil.copytree(source / "catalog", tmp_path / "catalog")
    descriptor = tmp_path / "catalog" / "tools" / "gold.append.yaml"
    descriptor.write_text(
        descriptor.read_text(encoding="utf-8").replace(
            "approval_mode: never", "approval_mode: always"
        ),
        encoding="utf-8",
    )
    (tmp_path / "org.yaml").write_text(
        "id: resume-test\nname: Resume Test\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    repo = OfficeRepository(tmp_path)
    agent = repo.create_agent(
        CreateAgentRequest(
            id="story-agent",
            name="Story Agent",
            team="stories",
            stack="openai-compatible",
            model="test-model",
            autonomy=AgentAutonomy(default=50),
            workspace={"project_id": "stories-1", "path": "/projects/stories"},
        ),
        user_id="reader",
    )
    return repo, agent


@pytest.mark.asyncio
async def test_approval_resumes_same_provider_tool_call_once(tmp_path):
    repo, agent = _office(tmp_path)
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
                        provider_tool_call_id="provider-call-27",
                        name="append_gold",
                        arguments='{"text":"June found the story card"}',
                    )
                ]
            ),
            ChatTurnResult(content="June's story note is saved."),
        ]
    )
    service._adapter_for = lambda _stack, connection_id=None: adapter
    run_messages = [{"role": "user", "content": "Remember June's story"}]

    events = [
        event
        async for event in service._run_with_gold_tools(
            adapter=adapter,
            model="test-model",
            messages=run_messages,
            agent=agent,
            user_id="reader",
            run_id="run-resume-test",
            stack="openai-compatible",
            connection_id="test-connection",
        )
    ]
    pending = next(event for event in events if event.get("code") == "approval_pending")
    card = service.approvals.list_cards(status=ApprovalStatus.pending_human)[0]
    assert card.capability_call_id
    checkpoint = CapabilityCallStore(
        Path(database_url.removeprefix("sqlite:///"))
    ).get(card.capability_call_id)
    assert checkpoint is not None
    assert checkpoint.provider_tool_call_id == "provider-call-27"
    assert checkpoint.run_id == "run-resume-test"
    assert checkpoint.status == "pending"
    assert pending["approval_id"] == card.id
    assert "June's story note" not in repo.read_gold(agent, "reader")

    service.approvals.decide(
        approval_id=card.id,
        actor="reader",
        decision=ApprovalDecision.accept,
    )
    continuation = await service.resume_approved_capability_call(
        card.capability_call_id
    )

    assert continuation == {
        "status": "completed",
        "assistant_text": "June's story note is saved.",
        "error": None,
    }
    assert "June found the story card" in repo.read_gold(agent, "reader")
    assert adapter.complete_chat_turn.await_count == 2
    resumed_messages = adapter.complete_chat_turn.await_args.kwargs["messages"]
    assert resumed_messages[-1]["role"] == "tool"
    assert resumed_messages[-1]["tool_call_id"] == "provider-call-27"
    assert resumed_messages[-1]["content"].startswith("ok: appended id=")
    assert CapabilityCallStore(Path(database_url.removeprefix("sqlite:///"))).get(
        card.capability_call_id
    ).status == "succeeded"


@pytest.mark.asyncio
async def test_failed_claimed_call_cannot_be_resumed_twice(tmp_path):
    repo, agent = _office(tmp_path)
    database_url = f"sqlite:///{tmp_path}/office.db"
    service = ChatRunService(
        repo=repo,
        journal=RunJournal(tmp_path / "journal.jsonl"),
        openai_compatible_base_url="http://unused.invalid/v1",
        okf=MagicMock(),
        database_url=database_url,
    )
    from agent_anystack.capabilities.binding import build_bindings

    gold_binding = build_bindings(service.capability_catalog, agent)["append_gold"]
    capability_call_id = "capcall-failed-once"
    service.capability_calls.create_pending(
        CapabilityCallRecord(
            capability_call_id=capability_call_id,
            approval_id="appr-failed-once",
            run_id="run-failure-test",
            provider_tool_call_id="provider-call-fail",
            agent_id=agent.id,
            user_id="reader",
            team=agent.team,
            project_id=agent.workspace.project_id,
            stack="openai-compatible",
            connection_id="test-connection",
            model="test-model",
            max_tokens=100,
            capability=gold_binding.item.model_dump(mode="json"),
            binding_schema=gold_binding.schema,
            callable_name=gold_binding.callable_name,
            arguments='{"text":"will fail"}',
            messages=[{"role":"user", "content":"save"}],
        )
    )
    service._execute_binding = AsyncMock(return_value="error: API request failed (ConnectError)")
    first = await service.resume_approved_capability_call(capability_call_id)
    second = await service.resume_approved_capability_call(capability_call_id)

    assert first["status"] == "failed"
    assert second["status"] == "failed"
    assert service._execute_binding.await_count == 1


def test_interrupted_execution_becomes_uncertain_and_is_not_reclaimed(tmp_path):
    store = CapabilityCallStore(tmp_path / "office.db")
    store.create_pending(
        CapabilityCallRecord(
            capability_call_id="capcall-interrupted",
            approval_id="appr-interrupted",
            run_id="run-interrupted",
            provider_tool_call_id="provider-interrupted",
            agent_id="story-agent",
            user_id="reader",
            team="stories",
            project_id="stories-1",
            stack="openai-compatible",
            connection_id="test-connection",
            model="test-model",
            max_tokens=100,
            capability={},
            binding_schema={},
            callable_name="write_external",
            arguments="{}",
            messages=[],
        )
    )
    assert store.claim("capcall-interrupted") is not None

    assert store.mark_interrupted_executions_uncertain() == 1
    assert store.get("capcall-interrupted").status == "uncertain"
    assert store.claim("capcall-interrupted") is None