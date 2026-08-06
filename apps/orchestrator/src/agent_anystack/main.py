"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent_anystack import __version__
from agent_anystack.api.agents import router as agents_router
from agent_anystack.api.chat import router as chat_router
from agent_anystack.api.gold import router as gold_router
from agent_anystack.api.health import router as health_router
from agent_anystack.api.me import router as me_router
from agent_anystack.config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentAnyStack",
        description="Office backbone for agents — orchestrator API",
        version=__version__,
    )
    app.include_router(health_router)
    app.include_router(me_router)
    app.include_router(agents_router)
    app.include_router(gold_router)
    app.include_router(chat_router)

    ui_dir = Path(get_settings().office_ui_path).resolve()
    if ui_dir.is_dir():
        index = ui_dir / "index.html"

        @app.get("/")
        async def office_ui() -> FileResponse:
            return FileResponse(index)

        app.mount("/assets", StaticFiles(directory=ui_dir), name="assets")

    return app


app = create_app()
