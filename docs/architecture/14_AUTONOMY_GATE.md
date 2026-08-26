# Autonomy gate (P14)

Effective autonomy (§4.1) drives **one gate** on `POST /approvals` for `action_type=external_send`.

| effective | Gate | Result |
| --- | --- | --- |
| ≤20 | **deny** | Card `denied` + journal `approval_deny` + HTTP **403** |
| 21–79 | **hitl** | Card `pending_human` → human board ([13_HITL.md](./13_HITL.md)) |
| ≥80 | **allow** | Card `accepted`, `decided_by=gate` + journal `approval_accept` |

Other action types → always **hitl** (no band). Orchestrator still does **not** send Slack itself on allow.

Formula + ceiling: [06_HITL.md](./06_HITL.md) · Product: [ORCHESTRATOR.md](../ORCHESTRATOR.md) §4.1.

```mermaid
flowchart LR
    ORG[org.max_autonomy]
    AG[agent.max / default]
    USR[autonomy_override]
    EFF[compute_effective]
    GATE[gate_action]
    ORG --> EFF
    AG --> EFF
    USR --> EFF
    EFF --> GATE
    GATE -->|≤20| D[deny]
    GATE -->|21–79| H[hitl]
    GATE -->|≥80| A[allow]
```

| Piece | Path |
| --- | --- |
| Formula + gate | `hitl/autonomy.py` |
| Wire | `hitl/service.ApprovalService.propose` |
| HTTP | `api/approvals.propose_approval` |
| Chat reuse | `runs/service` → `compute_effective` for Envelope |
| UI | Approvals · optional override field |

---

## Example flow: main → route → effective → gate → outcome

**Scenario:** Desk `ba` exists (`autonomy.default: 50`, max 100). Org `max_autonomy: 100`. User `admin`.

| Call | `autonomy_override` | effective | Outcome |
| --- | --- | --- | --- |
| `external_send` | — | 50 | hitl |
| `external_send` | `15` | 15 | deny |
| `external_send` | `90` | 90 | allow |
| `external_send` | `200` (invalid body) | — | 422 validation |
| `external_send` | `99` with agent max 70 | 70 | hitl (clamped) |
| `demo` | `90` | 90 | hitl (not gated type) |

### Request contract

```http
POST /approvals
X-User-Id: admin
Content-Type: application/json

{
  "agent_id": "ba",
  "team": "eng",
  "action_type": "external_send",
  "summary": "Send Slack to #sales: Q3 numbers ready",
  "autonomy_override": 90
}
```

| Value | Source |
| --- | --- |
| `agent_id` | Body — must exist (404 else) |
| `action_type` | Body — only `external_send` is banded |
| `autonomy_override` | Optional 0–100; clamped to `effective_max` |
| `requester` | `X-User-Id` |
| Response | `201` + card (`gate`, `effective_autonomy`) **or** `403` deny detail |

### End-to-end modules

```mermaid
flowchart TD
    UI["office-ui Approvals"]
    MAIN["main.create_app"]
    R["api/approvals.propose_approval"]
    UID["deps.get_user_id"]
    S["ApprovalService.propose"]
    REPO["OfficeRepository"]
    EFF["compute_effective"]
    G["gate_action"]
    ST["ApprovalStore"]
    J["RunJournal"]

    UI -->|POST /approvals| MAIN
    MAIN --> R
    R --> UID
    R --> S
    S --> REPO
    S --> EFF
    S --> G
    G -->|deny / allow / hitl| ST
    G -->|deny / allow| J
    R -->|201 or 403| UI
```

### Inside `propose` (order)

```text
1. repo.get_agent(agent_id)     → 404 if missing
2. repo.load_org()
3. compute_effective(org, agent, user_override=…)
4. gate_action(action_type, effective)
5a. deny  → upsert denied + journal approval_deny → raise → HTTP 403
5b. allow → upsert accepted (decided_by=gate) + journal approval_accept → 201
5c. hitl  → upsert pending_human → 201 (no journal until human decide)
```

### A) HITL band (default desk = 50)

```http
POST /approvals
X-User-Id: admin
{"agent_id":"ba","action_type":"external_send","summary":"Send Slack","team":"eng"}
```

```mermaid
sequenceDiagram
    participant UI as Approvals UI
    participant R as propose_approval
    participant S as ApprovalService
    participant Eff as compute_effective
    participant G as gate_action
    participant ST as ApprovalStore

    UI->>R: POST /approvals
    R->>S: propose(…)
    S->>Eff: override=None → 50
    S->>G: external_send, 50 → hitl
    S->>ST: status=pending_human, gate=hitl, effective_autonomy=50
    R-->>UI: 201 {gate: hitl, status: pending_human}
    Note over UI: Accept/Reject — see 13_HITL
```

### B) Allow band (override ≥ 80)

```http
POST /approvals
X-User-Id: admin
{"agent_id":"ba","action_type":"external_send","summary":"Send Slack","autonomy_override":90}
```

```mermaid
sequenceDiagram
    participant R as propose_approval
    participant S as ApprovalService
    participant G as gate_action
    participant ST as ApprovalStore
    participant J as journal.jsonl

    R->>S: propose(…, user_override=90)
    S->>G: → allow
    S->>ST: status=accepted, decided_by=gate
    S->>J: status=approval_accept, effective_autonomy=90
    R-->>UI: 201 {gate: allow, status: accepted}
```

**Journal snippet:**

```json
{
  "status": "approval_accept",
  "approval_id": "appr-…",
  "decision": "accept",
  "decided_by": "gate",
  "effective_autonomy": 90,
  "stack": "hitl"
}
```

### C) Deny band (override ≤ 20)

```http
POST /approvals
X-User-Id: admin
{"agent_id":"ba","action_type":"external_send","summary":"Send Slack","autonomy_override":15}
```

```mermaid
sequenceDiagram
    participant R as propose_approval
    participant S as ApprovalService
    participant G as gate_action
    participant ST as ApprovalStore
    participant J as journal.jsonl

    R->>S: propose(…, user_override=15)
    S->>G: → deny
    S->>ST: status=denied, decided_by=gate
    S->>J: status=approval_deny
    S-->>R: ApprovalGateDeniedError
    R-->>UI: 403 {message, gate: deny, effective_autonomy: 15}
```

### D) Formula detail (same as chat)

```text
effective_max = min(org.max_autonomy, agent.autonomy.max ?? 100)
raw           = autonomy_override ?? agent.autonomy.default ?? org.autonomy.default
effective     = clamp(raw, 0, effective_max)
```

```mermaid
sequenceDiagram
    participant Chat as ChatRunService
    participant Eff as compute_effective
    participant Env as Envelope

    Note over Chat,Env: Same function — one formula everywhere
    Chat->>Eff: org + agent (no override in chat yet)
    Eff-->>Chat: effective
    Chat->>Env: Effective autonomy for this run: N/100
```

### Module map

| Step | Module |
| --- | --- |
| Boot | `main` → `approvals` router |
| HTTP | `api/approvals.py` |
| Service | `hitl/service.ApprovalService.propose` |
| Formula | `hitl/autonomy.compute_effective` |
| Gate | `hitl/autonomy.gate_action` (`GATED_ACTION_TYPE`) |
| Desk/org | `office.OfficeRepository` |
| Persist | `hitl/store` — `gate`, `effective_autonomy` columns |
| Audit | `runs/journal` |
| Human path | [13_HITL.md](./13_HITL.md) when `gate=hitl` |

```text
+ OK: external_send bands on effective; journal stamps effective_autonomy
- BAD: orchestrator executes Slack on allow

+ OK: non-external_send → always HITL board
- BAD: full catalog hil / MCP matrix in this slice

+ OK: override clamped to effective_max (no self-promote)
- BAD: free raise above org/agent ceiling
```

### Explicitly not P14

| Later | Why |
| --- | --- |
| Hard floor: never auto `external_send` even at 100 | Product intent; P14 allows ≥80 to **prove the knob** |
| Pause chat mid-run when gate=hitl | Needs tool loop |
| MCP `_locked` grant after allow | Later |
| Memory HITL bands | Later |
| User override on chat Envelope | Optional; chat uses agent default today |

**Status (P14):** one gate on propose = done.  
**Core v0:** also [15_OKF_EXPORT.md](./15_OKF_EXPORT.md). Optional: shelf / import.
