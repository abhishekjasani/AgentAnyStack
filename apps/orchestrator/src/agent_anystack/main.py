"""FastAPI application factory."""

from fastapi import FastAPI

from agent_anystack import __version__
from agent_anystack.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgentAnyStack",
        description="Office backbone for agents — orchestrator API",
        version=__version__,
    )
    app.include_router(health_router)
    return app


app = create_app()
