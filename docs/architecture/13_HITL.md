# HITL approval board (P13)

One **action** card path — propose → board → Accept/Reject → journal.  
Orchestrator **gates**; it does **not** execute Slack/send/etc. on Accept (agent execute / MCP grant = later).

**P14:** `external_send` propose is gated by effective autonomy — see **[14_AUTONOMY_GATE.md](./14_AUTONOMY_GATE.md)**. This file is the human board path (HITL mid-band + decide).

Product intent: [ORCHESTRATOR.md](../ORCHESTRATOR.md) §6.0 · formula index: [06_HITL.md](./06_HITL.md).

```mermaid
sequenceDiagram
    participant UI as Approvals UI
    participant API as api/approvals
    participant S as ApprovalService
    participant P as can_decide
    participant ST as ApprovalStore
    participant J as RunJournal

    UI->>API: POST /approvals (propose)
    API->>S: propose(requester from X-User-Id)
    S->>ST: upsert pending_human
    API-->>UI: ApprovalCard

    UI->>API: POST /approvals/{id}/decide
    API->>S: decide(actor, accept|reject)
    S->>P: permissive? requester ∪ ORG_ADMINS
    alt 403
        API-->>UI: forbidden
    else ok
        S->>ST: accepted | rejected
        S->>J: approval_* + approval_id
        API-->>UI: decided card
    end
```

| Step | HTTP | Result |
| --- | --- | --- |
| Propose | `POST /approvals` | `status=pending_human` in SQLite |
| List | `GET /approvals?status=pending_human` | Board |
| Decide | `POST /approvals/{id}/decide` | Card + **journal** row |
| Forbidden | same decide, wrong actor | **403** |

| Piece | Path |
| --- | --- |
| Model | `hitl/card.py` — `ApprovalCard` |
| Policy | `hitl/policy.py` — `can_decide` |
| Store | `hitl/store.py` — table `approval_cards` |
| Service | `hitl/service.py` — `ApprovalService` |
| HTTP | `api/approvals.py` |
| UI | nav **Approvals** |
| Config | `APPROVER_MODE`, `ORG_ADMINS` (community default `admin`) |

**Community:** default user + `ORG_ADMINS` = `admin`. Multi-user via `X-User-Id` still works; edition lock later. See [10_USER.md](./10_USER.md).

---

## Example flow: main → route → propose → decide → journal

**Scenario (community):** `admin` proposes a gated Slack send for desk `ba`, then Accepts. A non-admin stranger (`carol`) cannot decide.

**Scenario (multi-user demo):** `alice` proposes; `admin` (in `ORG_ADMINS`) may Accept; `bob` who is neither requester nor admin → 403 under permissive unless bob is the requester.

### Request contract

```http
POST /approvals
X-User-Id: admin
Content-Type: application/json

{
  "agent_id": "ba",
  "team": "eng",
  "action_type": "external_send",
  "summary": "Send Slack to #sales: Q3 numbers ready"
}
```

```http
GET /approvals?status=pending_human
X-User-Id: admin
```

```http
POST /approvals/appr-…/decide
X-User-Id: admin
{"decision":"accept"}
```

| Value | Source |
| --- | --- |
| `requester` | `X-User-Id` on propose → card.`user_id` |
| `actor` | `X-User-Id` on decide |
| `run_id` | Optional body; else `new_run_id()` |
| `tag` | Always `action` in P13 |
| Response | JSON `ApprovalCard` — **not** SSE |

**Permissive (`APPROVER_MODE=permissive`):**

```text
can_decide ⇔ actor == requester  OR  actor ∈ ORG_ADMINS
```

**Strict (supported in policy, not the community default):** org admin only — requester cannot Accept.

### End-to-end modules

```mermaid
flowchart TD
    UI["office-ui Approvals view"]
    MAIN["main.create_app"]
    R["api/approvals"]
    UID["api/deps.get_user_id"]
    WIRE["get_approval_service"]
    CFG["config.Settings"]
    S["hitl.ApprovalService"]
    POL["hitl.policy.can_decide"]
    ST["hitl.ApprovalStore"]
    DB["data/office.db approval_cards"]
    J["runs.RunJournal journal.jsonl"]

    UI -->|POST/GET /approvals| MAIN
    MAIN -->|include_router| R
    R --> UID
    R --> WIRE
    WIRE --> CFG
    WIRE --> S
    R -->|propose / list / decide| S
    S --> ST
    ST --> DB
    S -->|on decide| POL
    S -->|on decide| J
    R -->|JSON| UI
```

### A) Propose (pending card)

```http
POST /approvals
X-User-Id: admin
{"agent_id":"ba","team":"eng","action_type":"external_send","summary":"Send Slack to #sales"}
```

```mermaid
sequenceDiagram
    participant UI as Approvals UI
    participant Main as main.create_app
    participant R as api/approvals.propose_approval
    participant Deps as get_user_id
    participant S as ApprovalService
    participant ST as ApprovalStore
    participant DB as office.db

    Note over Main: include_router(approvals_router)
    UI->>R: POST /approvals
    R->>Deps: X-User-Id → admin
    R->>S: propose(requester=admin, agent_id=ba, …)
    Note over S: id=appr-… · status=pending_human · run_id new or body
    S->>ST: upsert(card)
    ST->>DB: INSERT approval_cards
    R-->>UI: 201 ApprovalCardOut
```

**Card shape (response):**

```json
{
  "id": "appr-…",
  "tag": "action",
  "status": "pending_human",
  "run_id": "run-…",
  "agent_id": "ba",
  "user_id": "admin",
  "team": "eng",
  "summary": "Send Slack to #sales",
  "action_type": "external_send",
  "created_at": "…",
  "decision": null,
  "decided_by": null
}
```

### B) List board

```http
GET /approvals?status=pending_human
X-User-Id: admin
```

```mermaid
sequenceDiagram
    participant UI as Approvals UI
    participant R as api/approvals.list_approvals
    participant S as ApprovalService
    participant ST as ApprovalStore

    UI->>R: GET /approvals?status=pending_human
    R->>S: list_cards(status=pending_human)
    S->>ST: SELECT … ORDER BY created_at DESC
    R-->>UI: ApprovalCard[]
```

UI: Pending filter = `status=pending_human`; All = no status query.

### C) Accept → journal

```http
POST /approvals/appr-…/decide
X-User-Id: admin
{"decision":"accept"}
```

```mermaid
sequenceDiagram
    participant UI as Approvals UI
    participant R as api/approvals.decide_approval
    participant S as ApprovalService
    participant P as can_decide
    participant ST as ApprovalStore
    participant J as journal.jsonl

    UI->>R: POST …/decide accept
    R->>S: decide(actor=admin, accept)
    S->>ST: get(id) must be pending_human
    S->>P: permissive?
    P-->>S: true (admin ∈ ORG_ADMINS / is requester)
    S->>ST: status=accepted, decided_by, decided_at
    S->>J: JournalEntry status=approval_accept
    R-->>UI: card accepted
```

**Journal row (audit — not chat history):**

```json
{
  "run_id": "run-…",
  "agent_id": "ba",
  "user_id": "admin",
  "team": "eng",
  "channel": "office_ui",
  "stack": "hitl",
  "status": "approval_accept",
  "approval_id": "appr-…",
  "decision": "accept",
  "decided_by": "admin",
  "started_at": "<card.created_at>",
  "ended_at": "<decided_at>"
}
```

Reject → `status=approval_reject`, card `status=rejected`. Optional body `note` → journal `error` field.

### D) Forbidden actor (403)

```http
POST /approvals/appr-…/decide
X-User-Id: carol
{"decision":"accept"}
```

(`carol` ∉ `ORG_ADMINS`, not requester)

```mermaid
sequenceDiagram
    participant R as decide_approval
    participant S as ApprovalService
    participant P as can_decide

    R->>S: decide(actor=carol, accept)
    S->>P: permissive?
    P-->>S: false
    S-->>R: ApprovalForbiddenError
    R-->>R: HTTP 403
```

Already decided / missing id → **404** (`ApprovalNotPendingError`).

### Inside `decide` (order)

```text
1. store.get(id)                     → must exist + pending_human
2. can_decide(actor, requester, …)   → else 403
3. set decision / decided_by / time  → status accepted|rejected
4. store.upsert(card)
5. journal.append(… approval_*)
```

### Module map for the example

| Step | Module |
| --- | --- |
| Boot | `main.create_app` → `approvals` router |
| Identity | `deps.get_user_id` (`admin` default) |
| Wire | `get_approval_service` → Settings + SQLite + journal path |
| Propose | `ApprovalService.propose` |
| Policy | `hitl.policy.can_decide` |
| Persist | `ApprovalStore` / `approval_cards` |
| Audit | `RunJournal.append` |
| UI | `apps/office-ui` Approvals → propose / Accept / Reject |

```text
+ OK: Accept writes journal; board lists pending
- BAD: orchestrator sends Slack itself on Accept

+ OK: P13 = board + decide only
- BAD: run pause, MCP `_locked` grant, memory cards, autonomy-on-gate in this slice

+ OK: community default ORG_ADMINS=admin; multi-user header still works
- BAD: remove user_id from cards/gold and re-plumb for enterprise later
```

### Explicitly not P13

| Later | Why deferred |
| --- | --- |
| Effective autonomy opens/skips card | **P14** — [14_AUTONOMY_GATE.md](./14_AUTONOMY_GATE.md) |
| Pause chat run mid-stream | Needs tool loop |
| Deliver grant → agent ACK | MCP `_locked` |
| Memory HITL cards | Async pipeline |
| Community “single user only” switch | Edition flag on top of this plumbing |

**Status:** P13 board + P14 gate + **P15 OKF export** = core slices done.  
**Optional:** shelf ∩ P(p), OKF import.
