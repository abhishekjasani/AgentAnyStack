from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_anystack.adapters.bedrock import BedrockAdapter, _parse_converse_output
from agent_anystack.adapters.llm import (
    ChatTurnResult,
    OpenAICompatibleAdapter,
    TokenUsage,
    ToolCallRequest,
)
from agent_anystack.adapters.opencode.events import (
    EventMapper,
    collect_usage_from_messages,
    extract_opencode_usage,
)
from agent_anystack.api.analytics import get_analytics_runs, get_analytics_summary
from agent_anystack.api.connections import connection_runtimes
from agent_anystack.runs.journal import JournalEntry, RunJournal
from agent_anystack.runs.service import ChatRunService


def test_token_usage_model_and_aggregation():
    u1 = TokenUsage(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        reasoning_tokens=20,
        cost=0.001,
        estimated=False,
    )
    assert u1.input_tokens == 100
    assert u1.output_tokens == 50
    assert u1.prompt_tokens == 100
    assert u1.completion_tokens == 50

    u2 = TokenUsage(
        prompt_tokens=200,
        completion_tokens=80,
        total_tokens=280,
        reasoning_tokens=30,
        cost=0.002,
        estimated=False,
    )
    assert u2.input_tokens == 200
    assert u2.output_tokens == 80

    combined = u1.add(u2)
    assert combined.input_tokens == 300
    assert combined.output_tokens == 130
    assert combined.prompt_tokens == 300
    assert combined.completion_tokens == 130
    assert combined.total_tokens == 430
    assert combined.reasoning_tokens == 50
    assert combined.cost == 0.003
    assert not combined.estimated

    # Add None
    assert combined.add(None) == combined

    # Add estimated
    u_est = TokenUsage(input_tokens=50, output_tokens=10, total_tokens=60, estimated=True)
    combined_est = combined.add(u_est)
    assert combined_est.estimated is True

    # as_dict serialization contains both pairs
    d = combined.as_dict()
    assert d["input_tokens"] == 300
    assert d["output_tokens"] == 130
    assert d["prompt_tokens"] == 300
    assert d["completion_tokens"] == 130
    assert d["total_tokens"] == 430
    assert d["reasoning_tokens"] == 50
    assert d["cost"] == 0.003
    assert d["estimated"] is False


@pytest.mark.asyncio
async def test_openai_compatible_adapter_complete_turn_usage(monkeypatch):
    adapter = OpenAICompatibleAdapter("http://mock-llm:11434")

    fake_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello world",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }

    class MockResponse:
        status_code = 200

        def json(self):
            return fake_response

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient", MockClient)

    turn = await adapter.complete_chat_turn(
        model="test-model",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert turn.content == "Hello world"
    assert turn.usage is not None
    assert turn.usage.input_tokens == 12
    assert turn.usage.output_tokens == 5
    assert turn.usage.prompt_tokens == 12
    assert turn.usage.completion_tokens == 5
    assert turn.usage.total_tokens == 17
    assert turn.usage.reasoning_tokens == 2


@pytest.mark.asyncio
async def test_openai_compatible_adapter_streaming_usage(monkeypatch):
    adapter = OpenAICompatibleAdapter("http://mock-llm:11434")

    lines = [
        b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n',
        b'data: {"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}\n\n',
        b"data: [DONE]\n\n",
    ]

    class MockStreamResponse:
        status_code = 200

        async def aiter_lines(self):
            for line in lines:
                yield line.decode("utf-8")

        async def aread(self):
            return b""

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            class StreamCtx:
                async def __aenter__(self):
                    return MockStreamResponse()

                async def __aexit__(self, *args):
                    pass

            return StreamCtx()

    monkeypatch.setattr("httpx.AsyncClient", MockClient)

    events = []
    async for ev in adapter.stream_chat_events(
        model="test-model",
        messages=[{"role": "user", "content": "hi"}],
    ):
        events.append(ev)

    token_events = [e for e in events if e.get("type") == "token"]
    usage_events = [e for e in events if e.get("type") == "usage"]

    assert len(token_events) == 1
    assert token_events[0]["text"] == "Hi"
    assert len(usage_events) == 1
    assert usage_events[0]["input_tokens"] == 10
    assert usage_events[0]["output_tokens"] == 2
    assert usage_events[0]["prompt_tokens"] == 10
    assert usage_events[0]["completion_tokens"] == 2
    assert usage_events[0]["total_tokens"] == 12


def test_bedrock_converse_output_usage():
    mock_resp = {
        "output": {
            "message": {
                "content": [{"text": "Bedrock answer"}],
            }
        },
        "usage": {
            "inputTokens": 45,
            "outputTokens": 18,
            "totalTokens": 63,
        },
    }
    turn = _parse_converse_output(mock_resp)
    assert turn.content == "Bedrock answer"
    assert turn.usage is not None
    assert turn.usage.input_tokens == 45
    assert turn.usage.output_tokens == 18
    assert turn.usage.prompt_tokens == 45
    assert turn.usage.completion_tokens == 18
    assert turn.usage.total_tokens == 63


def test_opencode_event_mapper_and_messages_usage():
    session_id = "ses-123"
    mapper = EventMapper(session_id)

    # 1. message.updated event with tokens and cost
    event = {
        "type": "message.updated",
        "properties": {
            "sessionID": session_id,
            "info": {
                "role": "assistant",
                "tokens": {
                    "input": 150,
                    "output": 60,
                    "reasoning": 25,
                },
                "cost": 0.0015,
            },
        },
    }
    mapped = mapper.map(event)
    assert len(mapped) == 1
    assert mapped[0]["type"] == "usage"
    assert mapped[0]["input_tokens"] == 150
    assert mapped[0]["output_tokens"] == 60
    assert mapped[0]["prompt_tokens"] == 150
    assert mapped[0]["completion_tokens"] == 60
    assert mapped[0]["reasoning_tokens"] == 25
    assert mapped[0]["total_tokens"] == 235
    assert mapped[0]["cost"] == 0.0015

    # 2. step-finish event with tokens and cost
    step_event = {
        "type": "step-finish",
        "properties": {
            "sessionID": session_id,
            "tokens": {"input": 40, "output": 10},
            "cost": 0.0002,
        },
    }
    mapped_step = mapper.map(step_event)
    assert len(mapped_step) == 1
    assert mapped_step[0]["type"] == "usage"
    assert mapped_step[0]["input_tokens"] == 40
    assert mapped_step[0]["output_tokens"] == 10
    assert mapped_step[0]["total_tokens"] == 50

    # 3. collect_usage_from_messages harvest
    messages_payload = [
        {"role": "user", "content": "do something"},
        {
            "role": "assistant",
            "tokens": {"input": 200, "output": 100, "reasoning": 50},
            "cost": 0.002,
        },
    ]
    harvested = collect_usage_from_messages(messages_payload)
    assert harvested is not None
    assert harvested["input_tokens"] == 200
    assert harvested["output_tokens"] == 100
    assert harvested["prompt_tokens"] == 200
    assert harvested["completion_tokens"] == 100
    assert harvested["reasoning_tokens"] == 50
    assert harvested["total_tokens"] == 350
    assert harvested["cost"] == 0.002


def test_run_journal_persistence_and_analytics_summary(tmp_path: Path):
    journal_path = tmp_path / "journal.jsonl"
    journal = RunJournal(journal_path)

    # Append runs with separate input and output tokens and cost
    e1 = JournalEntry(
        run_id="run-1",
        agent_id="pythondev",
        user_id="user-a",
        team="eng",
        project_id="proj-1",
        channel="office_ui",
        stack="openai-compatible",
        model="llama3",
        effective_autonomy=50,
        status="ok",
        started_at="2026-08-26T10:00:00+00:00",
        ended_at="2026-08-26T10:00:05+00:00",
        connection_id="ollama",
        input_tokens=500,
        output_tokens=100,
        total_tokens=600,
        cost=0.0006,
    )
    e2 = JournalEntry(
        run_id="run-2",
        agent_id="ba",
        user_id="user-b",
        team="product",
        project_id="proj-2",
        channel="office_ui",
        stack="bedrock",
        model="nova-pro",
        effective_autonomy=80,
        status="ok",
        started_at="2026-08-26T10:10:00+00:00",
        ended_at="2026-08-26T10:10:04+00:00",
        connection_id="bedrock-main",
        input_tokens=800,
        output_tokens=200,
        total_tokens=1000,
        cost=0.0025,
    )
    journal.append(e1)
    journal.append(e2)

    # 1. Verify read_all round-trip
    rows = journal._read_all()
    assert len(rows) == 2
    assert rows[0].input_tokens == 500
    assert rows[0].output_tokens == 100
    assert rows[0].prompt_tokens == 500
    assert rows[0].completion_tokens == 100
    assert rows[0].total_tokens == 600
    assert rows[0].cost == 0.0006
    assert rows[1].input_tokens == 800
    assert rows[1].output_tokens == 200
    assert rows[1].total_tokens == 1000

    # 2. Verify recent_runs filters
    recent = journal.recent_runs(limit=10, team="eng")
    assert len(recent) == 1
    assert recent[0].run_id == "run-1"

    # 3. Verify summary aggregation
    summary = journal.summary()
    assert summary["total_runs"] == 2
    assert summary["total_input_tokens"] == 1300
    assert summary["total_output_tokens"] == 300
    assert summary["total_prompt_tokens"] == 1300
    assert summary["total_completion_tokens"] == 300
    assert summary["total_tokens"] == 1600
    assert summary["total_cost"] == 0.0031

    # Breakdown by stack has input and output separated
    assert summary["by_stack"]["openai-compatible"]["input_tokens"] == 500
    assert summary["by_stack"]["openai-compatible"]["output_tokens"] == 100
    assert summary["by_stack"]["openai-compatible"]["total_tokens"] == 600

    assert summary["by_stack"]["bedrock"]["input_tokens"] == 800
    assert summary["by_stack"]["bedrock"]["output_tokens"] == 200
    assert summary["by_stack"]["bedrock"]["total_tokens"] == 1000

    # Breakdown by agent has input and output separated
    assert summary["by_agent"]["pythondev"]["input_tokens"] == 500
    assert summary["by_agent"]["pythondev"]["output_tokens"] == 100
    assert summary["by_agent"]["pythondev"]["total_tokens"] == 600

    assert summary["by_agent"]["ba"]["input_tokens"] == 800
    assert summary["by_agent"]["ba"]["output_tokens"] == 200
    assert summary["by_agent"]["ba"]["total_tokens"] == 1000


@pytest.mark.asyncio
async def test_service_multi_round_tool_tokens_accumulation():
    """Verify that multiple tool rounds in ChatRunService aggregate tokens properly."""
    with tempfile.TemporaryDirectory() as td:
        db_url = f"sqlite:///{td}/test.db"
        journal_path = Path(td) / "journal.jsonl"
        journal = RunJournal(journal_path)

        repo_mock = MagicMock()
        repo_mock.list_gold_notes.return_value = []
        agent_mock = MagicMock()
        agent_mock.id = "agent-1"
        agent_mock.team = "eng"
        agent_mock.connection_id = "mock-conn"
        agent_mock.workspace = None
        repo_mock.get_agent.return_value = agent_mock

        service = ChatRunService(
            repo=repo_mock,
            journal=journal,
            openai_compatible_base_url="http://mock:11434",
            okf=MagicMock(),
            database_url=db_url,
        )

        # Mock adapter with 2 turns:
        # Round 1: calls read_gold with usage (input: 50, output: 15, total: 65)
        # Round 2: final answer with usage (input: 80, output: 25, total: 105)
        mock_adapter = MagicMock()
        turn1 = ChatTurnResult(
            content="",
            tool_calls=[ToolCallRequest(id="call-1", name="read_gold", arguments="{}")],
            usage=TokenUsage(input_tokens=50, output_tokens=15, total_tokens=65),
        )
        turn2 = ChatTurnResult(
            content="Here is your note.",
            tool_calls=[],
            usage=TokenUsage(input_tokens=80, output_tokens=25, total_tokens=105),
        )
        mock_adapter.complete_chat_turn = AsyncMock(side_effect=[turn1, turn2])

        events = []
        async for ev in service._run_with_gold_tools(
            adapter=mock_adapter,
            model="test-model",
            messages=[{"role": "user", "content": "read notes"}],
            agent=agent_mock,
            user_id="user-1",
            run_id="run-tool-test",
        ):
            events.append(ev)

        # 2 usage events yielded (one per round)
        usage_events = [e for e in events if e.get("type") == "usage"]
        assert len(usage_events) == 2
        assert usage_events[0]["input_tokens"] == 50
        assert usage_events[0]["output_tokens"] == 15
        assert usage_events[0]["total_tokens"] == 65

        assert usage_events[1]["input_tokens"] == 80
        assert usage_events[1]["output_tokens"] == 25
        assert usage_events[1]["total_tokens"] == 105

        # Also verify tool event and token event
        tool_events = [e for e in events if e.get("type") == "tool"]
        token_events = [e for e in events if e.get("type") == "token"]
        assert len(tool_events) == 1
        assert len(token_events) >= 1


@pytest.mark.asyncio
async def test_analytics_api_endpoints(tmp_path: Path):
    journal_path = tmp_path / "journal.jsonl"
    journal = RunJournal(journal_path)
    journal.append(
        JournalEntry(
            run_id="run-api-1",
            agent_id="pythondev",
            user_id="user-1",
            team="eng",
            project_id="proj-1",
            channel="office_ui",
            stack="openai-compatible",
            model="llama3",
            effective_autonomy=50,
            status="ok",
            started_at="2026-08-26T10:00:00+00:00",
            ended_at="2026-08-26T10:00:05+00:00",
            connection_id="ollama",
            input_tokens=150,
            output_tokens=50,
            total_tokens=200,
            cost=0.0002,
        )
    )

    # Test summary endpoint
    summary = await get_analytics_summary(journal=journal, _user_id="user-1")
    assert summary["total_runs"] == 1
    assert summary["total_input_tokens"] == 150
    assert summary["total_output_tokens"] == 50
    assert summary["total_tokens"] == 200
    assert summary["total_cost"] == 0.0002

    # Test runs explorer endpoint
    runs_res = await get_analytics_runs(
        limit=10,
        team="eng",
        agent_id=None,
        project_id=None,
        stack=None,
        journal=journal,
        _user_id="user-1",
    )
    assert runs_res["count"] == 1
    assert runs_res["runs"][0]["run_id"] == "run-api-1"
    assert runs_res["runs"][0]["input_tokens"] == 150
    assert runs_res["runs"][0]["output_tokens"] == 50
    assert runs_res["runs"][0]["prompt_tokens"] == 150
    assert runs_res["runs"][0]["completion_tokens"] == 50
    assert runs_res["runs"][0]["total_tokens"] == 200
    assert runs_res["runs"][0]["cost"] == 0.0002


@pytest.mark.asyncio
async def test_connection_runtimes_endpoint_includes_tokens(tmp_path: Path):
    from agent_anystack.adapters.connections import ConnectionStore, StackConnection

    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="ollama",
            kind="inference",
            product="ollama",
            label="Ollama",
        )
    )
    journal = RunJournal(tmp_path / "journal.jsonl")
    journal.append(
        JournalEntry(
            run_id="run-tok-1",
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
            input_tokens=400,
            output_tokens=100,
            total_tokens=500,
            cost=0.0005,
        )
    )

    res = await connection_runtimes(
        connection_id="ollama",
        store=store,
        journal=journal,
        _user_id="admin",
    )
    assert len(res["runs"]) == 1
    assert res["runs"][0]["input_tokens"] == 400
    assert res["runs"][0]["output_tokens"] == 100
    assert res["runs"][0]["prompt_tokens"] == 400
    assert res["runs"][0]["completion_tokens"] == 100
    assert res["runs"][0]["total_tokens"] == 500
    assert res["runs"][0]["cost"] == 0.0005
