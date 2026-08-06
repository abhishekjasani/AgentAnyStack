"""OKF export — DB → office/memory/ leave-path snapshot (not hot pack path)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_anystack.memory.fact import OkfFact
from agent_anystack.memory.store import OkfStore


@dataclass
class ExportResult:
    root: str
    teams: list[str]
    fact_count: int
    archived_count: int
    exported_at: str


def _frontmatter(fact: OkfFact) -> str:
    meta = {
        "id": fact.id,
        "type": fact.type.value,
        "scope": fact.scope,
        "projects": fact.projects,
        "tags": fact.tags,
        "domain": fact.domain,
        "created_by_user": fact.created_by_user,
        "created": fact.created,
        "pinned": fact.pinned,
        "archived": fact.archived,
        "sensitivity": fact.sensitivity.value,
        "source_run": fact.source_run,
    }
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n\n{fact.body.strip()}\n"


def _team_from_scope(scope: str) -> str | None:
    if scope.startswith("team:"):
        return scope.removeprefix("team:")
    return None


def _write_index(path: Path, title: str, lines: list[str]) -> None:
    body = "\n".join(lines).rstrip() + "\n"
    path.write_text(f"# {title}\n\n{body}", encoding="utf-8")


def export_okf_to_memory(
    store: OkfStore,
    office_root: Path,
    *,
    team: str | None = None,
    include_archived: bool = True,
) -> ExportResult:
    """
    Write OKF markdown bundle under office/memory/.

    Layout:
      memory/index.md
      memory/teams/<team>/index.md
      memory/teams/<team>/<fact-id>.md
      memory/teams/<team>/archive/<fact-id>.md   # archived only
    """
    memory_root = office_root.resolve() / "memory"
    memory_root.mkdir(parents=True, exist_ok=True)

    if team:
        teams = [team]
    else:
        teams = []
        for scope in store.list_scopes():
            t = _team_from_scope(scope)
            if t:
                teams.append(t)
        teams = sorted(set(teams))

    exported_at = datetime.now(timezone.utc).isoformat()
    fact_count = 0
    archived_count = 0
    team_summaries: list[str] = []

    for t in teams:
        facts = store.list_team_facts(t, include_archived=include_archived)
        team_dir = memory_root / "teams" / t
        active_dir = team_dir
        archive_dir = team_dir / "archive"
        active_dir.mkdir(parents=True, exist_ok=True)

        # Clear previous export for this team (leave-path snapshot replace)
        for old in active_dir.glob("*.md"):
            if old.name != "index.md":
                old.unlink(missing_ok=True)
        if archive_dir.is_dir():
            for old in archive_dir.glob("*.md"):
                old.unlink(missing_ok=True)

        active_links: list[str] = []
        archive_links: list[str] = []
        for fact in facts:
            text = _frontmatter(fact)
            if fact.archived:
                archive_dir.mkdir(parents=True, exist_ok=True)
                out = archive_dir / f"{fact.id}.md"
                archived_count += 1
                archive_links.append(f"- [{fact.id}](./archive/{fact.id}.md) — {fact.body[:80]}")
            else:
                out = active_dir / f"{fact.id}.md"
                fact_count += 1
                active_links.append(f"- [{fact.id}](./{fact.id}.md) — {fact.body[:80]}")
            out.write_text(text, encoding="utf-8")

        index_lines = [
            f"Exported: `{exported_at}`",
            f"Scope: `team:{t}`",
            "",
            "## Active",
            *(active_links or ["_(none)_"]),
            "",
            "## Archive",
            *(archive_links or ["_(none)_"]),
        ]
        _write_index(team_dir / "index.md", f"Team OKF — {t}", index_lines)
        team_summaries.append(
            f"- [{t}](./teams/{t}/index.md) — {len(active_links)} active, "
            f"{len(archive_links)} archived"
        )

    root_lines = [
        f"Exported: `{exported_at}`",
        "",
        "Portable OKF snapshot of shared team facts (SQLite is the hot path).",
        "",
        "## Teams",
        *(team_summaries or ["_(no team facts)_"]),
    ]
    _write_index(memory_root / "index.md", "Office memory export", root_lines)

    return ExportResult(
        root=str(memory_root),
        teams=teams,
        fact_count=fact_count,
        archived_count=archived_count,
        exported_at=exported_at,
    )
