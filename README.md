# AgentAnyStack

**Any stack. One orchestrator.** — An office where agents work (desks, scoped memory, HITL), not a single chatbot.

Product truth: [`docs/`](docs/). Build phases: pair with the coding agent; review and commit each phase.

## Phase 3 (current)

Create desks via API (no seed agents):

```bash
curl -X POST http://127.0.0.1:8787/agents -H "Content-Type: application/json" -d "{\"id\":\"ba\",\"name\":\"Business Analyst\",\"team\":\"eng\",\"stack\":\"openai-compatible\",\"model\":\"llama3.2\",\"persona_markdown\":\"# BA\\n\\n## Mission\\nClarify requirements.\\n\"}"

curl http://127.0.0.1:8787/agents
curl http://127.0.0.1:8787/agents/ba
```

Writes `office/teams/<team>/agents/<id>/{agent.yaml,AGENT.md,gold/}`.

Also: `GET /health`, `GET /org`, `GET /agents` (empty until create).

### Prerequisites

- **Python 3.12** (stable; e.g. 3.12.10). Repo `requires-python = ">=3.12"`.

### Run locally

From the **repo root** (venv lives here as `venv/`, gitignored):

```bash
# create once — Windows (py launcher) / or full path to python3.12
py -3.12 -m venv venv
# Unix: python3.12 -m venv venv

# activate
# Windows PowerShell: .\venv\Scripts\Activate.ps1
# Unix:               source venv/bin/activate

pip install -e "./apps/orchestrator[dev]"
copy .env.example .env   # Unix: cp .env.example .env

uvicorn agent_anystack.main:app --reload --host 0.0.0.0 --port 8787
```

```bash
curl http://127.0.0.1:8787/health
# {"status":"ok","version":"0.1.0"}

curl http://127.0.0.1:8787/agents
# []

curl http://127.0.0.1:8787/org
# {"id":"default","name":"AgentAnyStack",...}
```

`.dockerignore` excludes `venv/`, `.env`, and host `data/` so images stay lean (Docker image wiring in a later phase).

Run uvicorn from the **repo root** so `OFFICE_REPO_PATH=./office` resolves correctly.

## License

Apache-2.0 — see [LICENSE](LICENSE).
