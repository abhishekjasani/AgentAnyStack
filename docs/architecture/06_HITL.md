# HITL + autonomy (P13 board)

Controllability knob — same meaning for every stack. **P13:** one **action** card path + permissive decide → journal. Autonomy-on-gate = next slice.

```mermaid
flowchart LR
    ORG[org.max_autonomy]
    AG[agent.max optional]
    USR[user.override]
    EFF[effective 0 to 100]
    GATE[Allow or HITL card]
    ORG --> EFF
    AG --> EFF
    USR --> EFF
    EFF --> GATE
```

## Formula

```text
effective_max = min(org.max_autonomy, agent.max ?? 100)
effective = clamp(user.override ?? agent.default ?? org.default, 0, effective_max)
```

```text
+ OK: org max 70; agent max 80 → rejected at create (AutonomyCeilingError)
- BAD: agent silently runs above org ceiling

+ OK: user may tighten autonomy for themselves
- BAD: user self-promotes above effective_max

+ OK: one approval card path; permissive approvers in v0
- BAD: silent drop of gated actions
```

---

## Example flow: propose → board → Accept → journal

**Scenario:** Alice proposes a demo gated action for desk `ba`. Bob is not admin and not requester → 403. Alice Accepts → card `accepted` + journal row.

### Request contract

```http
POST /approvals
X-User-Id: alice
{"agent_id":"ba","team":"eng","action_type":"external_send","summary":"Send Slack to #sales"}
```

```http
POST /approvals/{id}/decide
X-User-Id: alice
{"decision":"accept"}
```

| Value | Source |
| --- | --- |
| requester | `X-User-Id` on propose |
| actor | `X-User-Id` on decide |
| Permissive | actor == requester **or** actor ∈ `ORG_ADMINS` |
| Strict (later) | org admin only |
| Community default | `ORG_ADMINS=admin` (sole seat; multi-user lock switch later) |

### End-to-end modules

```mermaid
flowchart TD
    UI["office-ui Approvals"]
    MAIN["main.create_app"]
    R["api/approvals"]
    SVC["hitl.ApprovalService"]
    POL["hitl.policy.can_decide"]
    ST["hitl.ApprovalStore"]
    J["runs.RunJournal"]
    DB["data/office.db"]

    UI -->|POST /approvals| MAIN
    MAIN --> R
    R --> SVC
    SVC --> ST
    ST --> DB
    UI -->|POST .../decide| R
    R --> SVC
    SVC --> POL
    SVC -->|append| J
```

### A) Propose

```mermaid
sequenceDiagram
    participant UI as Approvals UI
    participant R as api/approvals.propose
    participant S as ApprovalService
    participant ST as ApprovalStore

    UI->>R: POST /approvals + X-User-Id
    R->>S: propose(requester=alice, …)
    S->>ST: upsert pending_human
    R-->>UI: ApprovalCard {id, status=pending_human}
```

### B) Accept → journal

```mermaid
sequenceDiagram
    participant UI as Approvals UI
    participant R as api/approvals.decide
    participant S as ApprovalService
    participant P as can_decide
    participant ST as ApprovalStore
    participant J as journal.jsonl

    UI->>R: POST /approvals/id/decide accept
    R->>S: decide(actor, accept)
    S->>P: permissive?
    alt forbidden
        R-->>UI: 403
    else ok
        S->>ST: status=accepted
        S->>J: status=approval_accept + approval_id
        R-->>UI: card accepted
    end
```

### Module map

| Step | Module |
| --- | --- |
| Boot | `main` registers `approvals` router |
| HTTP | `api/approvals.py` |
| Policy | `hitl/policy.can_decide` |
| Store | `hitl/store.ApprovalStore` (SQLite `approval_cards`) |
| Service | `hitl/service.ApprovalService` |
| Audit | `runs/journal` — `approval_id`, `decision`, `decided_by` |

```text
+ OK: Accept writes journal; board lists pending
- BAD: auto-execute Slack/send from orchestrator on Accept (agent executes later)

+ OK: P13 = board + decide; no run pause / MCP grant yet
- BAD: build full dual HITL + `_locked` matrix in this slice
```

**Status (P13):** one action card + Approvals UI + permissive decide → journal = done.  
**Next:** effective autonomy on one gate (slice 9). Ceiling already checked on agent create.
