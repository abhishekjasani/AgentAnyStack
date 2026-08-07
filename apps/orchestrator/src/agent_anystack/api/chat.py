"""Agent chat — stream via orchestrator → OpenAI-compatible server."""

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.api.agents import get_office_repo
from agent_anystack.api.deps import get_user_id
from agent_anystack.channel_history import (
    ChannelHistoryStore,
    channel_history_root_from_database_url,
)
from agent_anystack.config import Settings, get_settings
from agent_anystack.memory import (
    ExtractJob,
    OkfStore,
    run_okf_extract,
    sqlite_path_from_database_url,
)
from agent_anystack.office import OfficeRepository
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import ChatRunService, journal_path_from_database_url

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)


def get_chat_service(
    settings: Settings = Depends(get_settings),
    repo: OfficeRepository = Depends(get_office_repo),
) -> ChatRunService:
    journal_file = journal_path_from_database_url(
        settings.database_url,
        Path("./data"),
    )
    history = ChannelHistoryStore(
        channel_history_root_from_database_url(settings.database_url, Path("./data"))
    )
    orc = repo.load_orchestrator()
    return ChatRunService(
        repo,
        RunJournal(journal_file),
        settings.openai_compatible_base_url,
        OkfStore(sqlite_path_from_database_url(settings.database_url)),
        pack_token_budget=orc.pack_token_budget,
        okf_extract_enabled=orc.okf_extract_enabled,
        channel_history=history,
        recent_history_days=orc.recent_history_days,
        recent_history_char_budget=orc.recent_history_char_budget,
        office_model=orc.model,
        openai_compatible_timeout=settings.openai_compatible_timeout,
    )


async def _background_okf_extract(job: ExtractJob, settings: Settings) -> None:
    store = OkfStore(sqlite_path_from_database_url(settings.database_url))
    adapter = OpenAICompatibleAdapter(
        settings.openai_compatible_base_url,
        timeout=settings.openai_compatible_timeout,
    )
    await run_okf_extract(job, okf=store, adapter=adapter)


@router.post("/agents/{agent_id}/chat")
async def chat(
    agent_id: str,
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_user_id),
    service: ChatRunService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    if service.repo.get_agent(agent_id) is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")

    async def event_stream():
        async for event in service.stream_agent_chat(
            agent_id=agent_id,
            user_id=user_id,
            message=body.message.strip(),
        ):
            if event.get("type") == "done" and "extract" in event:
                job: ExtractJob = event.pop("extract")
                background_tasks.add_task(_background_okf_extract, job, settings)
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
