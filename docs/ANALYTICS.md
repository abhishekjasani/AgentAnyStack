# Analytics & trust surface

Run history is available today. The broader analytics modules below describe the roadmap.

**Related:** [V0_SCOPE.md](./V0_SCOPE.md) · [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) · [ORCHESTRATOR.md](./ORCHESTRATOR.md) · [CONNECT.md](./CONNECT.md)

**Pillar fit:** Controllability + office transparency (not a fifth pillar).

---

## Purpose

Buyers and operators need proof: who ran what, with what knowledge, which APIs/MCP fired, what HITL decided. Approvals = ops inbox; **Analytics = trust / compliance / debug surface**.

---

## Modules (roadmap)

| Module | Shows | Phase |
| --- | --- | --- |
| **Run explorer** | Timeline by `run_id`: user, agent, team, project, pack summary, tools, HITL, outcome | First real analytics |
| **API / MCP usage** | Catalog id, agent, user, run_id, hil outcome, status, latency | With capability journal |
| **External channel usage** | channel × agent (AutoCAD, web, Slack, …) | With [CONNECT.md](./CONNECT.md) |
| **HITL stats** | Pending age, approve/reject, timeouts, who approved | After board exists |
| **OKF knowledge graph** | Facts as nodes; links as edges; ACL by readable scopes | After memory stable |
| **Memory health** | Counts by scope, prune candidates, gold sizes | Later |
| **Autonomy / risk** | Effective autonomy distribution, hard-floor hits, `_locked` unlocks | Later |
| **Cost / tokens** | By stack/agent/project | Later |
| **Connect-line traffic** | Cross-team shares approved | When floors exist |

### Minimum API/usage row

`timestamp · run_id · user_id · agent_id · team_id · project_id · catalog_id · method · hil_outcome · status · latency · channel`

### Knowledge graph notes

- UI explore (filter, 1–2 hop) ≠ packing the whole graph into agents.
- Same ACL as memory packing.
- Click node → body + provenance (`created_by_user`, run, project).
- Optional Postgres `fact_links` index — **not** a graph DB for v1.

---

## Available now

The **Run history** screen shows active runs plus up to 100 recent journal entries for the current user. It includes agent, team/project, model/connection, status, and start time. Inspect a run to view its metadata and recorded thinking when available. Approval decision audit rows are excluded.

The **Office floor** also shows live agent presence, pending approvals, and recent outcomes. Both surfaces use `GET /office/activity`; see [Office UI architecture](architecture/09_UI.md) for polling and presence lifecycle details.

Cost/token accounting, API/MCP usage aggregates, knowledge graphs, and cross-team communication visualizations remain planned. A shared project table on the floor represents assignments, not measured agent-to-agent traffic.

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-04 | Initial roadmap; v0 = journal + stub UI |
| 2026-09-05 | Office presence, run history, and run inspection available |
