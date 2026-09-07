"""Analytics & trust surface — summary metrics and run explorer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import journal_path_from_database_url

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_journal(settings: Settings = Depends(get_settings)) -> RunJournal:
    return RunJournal(
        journal_path_from_database_url(settings.database_url, Path("./data"))
    )


@router.get("/summary")
async def get_analytics_summary(
    journal: RunJournal = Depends(get_journal),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Overall token usage, cost, and breakdown by stack and agent."""
    return journal.summary()


@router.get("/runs")
async def get_analytics_runs(
    limit: int = Query(50, ge=1, le=200),
    team: str | None = Query(None),
    agent_id: str | None = Query(None),
    project_id: str | None = Query(None),
    stack: str | None = Query(None),
    journal: RunJournal = Depends(get_journal),
    _user_id: str = Depends(get_user_id),
) -> dict[str, Any]:
    """Run explorer timeline rows with tokens, cost, and status."""
    entries = journal.recent_runs(
        limit=limit,
        team=team,
        agent_id=agent_id,
        project_id=project_id,
        stack=stack,
    )
    rows = [
        {
            "run_id": e.run_id,
            "agent_id": e.agent_id,
            "user_id": e.user_id,
            "team": e.team,
            "project_id": e.project_id,
            "channel": e.channel,
            "stack": e.stack,
            "model": e.model,
            "effective_autonomy": e.effective_autonomy,
            "status": e.status,
            "started_at": e.started_at,
            "ended_at": e.ended_at,
            "error": e.error,
            "connection_id": e.connection_id,
            "prompt_tokens": e.prompt_tokens,
            "completion_tokens": e.completion_tokens,
            "total_tokens": e.total_tokens,
            "reasoning_tokens": e.reasoning_tokens,
            "cost": e.cost,
            "estimated": e.estimated,
        }
        for e in entries
    ]
    return {"runs": rows, "count": len(rows)}
