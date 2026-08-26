from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_anystack.adapters.llm import (
    ChatTurnResult,
    OpenAICompatibleAdapter,
    StreamingThinkParser,
    extract_reasoning_and_content,
)
from agent_anystack.adapters.thinking import append_thinking, read_thinking
from agent_anystack.runs.service import ChatRunService


def test_extract_reasoning_and_content():
    # Plain text
    c, r = extract_reasoning_and_content("Hello world")
    assert c == "Hello world"
    assert r == ""

    # Explicit reasoning
    c, r = extract_reasoning_and_content("42", raw_reasoning="Let me think...")
    assert c == "42"
    assert r == "Let me think..."

    # In-band think block
    c, r = extract_reasoning_and_content("<think>thinking step 1</think>The answer is 42.")
    assert c == "The answer is 42."
    assert r == "thinking step 1"

    # Multiple think blocks
    c, r = extract_reasoning_and_content(
        "<think>step 1</think>中间<think>step 2</think>Done."
    )
    assert c == "中间Done."
    assert r == "step 1\nstep 2"

    # Unclosed think block
    c, r = extract_reasoning_and_content("<think>I am still thinking...")
    assert c == ""
    assert r == "I am still thinking..."

    # Empty inputs
    c, r = extract_reasoning_and_content(None, None)
    assert c == ""
    assert r == ""


def test_streaming_think_parser():
    parser = StreamingThinkParser()

    # Plain text without tags
    events = parser.feed("Hello ")
    assert events == [("token", "Hello ")]
    events = parser.feed("world!")
    assert events == [("token", "world!")]
    assert parser.flush() == []

    # Stream with <think> tag split across chunks
    parser = StreamingThinkParser()
    out = []
    chunks = ["<th", "ink>pondering...", "</th", "ink>Result: 42"]
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    out.extend(parser.flush())

    assert out == [
        ("thinking", "pondering..."),
        ("token", "Result: 42"),
    ]

    # Stream with prefix that turns out not to be a tag
    parser = StreamingThinkParser()
    out = []
    chunks = ["Here is <", "a code tag> inside"]
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    out.extend(parser.flush())
    assert "".join(text for _, text in out) == "Here is <a code tag> inside"
    assert all(kind == "token" for kind, _ in out)


def test_append_and_read_thinking(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    run_id = "run-abc-123"

    append_thinking(db_url, run_id, "Thought 1\n")
    append_thinking(db_url, run_id, "Thought 2")

    result = read_thinking(db_url, run_id)
    assert result["run_id"] == run_id
    assert result["chunks"] == ["Thought 1", "Thought 2"]
    assert result["text"] == "Thought 1Thought 2"


@pytest.mark.asyncio
async def test_openai_compatible_adapter_complete_turn_reasoning(monkeypatch):
    adapter = OpenAICompatibleAdapter("http://mock-llm:11434")

    fake_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "<think>Calculated 2+2=4</think>The answer is 4.",
                }
            }
        ]
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
        messages=[{"role": "user", "content": "2+2?"}],
    )
    assert turn.content == "The answer is 4."
    assert turn.reasoning == "Calculated 2+2=4"

    text = await adapter.complete_chat(
        model="test-model",
        messages=[{"role": "user", "content": "2+2?"}],
    )
    assert text == "The answer is 4."


@pytest.mark.asyncio
async def test_service_run_with_gold_tools_emits_thinking():
    with tempfile.TemporaryDirectory() as td:
        db_url = f"sqlite:///{td}/test.db"
        service = ChatRunService(
            repo=MagicMock(),
            journal=MagicMock(),
            openai_compatible_base_url="http://mock:11434",
            okf=MagicMock(),
            database_url=db_url,
        )
        mock_adapter = MagicMock()
        mock_adapter.complete_chat_turn = AsyncMock(
            return_value=ChatTurnResult(
                content="Final reply",
                reasoning="Step 1: Analyzed prompt\nStep 2: Formulated answer",
            )
        )
        agent = MagicMock()
        agent.id = "agent-1"
        agent.team = "team-1"

        events = []
        async for ev in service._run_with_gold_tools(
            adapter=mock_adapter,
            model="deepseek-r1",
            messages=[{"role": "user", "content": "hello"}],
            agent=agent,
            user_id="user-1",
            run_id="run-think-test-1",
        ):
            events.append(ev)

        thinking_texts = [e["text"] for e in events if e.get("type") == "thinking"]
        assert "".join(thinking_texts) == "Step 1: Analyzed prompt\nStep 2: Formulated answer"

        token_texts = [e["text"] for e in events if e.get("type") == "token"]
        assert "".join(token_texts) == "Final reply"

        persisted = read_thinking(db_url, "run-think-test-1")
        assert persisted["run_id"] == "run-think-test-1"
        assert persisted["text"] == "Step 1: Analyzed prompt\nStep 2: Formulated answer"
