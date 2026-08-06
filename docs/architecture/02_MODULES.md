# Modules

Desk **data** ≠ orchestrator **code**.

```mermaid
flowchart TB
    API[api routers]
    DOM[domain Pydantic]
    OFF[office OfficeRepository]
    CFG[config Settings]
    AD[adapters later]
    MEM[memory later]
    RUN[runs later]
    HITL[hitl later]

    API --> OFF
    API --> DOM
    OFF --> DOM
    API --> CFG
    RUN --> AD
    RUN --> MEM
    RUN --> HITL
```

## Package layout

```text
apps/orchestrator/src/agent_anystack/
  main.py              # app factory
  config.py            # env / .env (platform bucket)
  api/health.py        # GET /health
  api/agents.py        # GET/POST agents, GET /org
  domain/agent.py      # AgentConfig, CreateAgentRequest, …
  domain/org.py        # OrgConfig
  office/repository.py # load/write office/ tree
  adapters/            # llm.py — StackAdapter + OpenAICompatibleAdapter (+ later wires)
  memory/              # later — gold + OKF + pack
  runs/                # later — run_id + journal
  hitl/                # later — approval cards
```

## Major types (now)

| Name | Role |
| --- | --- |
| `Settings` | Platform env (`OFFICE_REPO_PATH`, DB, Ollama URL) |
| `OrgConfig` | `office/org.yaml` |
| `AgentConfig` | One desk’s `agent.yaml` |
| `CreateAgentRequest` | UI/API create payload |
| `OfficeRepository` | Read/write desks on disk |
| `AgentExistsError` | Duplicate agent id |
| `AutonomyCeilingError` | Agent autonomy > org max |

```text
+ OK: from agent_anystack.office import OfficeRepository, AgentExistsError
- BAD: Python class AnalystAgent under apps/.../agents/

+ OK: AgentConfig = yaml settings; AGENT.md = persona text (separate file)
- BAD: put full AGENT.md body inside AgentConfig always
```

## Major types (later)

| Name | Role |
| --- | --- |
| `StackAdapter` | `stream_chat(...)` — OpenAI-compatible first (Ollama/vLLM via URL) |
| `GoldStore` / `OkfStore` / `Packer` | Memory read/write |
| `RunService` | `run_id`, journal, envelope |
| `ApprovalCard` | HITL queue |
