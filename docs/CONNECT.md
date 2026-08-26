# External connect — channels into the office

SMEs are not always in the Agent Office UI. They work in AutoCAD, IDEs, websites, Slack, etc. **Connect** = those products talk to the **same orchestrator → same agents, memory, HITL**.

**Related:** [V0_SCOPE.md](./V0_SCOPE.md) · [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) · [ORCHESTRATOR.md](./ORCHESTRATOR.md) · [ANALYTICS.md](./ANALYTICS.md) · [AGENT_DEFINITION.md](./AGENT_DEFINITION.md) · [IDE_FIRST.md](./IDE_FIRST.md) · [STACK_ADAPTERS.md](./STACK_ADAPTERS.md)

**Pillar fit:** Agent office + any-stack / any-channel (not a fifth pillar). Domain × channel × risk already describes seating.

---

## Correct mental model

Plugins run **inside the external product**, not inside Agent Office.

```text
┌──────────────────────────┐
│ AutoCAD (desktop)        │
│  └─ plugin (CAD engineers│
│      build & run here)   │
│         HTTPS/WS         │
└────────────┬─────────────┘
             ▼
      Orchestrator (AgentAnyStack)
             ▼
      Target agent desk (e.g. cad-designer)
      pack C(a,p,u) · HITL · tools · gold(a,u)
```

Same for: company website support widget → `support-resolver`; **human IDE seats → pack + WorkPacket sync** ([IDE_FIRST.md](./IDE_FIRST.md)); Slack → routed desk.

- Office does **not** embed AutoCAD or run CAD logic in the Python event loop.
- Plugin sends text / exports / commands; agent replies; plugin applies results in AutoCAD.

---

## Requirements for “seamless”

1. Auth maps plugin user → office `user_id` (SSO later).
2. Route by channel + intent → `agent_id` (config).
3. Same gold / pack / HITL as UI chat.
4. No memory FS backdoor — plugin only calls orchestrator API.
5. Stamp `channel` on every run (feeds Analytics).

---

## API-first (before any plugin)

Sketch (illustrative):

```http
POST /v1/runs
Authorization: …
{
  "channel": "autocad" | "web_support" | "slack" | "office_ui" | ...,
  "agent_id": "cad-designer",
  "user_id": "…",
  "message": "…",
  "attachments": []
}
```

→ creates `run_id`, packs context, streams or returns agent output.  
**Partner plugins** (AutoCAD, etc.) are thin clients against this API.

**Human IDE seats** (memory-only — [IDE_FIRST.md](./IDE_FIRST.md)):

```http
POST /v1/pack
{ "seat_id", "user_id", "project_id", "pack_depth": "team" | "full" }

POST /v1/seats/{seat_id}/sync
{ "user_id", "project_id", "channel", "message", "remember", "artifacts": [...] }
```

→ fan-out pack; fan-in WorkPacket → same OKF extract + MEMORY HITL (no ACTION HITL). Prefer **git/CI/stack hooks** as producers — not scraping local agent transcripts.

---

## Phasing

| Phase | What |
| --- | --- |
| **v0** | Connect **nav stub** + journal `channel=office_ui`; no plugins |
| **Design** | Stabilize Connect/runs API |
| **v1** | One reference channel (e.g. web widget, Slack, or **IDE pack sidecar** — [IDE_FIRST.md](./IDE_FIRST.md)) |
| **Partner** | AutoCAD (or other) plugin by domain engineers |
| **Later** | Channel catalog / signed webhooks; more IDE clients |

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-04 | Initial: in-product plugins → orchestrator; API-first; v0 stub only |
| 2026-08-11 | Link IDE_FIRST (pack/extract for IDE-loyal eng) |
| 2026-08-12 | Human seat sync API; WorkPacket; hooks ≫ transcript |
