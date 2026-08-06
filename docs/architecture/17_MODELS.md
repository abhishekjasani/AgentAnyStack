# P17 — Local models (Stacks)

Curated Ollama pull from the UI. Inference stays OpenAI-compatible `/v1`; management uses Ollama native API only.

```mermaid
flowchart LR
    UI["Stacks UI"]
    API["GET/POST /models"]
    M["OllamaModelManager"]
    OL["Ollama /api/pull, tags, delete"]
    UI --> API --> M --> OL
```

| HTTP | Role |
| --- | --- |
| `GET /models` | engine reachability + curated catalog (`pulled`) + installed |
| `POST /models/pull` | SSE progress (`meta` / `progress` / `done` / `error`) |
| `POST /models/delete` | remove curated tag from `./data/ollama` |

**Class:** `OllamaModelManager` in `adapters/ollama_models.py` (only Ollama-specific module).  
**UI:** nav **Stacks** — Pull / progress / Delete.  

**Prereq (CPU — default):**

```bash
docker compose --profile ollama up -d
```

**NVIDIA GPU (optional):** same stack + `docker-compose.gpu.yml`. If start fails, use the CPU command (fallback). Details: [07_DOCKER.md](./07_DOCKER.md).

```bash
docker compose --profile ollama -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

```text
+ OK: pull allowlisted curated tags only
- BAD: expose arbitrary registry pull from UI
+ OK: chat via /v1; pull via /api/pull
- BAD: bake weights into the image
+ OK: CPU default; GPU opt-in override
- BAD: hard-require NVIDIA in base compose
```
