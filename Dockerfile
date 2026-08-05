# AgentAnyStack orchestrator — Python 3.12
FROM python:3.12-slim-bookworm

WORKDIR /app

# Install package only (office/ + data/ mounted at runtime)
COPY apps/orchestrator /tmp/orchestrator
RUN pip install --no-cache-dir /tmp/orchestrator \
    && rm -rf /tmp/orchestrator

ENV HOST=0.0.0.0 \
    PORT=8787 \
    OFFICE_REPO_PATH=/office \
    DATABASE_URL=sqlite:////data/office.db \
    OLLAMA_BASE_URL=http://ollama:11434

EXPOSE 8787

CMD ["uvicorn", "agent_anystack.main:app", "--host", "0.0.0.0", "--port", "8787"]
