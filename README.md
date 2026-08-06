# AgentAnyStack

**Any stack. One orchestrator.** — An office where agents work (desks, scoped memory, HITL), not a single chatbot.

Product truth: [`docs/`](docs/). Build phases: pair with the coding agent; review and commit each phase.

## Phases 1–16 done · P17 local models

**P17:** Stacks UI + `GET/POST /models` — curated Ollama pull with progress.  
Flow: [17_MODELS.md](docs/architecture/17_MODELS.md). Need Ollama: `docker compose --profile ollama up -d`.

### Docker

```bash
copy .env.example .env   # optional; compose overrides office/ollama paths
docker compose up --build -d

curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/agents
```

Volumes: `./office` → desks; `./data` → SQLite later.

Ollama is optional. **CPU (default)** always works; **NVIDIA GPU** is opt-in:

```bash
docker compose --profile ollama up -d
# GPU when NVIDIA + Docker GPU support exist; else use the line above (CPU fallback)
docker compose --profile ollama -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Details: [docs/architecture/07_DOCKER.md](docs/architecture/07_DOCKER.md).

### Run locally (without Docker)

From the **repo root** (`venv/` gitignored, Python 3.12):

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

# create a desk (no seed agents in the image)
curl -X POST http://127.0.0.1:8787/agents -H "Content-Type: application/json" -d "{\"id\":\"ba\",\"name\":\"Business Analyst\",\"team\":\"eng\",\"stack\":\"openai-compatible\",\"model\":\"llama3.2\"}"
```

`.dockerignore` excludes `venv/`, `.env`, and host `data/` contents from the build context.

Run local uvicorn from the **repo root** so `OFFICE_REPO_PATH=./office` resolves correctly.

## License

Apache-2.0 — see [LICENSE](LICENSE).
