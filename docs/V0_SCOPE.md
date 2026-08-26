# v0 scope — core + clear product shell

**Goal:** Prove the office idea without rushing features. **Base** = working core **and** a simple UI shell so direction is obvious (stubs OK for later tabs).

**Related:** [IMPLEMENTATION.md](./IMPLEMENTATION.md) · [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) · [ANALYTICS.md](./ANALYTICS.md) · [CONNECT.md](./CONNECT.md) · [AGENT_DEFINITION.md](./AGENT_DEFINITION.md)

---

## Pillars — unchanged

Still four pillars (no fifth required for analytics/connect):

| Pillar | v0 shows it how |
| --- | --- |
| **1. Agent office** | Team desks + chat; Connect tab stub (channels later) |
| **2. Controllability** | One HITL path; Approvals nav |
| **3. Memory** | Gold + team OKF pack/extract; Memory nav (list first) |
| **4. No vendor lock-in** | Office git + SQLite/OKF export path; local Ollama BYO |

**Headline features** (not pillars): any-stack · office chat · **channels/connect** · **analytics/trust**.

Analytics and external connect **attach under** existing pillars — see [ANALYTICS.md](./ANALYTICS.md) · [CONNECT.md](./CONNECT.md).

---

## What “base / v0” means

| | Meaning |
| --- | --- |
| **Working core** | Deep enough to use: team, agents, chat, gold, OKF, thin office Q&A, one approval |
| **Visible shell** | Nav for Memory, Approvals, Analytics, Connect, Settings — even if some are stubs |
| **Not v0** | Fancy BI, AutoCAD plugin, floors UI, full MCP matrix, multi-stack polish |

A new visitor should understand: *workplace for agents, memory, control, later insights and in-tool access.*

---

## In v0 (build)

| Area | Scope |
| --- | --- |
| Runtime | Python FastAPI, async, SQLite OKF, `office/` git tree |
| Structure | Org + **one team** + 1–2 agents (`agent.yaml` + `AGENT.md`) |
| Users | `user_id` stub; gold(a,u); same agent, two users |
| Chat | Agent chat + stream + `run_id`; Office Envelope inject |
| Stack | **One** adapter — prefer **Ollama** |
| Memory | Pack `C(a,p,u)`; background extract; no agent direct OKF write |
| Office chat | Thin status / cited knowledge |
| HITL | One card path, permissive approvers |
| Journal | Log `run_id`, `agent_id`, `user_id`, channel=`office_ui` (feeds future analytics) |
| Config | `.env`; platform settings read-only + admin reveal (when UI exists) |

### UI (v0) — simpler than the mockup

**Mockup** (`docs/mockups/`) = compass / vision (org, floor, rich desks).  
**v0 app UI** = simpler functional shell:

```text
Sidebar
  ├── Team (desks + chat)     ← works
  ├── Memory (fact list)      ← works thin
  ├── Approvals               ← one path works
  ├── Analytics               ← stub page (“coming” / empty columns OK)
  ├── Connect                 ← stub (“channels API coming” + one-line vision)
  └── Settings                ← platform read-only when ready
```

- Do **not** pixel-build floor canvas, glow, or full stacks polish in v0.
- Copy **IA** (nav ideas) from mockup; skip visual fanciness.
- HTMX or minimal Vite is fine.

---

## Explicitly not v0

- Analytics graph UI / cost BI (instrument journal only)
- External plugins (AutoCAD, web widget) — API sketched in [CONNECT.md](./CONNECT.md); no plugin build
- Floors / connect lines between teams
- Full MCP catalog + `_locked` matrix
- Postgres, Celery, multi-stack
- SSO, CEO dashboards

---

## Build order (core)

```text
1. office/ YAML → list agents API
2. user_id + chat → Ollama + run_id + Envelope
3. gold(a,u)
4. agent.yaml + AGENT.md
5. SQLite OKF + pack + background extract
6. Thin office Q&A
7. One HITL card
8. Shell nav stubs (Analytics, Connect)
```

**Done when:** two users, one team, one local agent, memory round-trip, chat works, nav shows product direction.

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-04 | v0 = working core + shell stubs; pillars unchanged; UI simpler than mockup |
