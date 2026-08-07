"""Structured gold notes + tools."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_anystack.domain.agent import AgentConfig
from agent_anystack.office import GoldTooLargeError, OfficeRepository
from agent_anystack.office.gold_notes import format_gold_with_rules, load_gold_notes
from agent_anystack.tools.gold import GOLD_TOOL_SCHEMAS, execute_gold_tool


def _seed_desk(root: Path, *, team: str = "eng", agent_id: str = "ba") -> AgentConfig:
    desk = root / "teams" / team / "agents" / agent_id
    desk.mkdir(parents=True)
    (desk / "gold").mkdir()
    cfg = AgentConfig(
        id=agent_id,
        name="BA",
        team=team,
        stack="openai-compatible",
        model="llama3.2",
    )
    (desk / "agent.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json", exclude_none=True), sort_keys=False),
        encoding="utf-8",
    )
    (desk / "AGENT.md").write_text("# BA\n", encoding="utf-8")
    (root / "org.yaml").write_text(
        "id: acme\nname: Acme\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def repo(tmp_path: Path) -> tuple[OfficeRepository, AgentConfig]:
    root = tmp_path / "office"
    root.mkdir()
    agent = _seed_desk(root)
    return OfficeRepository(root, gold_max_chars=64_000), agent


def test_append_gets_unique_ids(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    a = r.append_gold_note(agent, "alice", "logo is round", run_id="run_1")
    b = r.append_gold_note(agent, "alice", "theme is blue", run_id="run_1")
    assert a.id != b.id
    assert a.id.startswith("g_")
    assert a.run_id == "run_1"
    notes = r.list_gold_notes(agent, "alice")
    assert len(notes) == 2
    assert notes[0].text == "logo is round"
    rendered = r.read_gold(agent, "alice")
    assert a.id in rendered and b.id in rendered


def test_delete_single_and_bulk(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    a = r.append_gold_note(agent, "alice", "one")
    b = r.append_gold_note(agent, "alice", "two")
    c = r.append_gold_note(agent, "alice", "three")
    deleted = r.delete_gold_notes(agent, "alice", [a.id, c.id])
    assert set(deleted) == {a.id, c.id}
    left = r.list_gold_notes(agent, "alice")
    assert len(left) == 1
    assert left[0].id == b.id


def test_clear_gold(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    r.append_gold_note(agent, "alice", "x")
    r.clear_gold(agent, "alice")
    assert r.list_gold_notes(agent, "alice") == []
    assert r.read_gold(agent, "alice") == ""


def test_users_isolated(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    r.append_gold_note(agent, "alice", "alice note")
    r.append_gold_note(agent, "bob", "bob note")
    assert len(r.list_gold_notes(agent, "alice")) == 1
    assert len(r.list_gold_notes(agent, "bob")) == 1
    assert "bob" not in r.read_gold(agent, "alice")


def test_legacy_md_migrates(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    legacy = r.gold_path(agent, "alice")
    legacy.write_text("old freeform notes\n", encoding="utf-8")
    notes = r.list_gold_notes(agent, "alice")
    assert len(notes) == 1
    assert notes[0].text == "old freeform notes"
    assert not legacy.is_file()
    jsonl = r.gold_dir(agent) / "alice.jsonl"
    assert jsonl.is_file()


def test_size_cap(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    tiny = OfficeRepository(r.root, gold_max_chars=400)
    tiny.append_gold_note(agent, "alice", "ok")
    with pytest.raises(GoldTooLargeError):
        tiny.append_gold_note(agent, "alice", "x" * 500)


def test_tools_append_delete_clear(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    names = {t["function"]["name"] for t in GOLD_TOOL_SCHEMAS}
    assert names == {"read_gold", "append_gold", "delete_gold", "clear_gold"}

    out = execute_gold_tool(
        "append_gold",
        {"text": "logo is round"},
        repo=r,
        agent=agent,
        user_id="alice",
        run_id="run_abc",
    )
    assert out.startswith("ok: appended id=")
    nid = out.split("id=", 1)[1].strip()

    out2 = execute_gold_tool(
        "append_gold",
        {"text": "theme blue"},
        repo=r,
        agent=agent,
        user_id="alice",
        run_id="run_abc",
    )
    nid2 = out2.split("id=", 1)[1].strip()
    assert nid != nid2

    read = execute_gold_tool(
        "read_gold",
        {},
        repo=r,
        agent=agent,
        user_id="alice",
    )
    assert nid in read and "logo is round" in read
    assert "append_gold" in read  # rules header

    deleted = execute_gold_tool(
        "delete_gold",
        {"ids": [nid]},
        repo=r,
        agent=agent,
        user_id="alice",
    )
    assert "deleted 1" in deleted
    assert nid not in r.read_gold(agent, "alice")
    assert nid2 in r.read_gold(agent, "alice")

    bulk = execute_gold_tool(
        "delete_gold",
        {"ids": [nid2, "g_missing"]},
        repo=r,
        agent=agent,
        user_id="alice",
    )
    assert "deleted 1" in bulk
    assert "missing=g_missing" in bulk

    r.append_gold_note(agent, "alice", "again")
    cleared = execute_gold_tool(
        "clear_gold",
        {},
        repo=r,
        agent=agent,
        user_id="alice",
    )
    assert cleared.startswith("ok: gold cleared")
    assert r.list_gold_notes(agent, "alice") == []


def test_delete_accepts_single_id_string(
    repo: tuple[OfficeRepository, AgentConfig],
) -> None:
    r, agent = repo
    n = r.append_gold_note(agent, "alice", "x")
    out = execute_gold_tool(
        "delete_gold",
        {"id": n.id},
        repo=r,
        agent=agent,
        user_id="alice",
    )
    assert "deleted 1" in out


def test_format_rules_outside_store(repo: tuple[OfficeRepository, AgentConfig]) -> None:
    r, agent = repo
    r.append_gold_note(agent, "alice", "logo is square")
    notes = r.list_gold_notes(agent, "alice")
    formatted = format_gold_with_rules(notes)
    assert formatted.startswith("## Gold")
    # File must not contain the rules header as a note row
    raw = load_gold_notes(r.gold_dir(agent), "alice")
    assert all("append_gold" not in n.text for n in raw)
