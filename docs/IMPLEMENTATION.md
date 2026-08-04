# Implementation & design notes — for coding agents

**Purpose:** Single handoff so a new repo / coding agent can build AgentAnyStack without re-deriving decisions from chat history.

**Status:** Design agreed through 2026-08-04. This `cursor_teams` tree is a **Cursor-first TypeScript prototype** + docs. **Greenfield rebuild** = Python orchestrator. **Start with:** [V0_SCOPE.md](./V0_SCOPE.md).

**Related:** [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) · [ORCHESTRATOR.md](./ORCHESTRATOR.md) · [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) · [AGENT_DEFINITION.md](./AGENT_DEFINITION.md) · [V0_SCOPE.md](./V0_SCOPE.md) · [ANALYTICS.md](./ANALYTICS.md) · [CONNECT.md](./CONNECT.md) · [USE_CASES_MEMORY.md](./USE_CASES_MEMORY.md) · [LOCAL_MODEL_STACK.md](./LOCAL_MODEL_STACK.md)

---

## 0. Doc map (read in this order)

| Order | Doc | What you learn |
| --- | --- | --- |
| 1 | [V0_SCOPE.md](./V0_SCOPE.md) | **What to build now** — core + shell stubs; UI vs mockup |
| 2 | [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) | Pillars (unchanged), hierarchy, office-as-git, multi-user |
| 3 | [ORCHESTRATOR.md](./ORCHESTRATOR.md) | Gates, HITL, autonomy, MCP, office chat |
| 4 | [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) | Gold(a,u), OKF in DB, packing |
| 5 | [AGENT_DEFINITION.md](./AGENT_DEFINITION.md) | agent.yaml + AGENT.md; Office Envelope |
| 6 | [ANALYTICS.md](./ANALYTICS.md) · [CONNECT.md](./CONNECT.md) | Later tabs — journal/API now, deep UI later |
| 7 | **This file** | Stack, async, config buckets, slices |
| 8 | [USE_CASES_MEMORY.md](./USE_CASES_MEMORY.md) | Stories |
| 9 | [LOCAL_MODEL_STACK.md](./LOCAL_MODEL_STACK.md) | Ollama |
| — | [COMMANDS.md](./COMMANDS.md) · [WORKER.md](./WORKER.md) · [DOCKER.md](./DOCKER.md) | Legacy TS prototype |

---

## 1. Product in one screen

**Brand:** AgentAnyStack — *Any stack. One orchestrator.*  
**Core:** An **office where agents work** (desks, teams, floors, scoped memory, visible activity, controllability).  
**Not:** “best coding agent” or another LangGraph/Crew framework.

**Pillars:** (1) agent office (2) controllability 0–100 (3) org/project memory (4) no vendor lock-in — **unchanged**; see [V0_SCOPE.md](./V0_SCOPE.md).

**Hierarchy:** `Org → Floor (optional) → Team → Agent`  
**Horizontal axis:** `Project` (often git folder; unique immutable ids).  
**Slogan:** *Users share the room; they don’t share the notepad.*

| Concept | Meaning |
| --- | --- |
| **Team** | Room — shared OKF among teammates (all users’ facts packed) |
| **Gold** | Per **(agent, user)** notepad in git |
| **Shelf** | Floor/org OKF — policies, checklists; filtered by project when packing |
| **Connect line** | Gated door between teams — not auto-merge |
| **Office chat** | Ask orchestrator status/knowledge **without** an agent (cite-bound) |
| **Connect (channels)** | External product plugins → orchestrator ([CONNECT.md](./CONNECT.md)) — stub in v0 |
| **Analytics** | Trust / usage / graph ([ANALYTICS.md](./ANALYTICS.md)) — journal in v0, UI stub |

---

## 2. Target tech stack (agreed — green light)

```text
Python 3.12+  — orchestrator, memory pipeline, policy, DB, OKF export
TS/JS         — office UI; adapters that are clearly SDK-native in TS (optional sidecar)
YAML/git      — office definitions (org/floor/team/agent/links/catalog) — language-agnostic
```

| Layer | Choice | Notes |
| --- | --- | --- |
| API / WS | **FastAPI** + uvicorn | Async end-to-end |
| Validation | **Pydantic** v2 | JSON Schema first; same contract as former Zod intent |
| Shared OKF store | **SQLite** (CE) → **Postgres** (scale) | Hot path = DB |
| Config + gold | **Git office repo** | `gold/<user_id>.md` per agent |
| OKF portability | Export/import OKF tree | Leave-path + DR |
| UI | **Simple** shell (nav stubs OK) — not full mockup fidelity | [V0_SCOPE.md](./V0_SCOPE.md) |
| Local models | Ollama in Docker; OpenAI-compatible URL | [LOCAL_MODEL_STACK.md](./LOCAL_MODEL_STACK.md) |
| License intent | Apache-2.0 CE | See market research |

**Why Python is good design (not only comfort):** control plane is I/O + policy + DB; LLM/agent latency dominates; Pydantic/FastAPI/local-model ecosystem fit. Node prototype remains a **behavior reference**.

**Performance:** Python is fine. Do **not** optimize for GIL myths. Measure pack+route vs adapter TTFT.

---

## 3. Concurrency model (v0 — locked)

| Use | v0 | Do **not** |
| --- | --- | --- |
| HTTP / WS / DB / adapters | **`async` / `await`** | Thread-per-request architecture |
| Extract / export / prune after run | **`asyncio.create_task`** or FastAPI `BackgroundTasks` | Block the chat request |
| Survive restart / scale jobs | Later: **arq** (Redis) | **Celery on day one** |
| Sync-only library | Rare `asyncio.to_thread(...)` | Design around `threading.Thread` / ThreadPool |
| Heavy CPU | Not needed v0 | Multiprocessing as default |

**Rule:** No threading as an architecture in v0. No Celery in v0. No multiprocessing unless a profiler demands it.

```text
Chat / Office Q&A / Agent stream  →  async handlers
Agent run ends                    →  enqueue extract (create_task / BackgroundTasks)
Long extract must NOT sit inside the user’s chat await path
```

---

## 4. Office chat (orchestrator Q&A — no agent)

Users may ask the **office** about project **status** and **knowledge** without routing to Analyst/Developer/etc.

| Ask type | Source | LLM? |
| --- | --- | --- |
| Status (“what’s running?”) | Journal / runs registry | Optional; often pure code |
| Knowledge (“what’s our commission rule?”) | Deterministic OKF query / pack slice | Optional summarizer **with citations** |
| Do work (“build the hero”) | Route to an agent | Agent run |

**Rules:**

- Orchestrator **does not invent** business facts. Empty memory → say so.
- Every knowledge claim cites `fact_id` / `run_id`.
- Q&A is a **read path** — does **not** write OKF (writes still via agent report pipeline / explicit `remember:`).
- Chat grammar idea: `Office:` or default when no `AgentName:` prefix.
- Scope visible: which team/project shelf is being queried.

This does **not** reopen “orchestrator as free-roaming LLM persona.” It is **front desk**: retrieve + optional cite-bound phrase.

---

## 5. Multi-user & packing (summary)

- Same agent desk, many users → separate **`run_id`**, separate **`gold(a,u)`**.
- Shared OKF: stamp **`created_by_user`** for **audit only**; **pack all users’ room facts** (accept noise; prune later).
- Formula: `C(a, p, u) = gold(a,u) ∪ mem(team) ∪ (floor ∪ linkshare ∪ org) ∩ P(p)`  
  Full rules: [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md).

---

## 6. Controllability & HITL (summary)

**Effective autonomy** (ceiling + tighten-only user override):

```text
effective_max = min(org.max_autonomy, agent.max_autonomy ?? 100)
effective = clamp(user.override ?? agent.default ?? org.default, 0, effective_max)
```

**Approvers v1 (`permissive`):** requester ∪ org admin ∪ MCP/cred owner.  
**Later (`strict`):** org admin and/or MCP/cred owner only.

Detail: [ORCHESTRATOR.md](./ORCHESTRATOR.md) §4.1 · §6.0.2.

---

## 7. Hybrid storage & security TODOs

| Data | Runtime | Portability |
| --- | --- | --- |
| Org/floor/team/agent/links/catalog | Git | Clone |
| Gold(a,u) | Git | Clone |
| Shared OKF | DB | OKF export |
| Secrets (intended) | Vault/env | Never commit |

**Known gaps (do not market as solved):**

1. Gold/OKF may accidentally contain credentials — scrub later.  
2. MCP `_locked` + grant is **best-effort**, not hard isolation.  
3. Intended secret path = vault/env refs only.

---

## 7.1 Configuration buckets & UI (v0)

Do **not** put platform/DB settings inside the MCP · API-creds catalog. Three buckets:

| Bucket | What | Examples | UI (v0) | Storage |
| --- | --- | --- | --- | --- |
| **1. Platform / runtime** | How the office process runs | `DATABASE_URL` (or host/port/db/user/password), `OFFICE_REPO_PATH`, `SECRET_KEY`, `PORT`, pack budget, `APPROVER_MODE` | **Read-only** settings page (admin). Edit via `.env` / compose / deploy only | Env / vault |
| **2. Stacks** | BYO model/runtime connections | Cursor / Claude / Ollama keys & base URLs | Editable on Stacks screen (later); v0 may be env-only | Env / vault refs |
| **3. Catalog** | Agent tools | MCP, Skills, API/creds + `hil` / `_locked` / cred owner | Editable catalog + agent registration | Git descriptors + vault for secret values |

**Office structure** (org/floor/team/agent/links/autonomy numbers) stays in **office git YAML**, editable from UI later (create = commit) — separate from platform secrets.

### Platform settings UI (v0) — read-only + view password

- Platform config is **not updatable from UI** in v0 (change `.env` and restart).
- Non-secret fields (host, port, database name, user, `OFFICE_REPO_PATH`, budgets) show as plain **read-only** text.
- Passwords / API-style platform secrets:
  - Default: **masked** (`••••••••`) or status **Configured** / **Not set**
  - Admin **may reveal/view** the real value (Show toggle) — accepted for v0 self-host convenience
  - Reveal only via authenticated admin + explicit reveal request (do not embed secrets on every page load)
  - Prefer HTTPS when not localhost; never log secret values
- Later (post-v0): optional UI edit + test-connection for DB; tighter “no reveal” for multi-tenant SaaS

### Minimal `.env` shape (illustrative)

```bash
DATABASE_URL=postgresql://office:office@localhost:5432/agent_anystack
# or: DATABASE_URL=sqlite:///./data/office.db

OFFICE_REPO_PATH=./office
HOST=0.0.0.0
PORT=8787
SECRET_KEY=change-me
OFFICE_API_TOKEN=change-me

CURSOR_API_KEY=
ANTHROPIC_API_KEY=
OLLAMA_BASE_URL=http://127.0.0.1:11434

PACK_TOKEN_BUDGET=8000
APPROVER_MODE=permissive
```

---

## 8. Suggested greenfield layout

```text
agent-anystack/                 # NEW public-ready repo
  LICENSE                       # Apache-2.0 on commit 1
  README.md
  .gitignore                    # .env, .venv, __pycache__, *.db, node_modules
  .env.example
  docs/                         # copy from this project’s docs/
  office/                       # sample office git tree
    org.yaml
    teams/<team>/agents/<id>/
      agent.yaml                # AGENT_DEFINITION.md
      AGENT.md                  # persona
      gold/<user>.md
  apps/
    orchestrator/               # FastAPI
    office-ui/                  # TS later
  docker-compose.yml
```

Agent definition + fixed Office Envelope: [AGENT_DEFINITION.md](./AGENT_DEFINITION.md).

**Public-repo hygiene:** no secrets in history; Conventional commits; tag `v0.1.0`; gitleaks before public/transfer ownership.

**What to copy from `cursor_teams`:** all of `docs/`, mockups, YAML ideas, command grammar.  
**What not to treat as target code:** `apps/orchestrator` Fastify — reference WS/activity shapes only.

---

## 9. Build slices (implement in order)

Canonical v0 cut: **[V0_SCOPE.md](./V0_SCOPE.md)**. Do not build floors+MCP+analytics UI+plugins first.

| # | Slice | Done when |
| --- | --- | --- |
| 1 | Load `office/` YAML — list agents API | Desks visible in JSON |
| 2 | `user_id` on every request (header stub) | Two users distinct |
| 3 | Chat → **Ollama** (or one stack) + `run_id` + journal | Live tokens |
| 4 | `gold(a,u)` read/write | Per-user notepad |
| 4b | Agent create: `agent.yaml` + `AGENT.md` + Office Envelope | Desk reversible in git |
| 5 | SQLite OKF + Pydantic + pack `C(a,p,u)` | Facts round-trip |
| 6 | Post-run extract via BackgroundTasks | Chat not blocked |
| 7 | Office chat: status + cited knowledge (thin) | No agent required |
| 8 | Approval board: one action card, permissive | Accept → journal |
| 9 | Effective autonomy §4.1 on one gate | Ceiling works |
| 10 | OKF export to `memory/` | Leave-path |
| 11 | **UI shell:** Team/Memory/Approvals + Analytics & Connect **stubs** | Direction clear |
| — | Floors, full MCP/`_locked`, Analytics deep UI, Connect plugins | **After v0** |

---

## 10. Explicit non-goals (v0)

- Celery / multiprocessing / thread-pool architecture  
- Vector DB as primary retrieval  
- Orchestrator inventing facts without memory  
- Agents writing shared OKF directly  
- Filtering shared OKF by `user_id` on pack  
- Claiming `_locked` is a hard sandbox  
- Wrapping consumer Claude OAuth as multi-tenant harness (ToS)  
- **Analytics/graph BI UI** (journal only)  
- **External plugins** (AutoCAD etc.) — stub + API sketch only  
- Pixel-perfect mockup / floor canvas / multi-stack polish  

---

## 11. Prototype vs target

| | This repo (`cursor_teams`) | Target greenfield |
| --- | --- | --- |
| Orchestrator | Fastify (TS) | **FastAPI (Python)** |
| UI | Vite office-ui | **Simple** shell — less fidelity than vision mockup |
| Memory | Gold files; design for OKF+DB | Implement hybrid |
| Hierarchy | Partial (box→team rename in docs) | One team in v0; floors later |
| Multi-user | Not fully built | `user_id` + gold(a,u) from slice 2 |

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-03 | Initial handoff: Python stack, async model, office chat, slices, public git hygiene |
| 2026-08-04 | §7.1 Config buckets; platform UI read-only v0; admin may reveal masked passwords |
| 2026-08-04 | Link AGENT_DEFINITION.md (yaml+md, Office Envelope, workspace isolation) |
| 2026-08-04 | V0_SCOPE, ANALYTICS, CONNECT; slices align; UI simpler than mockup; pillars unchanged |
