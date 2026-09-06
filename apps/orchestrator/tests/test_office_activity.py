from dataclasses import replace
from types import SimpleNamespace

import pytest
from agent_anystack.config import Settings, get_settings
from agent_anystack.main import create_app
from agent_anystack.runs.activity import ActivityStore
from agent_anystack.runs.journal import JournalEntry, RunJournal
from agent_anystack.runs.service import ChatRunService
from fastapi.testclient import TestClient


def test_activity_shared_across_instances_and_expired(tmp_path, monkeypatch):
    store = ActivityStore(tmp_path / "activity.sqlite3")
    store.put({"run_id": "one", "agent_id": "writer", "status": "working"})
    other = ActivityStore(store.path)
    assert other.active()[0]["run_id"] == "one"
    other.put({"run_id": "one", "agent_id": "writer", "status": "thinking"})
    assert store.active()[0]["status"] == "thinking"
    monkeypatch.setattr("agent_anystack.runs.activity.time.time", lambda: 10**12)
    assert store.active() == []


def test_activity_api_scopes_user_and_excludes_approval_audit(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/office.db")
    journal = RunJournal(tmp_path / "journal.jsonl")
    entry = JournalEntry(
        run_id="run-first",
        agent_id="writer",
        user_id="admin",
        team="eng",
        project_id=None,
        channel="office_ui",
        stack="test",
        model="test",
        effective_autonomy=50,
        status="ok",
        started_at="2026-09-05",
    )
    journal.append(entry)
    journal.append(replace(entry, run_id="run-other-user", user_id="alice"))
    journal.append(replace(entry, run_id="run-approval", approval_id="card-1"))
    journal.append(replace(entry, run_id="run-latest", status="error"))
    activity = ActivityStore(tmp_path / "activity.sqlite3")
    activity.put({"run_id": "live-admin", "user_id": "admin"})
    activity.put({"run_id": "live-alice", "user_id": "alice"})
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        result = client.get("/office/activity").json()
        assert [r["run_id"] for r in result["recent"]] == ["run-latest", "run-first"]
        assert [r["run_id"] for r in result["active"]] == ["live-admin"]
        result = client.get("/office/activity", headers={"X-User-Id": "alice"}).json()
        assert [r["run_id"] for r in result["recent"]] == ["run-other-user"]
        assert [r["run_id"] for r in result["active"]] == ["live-alice"]


def fake_service(tmp_path):
    service = ChatRunService.__new__(ChatRunService)
    service.journal = RunJournal(tmp_path / "journal.jsonl")
    service.repo = SimpleNamespace(
        get_agent=lambda _: SimpleNamespace(team="eng", workspace=None)
    )
    return service


@pytest.mark.asyncio
async def test_presence_tracks_stream_and_cleans_up_on_completion(tmp_path):
    service = fake_service(tmp_path)

    async def events(**kwargs):
        yield {
            "type": "meta",
            "run_id": "run-live",
            "agent_id": "writer",
            "user_id": "admin",
        }
        yield {"type": "thinking", "text": "private reasoning"}
        yield {"type": "tool", "name": "read_gold"}
        yield {"type": "token", "text": "response"}
        yield {"type": "done"}

    service._stream_agent_chat = events
    statuses = []
    store = ActivityStore(tmp_path / "activity.sqlite3")
    async for event in service.stream_agent_chat(
        agent_id="writer", user_id="admin", message="private prompt"
    ):
        row = store.active()[0]
        statuses.append(row["status"])
        assert "text" not in row
        assert "message" not in row
    assert statuses == ["working", "thinking", "using tool", "responding", "finishing"]
    assert store.active() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_presence_cleans_up_on_disconnect_or_exception(tmp_path, failure):
    service = fake_service(tmp_path)

    async def events(**kwargs):
        yield {
            "type": "meta",
            "run_id": "run-live",
            "agent_id": "writer",
            "user_id": "admin",
        }
        raise RuntimeError("adapter failure")

    service._stream_agent_chat = events
    stream = service.stream_agent_chat(
        agent_id="writer", user_id="admin", message="hello"
    )
    await anext(stream)
    store = ActivityStore(tmp_path / "activity.sqlite3")
    assert len(store.active()) == 1
    if failure:
        with pytest.raises(RuntimeError):
            await anext(stream)
    else:
        await stream.aclose()
    assert store.active() == []
