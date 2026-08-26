# Analytics & trust surface

Comprehensive analytical tab — **direction**, not a v0 build commitment.

**Related:** [V0_SCOPE.md](./V0_SCOPE.md) · [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) · [ORCHESTRATOR.md](./ORCHESTRATOR.md) · [CONNECT.md](./CONNECT.md)

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

## v0 rule

- **UI:** Analytics nav **stub** only (“coming” / empty table headers OK).
- **Must:** structured **journal events** on every run (`run_id`, `agent_id`, `user_id`, `channel`) so the tab can light up later without re-instrumenting.

No fancy BI in v0.

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-04 | Initial roadmap; v0 = journal + stub UI |
