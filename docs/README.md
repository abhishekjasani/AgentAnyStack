# Docs index — AgentAnyStack

Start here if you are a **coding agent** or new contributor building the product.

## Read first

1. **[V0_SCOPE.md](./V0_SCOPE.md)** — **what to build now** (core + shell stubs; UI vs mockup; pillars unchanged)  
2. **[README_V0.md](./README_V0.md)** — **public v0 README** (full feature list + status) — copy to AgentAnyStack root as `README.md` when publishing  
3. **[IMPLEMENTATION.md](./IMPLEMENTATION.md)** — Python/FastAPI stack, async, config buckets, slices  
3. **[PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md)** — pillars, hierarchy, office-as-git  
4. **[ORCHESTRATOR.md](./ORCHESTRATOR.md)** — HITL, autonomy, Guardrails catalog, office Q&A, `OFFICE_MODEL`  
5. **[MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md)** — gold(a,u), recent_thread, OKF/DB, packing   
6. **[AGENT_DEFINITION.md](./AGENT_DEFINITION.md)** — `agent.yaml` + `AGENT.md`, Office Envelope  
7. **[STACK_ADAPTERS.md](./STACK_ADAPTERS.md)** — Inference / Harness / External; Stacks tab UX; OpenCode-first  
8. **[IDE_FIRST.md](./IDE_FIRST.md)** — human seats; BYO IDE; pack + WorkPacket; MEMORY HITL only  

## Direction (stub in v0, design now)

| Doc | Role |
| --- | --- |
| [ANALYTICS.md](./ANALYTICS.md) | Trust tab: runs, API/MCP, graph, HITL stats — journal first |
| [CONNECT.md](./CONNECT.md) | External plugins (AutoCAD, web, …) → orchestrator — API-first |
| [IDE_FIRST.md](./IDE_FIRST.md) | Human seats; pack/WorkPacket sync; hooks ≫ transcript |
| [STACK_ADAPTERS.md](./STACK_ADAPTERS.md) | Few runtime kinds; desks hero; Stacks UX; compose via catalog |

## Also useful

| Doc | Role |
| --- | --- |
| [USE_CASES_MEMORY.md](./USE_CASES_MEMORY.md) | Stories + speaker notes |
| [LOCAL_MODEL_STACK.md](./LOCAL_MODEL_STACK.md) | Ollama / local models |
| [OPEN_SOURCE_MARKET_RESEARCH.md](./OPEN_SOURCE_MARKET_RESEARCH.md) | CE/EE, naming |

## Legacy prototype (this repo’s TS code)

| Doc | Role |
| --- | --- |
| [COMMANDS.md](./COMMANDS.md) | Chat grammar |
| [WORKER.md](./WORKER.md) | Cursor workers |
| [DOCKER.md](./DOCKER.md) | Fastify/Vite Docker |

## Mockups

[`mockups/`](./mockups/) — **vision compass** (richer than v0). Build a **simpler** functional UI per V0_SCOPE.
