"""Unified office channel — one orchestrator entry for office Q&A + agent chat + history + HITL."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_anystack.api.agents import get_office_repo
from agent_anystack.api.approvals import ApprovalCardOut, get_approval_service
from agent_anystack.api.chat import _background_okf_extract, get_chat_service
from agent_anystack.api.deps import get_user_id
from agent_anystack.api.office import get_office_qa
from agent_anystack.channel_history import (
    ChannelHistoryStore,
    ChannelMessage,
    channel_history_root_from_database_url,
    new_message_id,
    utc_now,
)
from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.agent import AgentSummary
from agent_anystack.hitl import ApprovalService, ApprovalStatus
from agent_anystack.memory import ExtractJob
from agent_anystack.office import OfficeRepository
from agent_anystack.office_qa import OfficeQaService
from agent_anystack.runs.service import ChatRunService

router = APIRouter(tags=["channel"])


class ChannelChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)
    agent_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]*$")
    team: str = Field(default="eng", pattern=r"^[a-z][a-z0-9_-]*$")


class ChannelMessageOut(BaseModel):
    id: str
    role: str
    text: str
    created_at: str
    mode: str
    agent_id: str | None = None
    kind: str | None = None
    run_id: str | None = None

    @classmethod
    def from_msg(cls, m: ChannelMessage) -> "ChannelMessageOut":
        return cls(
            id=m.id,
            role=m.role,
            text=m.text,
            created_at=m.created_at,
            mode=m.mode,
            agent_id=m.agent_id,
            kind=m.kind,
            run_id=m.run_id,
        )


class ChannelState(BaseModel):
    """Bootstrap: desks + pending HITL + this user's single-thread history."""

    user_id: str
    agents: list[AgentSummary]
    pending_approvals: list[ApprovalCardOut]
    messages: list[ChannelMessageOut]
    office_hint: str = (
        "One channel per user. Select Office or a desk agent, then send. "
        "History is shared across desks for this user."
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _pending_out(svc: ApprovalService) -> list[ApprovalCardOut]:
    return [
        ApprovalCardOut.from_card(c)
        for c in svc.list_cards(status=ApprovalStatus.pending_human, limit=50)
    ]


def get_channel_history(settings: Settings = Depends(get_settings)) -> ChannelHistoryStore:
    return ChannelHistoryStore(
        channel_history_root_from_database_url(settings.database_url, Path("./data"))
    )


@router.get("/channel", response_model=ChannelState)
async def channel_state(
    user_id: str = Depends(get_user_id),
    repo: OfficeRepository = Depends(get_office_repo),
    approvals: ApprovalService = Depends(get_approval_service),
    history: ChannelHistoryStore = Depends(get_channel_history),
) -> ChannelState:
    """One payload for unified chat UI: agents, pending cards, per-user history."""
    return ChannelState(
        user_id=user_id,
        agents=repo.list_agent_summaries(),
        pending_approvals=_pending_out(approvals),
        messages=[
            ChannelMessageOut.from_msg(m) for m in history.list_messages(user_id)
        ],
    )


@router.get("/channel/history", response_model=list[ChannelMessageOut])
async def channel_history(
    user_id: str = Depends(get_user_id),
    history: ChannelHistoryStore = Depends(get_channel_history),
    limit: int = 200,
) -> list[ChannelMessageOut]:
    return [
        ChannelMessageOut.from_msg(m)
        for m in history.list_messages(user_id, limit=limit)
    ]


@router.post("/channel/chat")
async def channel_chat(
    body: ChannelChatRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
    chat: ChatRunService = Depends(get_chat_service),
    qa: OfficeQaService = Depends(get_office_qa),
    approvals: ApprovalService = Depends(get_approval_service),
    history: ChannelHistoryStore = Depends(get_channel_history),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """
    Single SSE channel. Persists one transcript per user (all agents + office).

    - No agent_id → office front desk
    - agent_id set → desk chat
    - Ends with approvals snapshot
    """
    message = body.message.strip()
    agent_id = (body.agent_id or "").strip() or None

    if agent_id is not None and chat.repo.get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")

    mode = "agent" if agent_id else "office"
    history.append(
        user_id,
        ChannelMessage(
            id=new_message_id(),
            role="user",
            text=message,
            created_at=utc_now(),
            mode=mode,
            agent_id=agent_id,
        ),
    )

    async def event_stream() -> AsyncIterator[str]:
        if agent_id is None:
            yield _sse(
                {
                    "type": "meta",
                    "mode": "office",
                    "user_id": user_id,
                    "team": body.team,
                    "agent_id": None,
                }
            )
            result = await qa.ask(message=message, team=body.team)
            history.append(
                user_id,
                ChannelMessage(
                    id=new_message_id(),
                    role="office",
                    text=result.answer,
                    created_at=utc_now(),
                    mode="office",
                    kind=result.kind.value,
                ),
            )
            yield _sse(
                {
                    "type": "answer",
                    "mode": "office",
                    "kind": result.kind.value,
                    "text": result.answer,
                    "team": result.team or body.team,
                    "citations": [
                        {"fact_id": c.fact_id, "run_id": c.run_id}
                        for c in result.citations
                    ],
                }
            )
            yield _sse(
                {
                    "type": "approvals",
                    "cards": [c.model_dump(mode="json") for c in _pending_out(approvals)],
                }
            )
            yield _sse({"type": "done", "mode": "office"})
            return

        assistant_parts: list[str] = []
        run_id: str | None = None
        async for event in chat.stream_agent_chat(
            agent_id=agent_id,
            user_id=user_id,
            message=message,
        ):
            if event.get("type") == "meta":
                run_id = event.get("run_id")
                event = {**event, "mode": "agent"}
            elif event.get("type") == "token":
                assistant_parts.append(str(event.get("text") or ""))
            if event.get("type") == "done" and "extract" in event:
                job: ExtractJob = event.pop("extract")
                background_tasks.add_task(_background_okf_extract, job, settings)
            yield _sse(event)

        assistant_text = "".join(assistant_parts).strip()
        if assistant_text:
            history.append(
                user_id,
                ChannelMessage(
                    id=new_message_id(),
                    role="assistant",
                    text=assistant_text,
                    created_at=utc_now(),
                    mode="agent",
                    agent_id=agent_id,
                    run_id=run_id,
                ),
            )

        yield _sse(
            {
                "type": "approvals",
                "cards": [c.model_dump(mode="json") for c in _pending_out(approvals)],
            }
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
