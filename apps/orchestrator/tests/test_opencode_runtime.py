from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_anystack.adapters.connections import ConnectionStore, StackConnection
from agent_anystack.adapters.opencode.runtime import (
    _sessions,
    get_session,
    kill_session,
    list_sessions,
    register_session,
    stop_serve_by_cwd,
)
from agent_anystack.api.connections import connection_runtimes, kill_connection_session
from agent_anystack.runs.journal import RunJournal


@pytest.fixture(autouse=True)
def clean_sessions():
    _sessions.clear()
    yield
    _sessions.clear()


@pytest.mark.asyncio
async def test_kill_session_removes_from_runtime_registry():
    sess = register_session(
        session_id="ses_test_123",
        agent_id="pythondev",
        user_id="admin",
        run_id="run-12345",
        cwd="/tmp/project",
        connection_id="opencode",
        base_url="",
    )
    assert sess.session_id == "ses_test_123"
    assert len(list_sessions()) == 1
    assert get_session("ses_test_123") is not None

    # Kill session
    killed = await kill_session("ses_test_123")
    assert killed.session_id == "ses_test_123"
    assert killed.status == "killed"
    assert killed.ended_at is not None

    # Verify session is removed from active registry
    assert get_session("ses_test_123") is None
    assert len(list_sessions()) == 0

    # Killing again should raise KeyError
    with pytest.raises(KeyError):
        await kill_session("ses_test_123")


@pytest.mark.asyncio
async def test_kill_connection_session_api_endpoint(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="oc-local",
            kind="agent_runtime",
            product="opencode",
            label="OpenCode Local",
            aliases=["opencode"],
        )
    )
    journal = RunJournal(tmp_path / "journal.jsonl")

    register_session(
        session_id="ses_api_test",
        agent_id="pythondev",
        user_id="admin",
        run_id="run-api-123",
        cwd="/tmp/project",
        connection_id="oc-local",
        base_url="",
    )

    # Inspect runtimes before kill
    res_before = await connection_runtimes(
        connection_id="oc-local",
        store=store,
        journal=journal,
        _user_id="admin",
    )
    assert len(res_before["sessions"]) == 1
    assert res_before["sessions"][0]["session_id"] == "ses_api_test"

    # Call kill endpoint
    kill_res = await kill_connection_session(
        connection_id="oc-local",
        session_id="ses_api_test",
        store=store,
        _user_id="admin",
    )
    assert kill_res["ok"] is True
    assert kill_res["session"]["status"] == "killed"

    # Inspect runtimes after kill: session is removed from runtimes
    res_after = await connection_runtimes(
        connection_id="oc-local",
        store=store,
        journal=journal,
        _user_id="admin",
    )
    assert len(res_after["sessions"]) == 0


@pytest.mark.asyncio
async def test_stop_serve_by_cwd_removes_sessions():
    register_session(
        session_id="ses_serve_1",
        agent_id="pythondev",
        user_id="admin",
        run_id="run-1",
        cwd="/tmp/test_dir",
        connection_id="opencode",
    )
    assert len(list_sessions()) == 1

    with patch("agent_anystack.adapters.opencode.serve.stop_serve", new_callable=AsyncMock):
        await stop_serve_by_cwd("/tmp/test_dir", connection_id="opencode")

    assert len(list_sessions()) == 0
