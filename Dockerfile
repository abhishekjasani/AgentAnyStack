# AgentAnyStack orchestrator — Python 3.12 + OpenCode CLI (harness spawn)
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY apps/orchestrator /tmp/orchestrator
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates bash \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://opencode.ai/install | bash \
    && pip install --no-cache-dir /tmp/orchestrator \
    && rm -rf /tmp/orchestrator

COPY apps/office-ui /ui

ENV HOST=0.0.0.0 \
    PORT=8787 \
    OFFICE_REPO_PATH=/office \
    OFFICE_UI_PATH=/ui \
    PROJECTS_ROOT=/projects \
    DATABASE_URL=sqlite:////data/office.db \
    OLLAMA_BASE_URL=http://ollama:11434 \
    PATH="/root/.opencode/bin:${PATH}"

EXPOSE 8787

CMD ["uvicorn", "agent_anystack.main:app", "--host", "0.0.0.0", "--port", "8787"]
