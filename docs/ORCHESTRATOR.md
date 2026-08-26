# Orchestrator — Control Plane

The orchestrator is **not an LLM persona**. It is the bridge: routes messages, packs context, runs write/action gates, triggers humans, and keeps operational books. Almost everything is **deterministic algorithm**; one fenced LLM step (the memory extractor) is the exception.

**Status:** design (agreed through 2026-08-14; not fully built)
**Target runtime:** **Python / FastAPI** (async) — see [IMPLEMENTATION.md](./IMPLEMENTATION.md) · [V0_SCOPE.md](./V0_SCOPE.md). This repo’s Fastify app is a behavior reference only.
**Related:** [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) · [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) · [IMPLEMENTATION.md](./IMPLEMENTATION.md) · [CONNECT.md](./CONNECT.md) · [ANALYTICS.md](./ANALYTICS.md)

---

## 1. Product pillars (what the orchestrator exists to serve)

```mermaid
flowchart LR
    P1[1. Agent office\nworkplace for agents]
    P2[2. Controllability\neffective autonomy 0–100]
    P3[3. Org / project memory\nscoped knowledge base]
    P4[4. No vendor lock-in\ngit + OKF export + any stack]
    P1 --- ORC[Orchestrator\nsingle choke point]
    P2 --- ORC
    P3 --- ORC
    P4 --- ORC
```

| Pillar | Meaning |
| --- | --- |
| **Agent office** | Desks, teams, floors, visible activity — multi-user concurrent desks |
| **Controllability** | Effective autonomy (§4.1) — ceiling + tighten-only user override |
| **Memory** | Hierarchy × projects + connect lines; gold per user; shared OKF in DB |
| **No vendor lock-in** | Config/gold in git; OKF export; BYO stacks |

Competitors sell agents. We sell **an office with a volume knob on autonomy, a real knowledge hierarchy, and portable env**. Every message, memory write, and side effect passes through the orchestrator — so the knobs mean the same thing for a coding agent and a Slack/sales agent.

---

## 2. Responsibilities

### 2.1 Message routing (the bridge)

- Parse role grammar (`Analyst:`, `remember:`, `reset`) and dispatch
- Route between agents/teams; manage **floor connect lines** (suggest / approve gated cross-team share)
- Stream run events back to the UI

### 2.2 Context packing (memory read)

- Compute `C(a, p, u)` — **recent_thread(u)** (~7 days or last N turns, char-capped; optional pack-time summary) + **gold(a,u)** + whole **team** OKF + project-filtered floor / link-share / org  
  See [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) formulas
- `recent_thread` is labeled **Recent thread** / **Recent thread summary** — **not** gold, **not** OKF
- Prefer user messages; light trim of assistant turns; hard budget so thread does not crowd memory
- Derive `run.project` from the agent's workspace / grant (registry lookup)
- Multiple users may run the **same agent** concurrently — separate packs per `user_id` (thread + gold are per user)
- Log what was packed (transparency)

### 2.3 Memory write pipeline

- Collect report + artifacts → extractor (**office model**, not `agent.model`) → schema validate → stamp (`created_by_user`) → upsert → trust ladder → **DB** (+ optional OKF export)
- See [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md)

### 2.3.1 Office model (soft orchestrator jobs)

Orchestrator remains a **deterministic spine** (route, pack filters, HITL, journal). Soft LLM jobs use a configurable **office model**, not the desk persona model:

| Job | Model |
| --- | --- |
| Desk chat / agent run | `agent.yaml` → stack + `model` |
| OKF soft extract | **`OFFICE_MODEL`** (office / `office_qa_model`) |
| Office Q&A phrasing | **`OFFICE_MODEL`** |
| Optional recent-thread summarize at pack | **`OFFICE_MODEL`** |
| HITL approve/reject | **Deterministic** — no LLM approver (v0) |

Config example: `OFFICE_MODEL` / extend `office_qa_model` in env or org settings.

### 2.4 Capabilities (Guardrails catalog)

- Org **catalog** (admin **Guardrails** tab): **MCP · Tools · Skills · External tools**
- **Approvals** = HITL inbox; **Guardrails** = what may exist / `hil` / registration — not the same screen
- **Agent-level registration only** (no team/floor ACL matrix in v1). Built-in **Tools** (`gold.read` / `gold.update`) **default-inherit agent desks**
- Direct vs **HIL-gated `_locked` wrappers**; grants after Accept; agent executes MCP / External tool under `run_id` (+ `user_id`)
- **v1 grant path is not hard isolation** — see §10 Security TODOs
- See §7

### 2.5 Action pipeline (side effects)

- Agent proposes Slack send / call / CRM write / git push / deploy / gated capability
- Catalog `hil` + **effective autonomy** (§4.1) + timer → allow / HITL card / deny
- After approve: deliver to **agent** to execute (ACK); journal

### 2.6 Human-in-the-loop

- Durable review queue for **memory** and **actions** / gated MCP
- Approve / edit / reject; never silent drop — **who may Approve** in §6.0.2
- Batched UI — avoid interrupt-fatigue

### 2.7 Multi-user concurrency

- Every API/WS message carries `user_id` (+ org membership / RBAC later)
- Same agent desk → **separate `run_id`s** (isolate pack, cancel/stop, MCP grant, activity)
- Gold: `agents/<id>/gold/<user_id>.md` — users share the room, not the notepad
- Desk UI: presence of colleagues; filter mine vs team runs

### 2.8 Operational state (not business knowledge)

- Write journal, quarantine, review queue, tag dictionary, extraction stats, derived index
- Capability catalog + bindings (secret refs) + per-agent registrations + short-TTL grants
- No orchestrator `gold.md`; orchestrator does **not** invent business facts

### 2.9 Office chat (status + knowledge — no agent)

Users may talk to the **office** without targeting an agent (`Office:` or default when no `Analyst:` / role prefix).

| Ask | Behavior |
| --- | --- |
| **Status** | Deterministic read of runs / activity / registry (“who is running what”) |
| **Knowledge** | Filter OKF (scope · project · tags/FTS) → optional vector **rank inside candidates** → **top-K only** → `OFFICE_MODEL` phrases; **every claim cites** `fact_id` / `run_id` |
| **Empty** | Say nothing found — **never hallucinate** fill |
| **Do work** | If user asks for side effects / build — route to an **agent**, don’t fake it in office chat |

**Knowledge path (detail):** do **not** dump all filtered facts into the model. Budget top-K (e.g. 5–15). Embeddings live in a separate rebuildable **`fact_embeddings`** table and only reorder prefiltered rows — never global semantic search as ACL. Full rules: [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) §4 (Office Q&A retrieval + Fact embeddings).

**Not extraction:** office Q&A is a **read path**. Writing OKF still goes through the agent report pipeline / explicit `remember:` only.

**Latency:** status/knowledge retrieval stays on the request path (budgeted). Soft phrasing uses **`OFFICE_MODEL`**. Full memory **extract/upsert** (and embed-on-upsert) stays **async** (also **`OFFICE_MODEL`** / embed model) — never block chat on long extract or re-embed.

### Explicit non-responsibilities

- No free-roaming LLM persona that invents business facts
- Never invents business facts from its own judgment
- Never autonomously curates/prunes the knowledge base without policy
- Never lets an agent self-register new MCP/API mid-run
- Does not put the **global** catalog into agent context — only that agent's registered subset (scoped injection)
- Does not use the **desk agent model** for extract / office Q&A / thread summarize — those use **office model**
- **v0:** no Celery; no thread-pool / multiprocessing architecture — see [IMPLEMENTATION.md](./IMPLEMENTATION.md)
- **v0:** no LLM-based HITL approver — approvals stay deterministic
- Does not rebuild Cursor/Claude Code/OpenCode tool harnesses — coding desks use **worker stacks** ([STACK_ADAPTERS.md](./STACK_ADAPTERS.md))

---

## 2.10 Desk UX knobs (configure on desk — not chat chrome)

| Knob | Default location | Runtime |
| --- | --- | --- |
| Worker **mode** (`agent` / `plan` where SDK supports) | `agent.yaml` / desk settings | Adapter maps to stack; rare per-send override |
| **Pack depth** (cut OKF: gold only / gold+team / full) | Desk Memory settings; pill on card | Packer respects override for that desk/run |
| **Stack hooks** / sandbox | Adapter + policy files | Blocks → **Approval board** (same as MCP HITL) |
| **Office policy** (e.g. require Jira ticket) | Desk policy + catalog API | Orchestrator gate — portable across stacks |

Do **not** put modes + pack cutters + hook toggles + approvals on the Team chat composer. See [STACK_ADAPTERS.md](./STACK_ADAPTERS.md) §5–6.

**Human seats:** no autonomy / ACTION HITL; MEMORY promotion only — [IDE_FIRST.md](./IDE_FIRST.md).

### Stack hooks vs office policy

- **Stack hooks** = tool safety for that runtime (e.g. Cursor `.cursor/hooks.json`) — native fs/shell/git/browser.  
- **Office / Connect hooks (human seats)** = git/CI/stop events that build a **WorkPacket** for OKF sync (portable across IDE/cloud/CLI) — not scraping agent transcripts.  
- **Office policy** = business rules (Jira-gated development, deploy windows) enforced by the **orchestrator** so Bedrock/Claude Code/OpenCode desks share the same rule.  
- **Catalog `_locked`** = HITL for **office MCP/API** only. Inference: 100%. Harness: only if no native twin (§7.3).

---

## 3. Deterministic vs soft

| Layer | Deterministic? |
| --- | --- |
| Routing, packing *selection*, project stamp, schema validate, upsert, archive, catalog `hil` + timer, registration list, HITL cards / grants | **Yes** — pure algo |
| Memory **extractor** (report → candidate facts) | **No** — office-model LLM; fenced by schema + citations + quarantine |
| Optional **recent-thread summarize** at pack | **No** — office-model LLM; output ephemeral in prompt only |
| Office Q&A phrasing | **No** — office-model LLM; claims must cite retrieved ids |
| Agent mid-run use of **direct** (non-HIL) MCP inside Cursor/Claude | **Not intercepted every call** — scoped by registration + injection only |
| Prompt text (“please ask before send”) | **Soft** — not enforcement |
| Agent reasoning (desk model) | **No** — outside orchestrator spine |

Honest framing: registration **scopes** what the agent may have; HITL is deterministic on the **approval / `_locked` unlock** path — not on every MCP round-trip unless proxied. Criticality **only** in the system prompt is not a guarantee. **Inference desks:** `_locked` is complete (office owns the tool list). **Harness desks:** `_locked` is complete **only for catalog-only capabilities** (no native twin, no leaked creds) — see §7.3.

---

## 4. Controllability knob (0–100)

One operator-facing slider. Internally it selects a **policy bundle** — not a prompt vibe.

```mermaid
flowchart TB
    K[Effective autonomy 0–100] --> G[Gates\nwhat may land / fire without human]
    K --> S[Sampling\nonly on orchestrator-owned model calls]
    K --> F[Hard floors\nnever disabled even at 100]
```

### 4.1 Effective autonomy (ceiling + default + tighten-only override)

Precedence — define **once**, use for memory HITL, action HITL, and MCP `follow_autonomy`:

```text
org.default_autonomy
org.max_autonomy              // hard ceiling

agent.default_autonomy       // optional; else inherit org.default
agent.max_autonomy           // optional tighter ceiling for that desk

user.autonomy_override       // optional; may only set ≤ effective_max
                             // if unset → agent.default ?? org.default

effective_max = min(org.max_autonomy, agent.max_autonomy ?? 100)
effective     = clamp(
                  user.autonomy_override ?? agent.default_autonomy ?? org.default_autonomy,
                  0,
                  effective_max
                )
```

| Rule | Why |
| --- | --- |
| **Org/agent set the ceiling** | Controllability stays a company knob |
| **User may only go down** (or up to ceiling, never above `effective_max`) | Intern can be stricter; cannot self-promote past policy |
| **Role caps (later)** | Optional `role.max` in the `min()` (intern/contractor) |
| **One formula everywhere** | No per-pipeline drift |

**Avoid v1:** free per-user override with no max; or “strictest of all layers” with no defaults (confusing when org=40, agent=60, user unset).

### Example bands (presets over rules)

| Band | Memory | Actions (catalog / hooks) | Desk chat (soft) |
| --- | --- | --- | --- |
| **0–20** | Almost all writes → human queue | External / write systems → block or approve-only (`*_locked` / hooks) | **Ask before changes by default** — clarify unknowns in desk chat; prefer `mode: plan`; do not implement/edit/send until the human answers |
| **40–60** | Team auto; floor/link needs corroboration; org + new floor links HITL | Internal OK; external / prod / money → HITL | Ask when blocked / ambiguous / high-stakes; otherwise proceed on clear tasks |
| **80–100** | Trust ladder as designed | Allowlist grows; only irreversible / high-sensitivity remain | Proceed; still respect hard floors + gated catalog |

**Hard floors** (never graduate off, even at 100): external customer send, legal/binding text, PII/PHI exposure, money movement, prod deploy — unless an admin explicitly widens policy.

**Autonomy ↔ desk chat:** lowest band turns on “ask me first” **in the desk thread** via Office Envelope (soft). That is **not** an Approvals card — see §6.0.3. Pair with hard gates for catalog/hooks/memory.

Start strict; **auto-approve allowlist** grows from repeated human approvals (same action type + low risk). Timeout policy required for pending approvals (expire / escalate / fail-safe **reject** for external sends).

Bands apply to **`effective`** autonomy after §4.1.

---

## 5. Sampling policy (orchestrator-owned, never per-agent)

Temperature / top_p / seed **reduce variance**; they do not guarantee bit-identical outputs. Softness dial, not true determinism.

| Who sets sampling | Rule |
| --- | --- |
| Extractor (orchestrator LLM call) | Orchestrator only — low autonomy → near-zero temperature, strict schema |
| Local / OpenAI-compatible adapter | Orchestrator passes params on every request |
| Cursor / Claude BYO stacks | Often **cannot** control sampling → rely on **gates** |

**Banned:** agents (or their prompts) owning temperature / “be more creative” overrides. That bypasses the office knob and breaks any-stack consistency.

---

## 6. Dual HITL pipelines + approval board

Industry pattern: policy → durable queue → human (approve / reject / edit) → audit → **agent executes** (actions) or pipeline commits (memory). Gate irreversible / high-stakes; don’t rubber-stamp everything.

**Critical rule: orchestrator gates; agent executes.**  
Orchestrator may see all projects/registry for packing and the board — it does **not** send WhatsApps, dial, or push git with god-access. Agents keep project/channel grants. After human decide, the decision is **translated back to that agent’s run** (same idea as Cursor/Claude ask-back), then the agent runs its tools. Trace everything with `run_id` + `user_id` (+ `approval_id` / `item_id`).

**HITL is not model-decided.** Catalog `hil: follow_autonomy` + low `effective` autonomy → office **binds** `*_locked` (or denies) at session start / call time (A1/A2). The desk model only **calls a tool**; the wrapper creates the card. Envelope text (“autonomy low — wait on humans”) is a **soft hint** so the agent does not spin — it is **not** the control plane. Never rely on “if autonomy &lt; 20 ask for approval” as the only gate.

```mermaid
flowchart TB
    subgraph Memory HITL async
        M1[Extracted fact] --> M2{Algo validations}
        M2 -->|fail hard| Q[Quarantine]
        M2 -->|pass| M3{Trust ladder + sensitivity + autonomy}
        M3 -->|auto| M4[Commit OKF]
        M3 -->|needs human| M5[Memory card on board]
        M5 -->|approve / edit / reject| M4
    end
    subgraph Action HITL sync
        A1[Agent proposes action / batch] --> A2{Risk × channel × autonomy}
        A2 -->|deny| D[Block + journal]
        A2 -->|allow| A6[Agent executes]
        A2 -->|HITL| A3[Pause run · Action card]
        A3 --> A4[Human decide on board / chat]
        A4 -->|approve / edit / partial| A5[Deliver locked payload to agent]
        A5 --> A6
        A6 --> A7[Agent ACK → card swipe-out]
    end
```

Detail of memory storage: [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md).

---

## 6.0 Approval board (product surface)

One **Approval board** for the office. Same inbox for both pipelines; **not** the same card body.

| | **Action card** | **Memory card** |
| --- | --- | --- |
| Tag | `action` | `memory` |
| Timing | **Sync** — pauses the agent run | **Async** — usually after the run |
| Scope | **One agent + one run** only | One fact/batch from one run’s pipeline |
| Human UX | Multi-choice / scrollable options (Claude Code–style); batch rows (e.g. 10 of 10k drafts) | Approve / edit / reject / supersede |
| Visible in | Board **and** that agent’s chat (same durable card) | Board **and** optionally chat |
| Close when | Agent **ACK** that decided items are processed | Pipeline ACK that OKF write done (or reject/dismiss) |

**v1 card kinds = two only:** `action` \| `memory`. Agent clarifying questions, plan check-ins, and “any understanding needed?” stay in **desk chat** — not a third Approvals kind (§6.0.3).

### Card lifecycle

```text
proposed → pending_human → decided → delivered_to_agent → agent_acked → archived (swipe out of board)
                ↘ rejected | expired | user_dismissed
```

- Card stays visible until **`agent_acked`** (action) or pipeline terminal state (memory), unless rejected / expired / user dismissed.
- **Partial approve:** one card, checklist of items; progress e.g. `3/10 done`; swipe-out only when all **decided** items are acked (or remaining explicitly rejected).
- **User hide / swipe without agent receiving the ask:** allowed → `user_dismissed` = cancel. Agent is not required to execute. Journal it. Fine if the ask never arrives.
- **Processed cards** swipe out of the active board; history retained via journal + `run_id`.

### Offline agent

- Card footer: agent offline / unreachable + last seen + countdown toward timeout.
- Orchestrator may **nudge** when back (“reconfirm status”) — still deliver locked decision to the agent, not execute itself.
- If offline past **action timeout** (esp. external send): **expire as reject** — do not auto-send later without a fresh confirm.

### When the card path fails — gold is fallback, not approval

**Gold memory never approves.** Source of truth for decide/ACK is always the orchestrator journal + board.

If card approval fails (expired, dismissed, agent never acked, delivery broken): the human **talks to the agent in chat** and pieces the work together manually. The agent may use **that user’s gold(a,u)** as working notes to recover context (“what was I about to send?”). That is a **fallback conversation path**, not a second approval system. Gold must not silently re-approve or re-fire locked payloads.

### Traceability

Every card links: `approval_id` → `run_id` → `agent_id` → `user_id` (requester) → `project_id` → decision + ACK timestamps. Approval is auditable via **run id** across board, chat, and journal. (Storage shape for agent/run indexes deferred to agent-structure design — not specified here.)

---

## 6.0.1 HITL / board config options (so far)

| Config | Applies | Purpose |
| --- | --- | --- |
| `autonomy` / effective (§4.1) | both | Preset: which gates auto vs HITL |
| `hil` on catalog item | MCP / External tool / optional Tool | `always` \| `never` \| `follow_autonomy` |
| `hil_timer_hours` | MCP / External tool with HIL | Admin-started clock: treat item closer to autonomy for N hours, then **snap back** to **original** `hil` (see §7.2) |
| `risk_class` | catalog item | **Optional** — advisory; `hil` is the operator control |
| `action_timeout` | action | Pending human → expire reject / escalate |
| `memory_timeout` | memory | Softer: remind; do not auto-commit on expiry |
| `offline_grace` | action | When to show offline state on card |
| `ack_timeout` | action | After approve, max wait for agent ACK before escalate |
| `require_reconfirm_after_offline` | action | Offline longer than X → second human confirm before deliver |
| `partial_allowed` | action batches | Approve subset of N drafts |
| `max_batch_size` | action | Chunk large batches into multiple cards |
| `allowlist` graduation | action | Auto after N approvals of same type |
| `user_dismiss_allowed` | both | Swipe = cancel (default true for drafts) |
| `board_retention` | both | How long acked cards stay in history view |
| `notify_channels` | both | In-app / Slack / email for pending cards |
| `sampling_*` | extractor only | Orchestrator-owned; never per-agent |
| `approver_mode` | both | `permissive` (v1 default) \| `strict` (later) — see §6.0.2 |

---

## 6.0.2 Who may Approve (v1 + later)

**v1 — `approver_mode: permissive`:** any of the following may Approve / Reject / Edit on a card:

| Actor | Why |
| --- | --- |
| **Requester** | User who started the run that produced the card |
| **Org admin** | Company override |
| **MCP / cred owner** | Catalog binding owner for that gated capability (action / MCP cards) |

Not “every seat in the org” by default — those three roles. Bind Accept to `run_id` + actor so User B cannot unlock User A’s grant unless they are admin or cred owner.

**Later — `approver_mode: strict`:** only **org admin** and/or **MCP/cred owner** (requester cannot Accept). Optional further tighten to admin-only or owner-only.

Memory cards without an MCP/cred: requester ∪ org admin (cred owner N/A).

### 6.0.3 Three “wait for human” paths (Approvals ≠ clarify)

| Kind | Example | Where | Enforced by |
| --- | --- | --- | --- |
| **ACTION HITL** | WhatsApp / gated MCP / publish hook | **Approvals** board (`action`) + `_locked` / hooks | Orchestrator / hooks (**hard**) |
| **MEMORY HITL** | Promote fact to OKF | **Approvals** board (`memory`) | Orchestrator (**hard**) |
| **Clarify / plan / “ask before implement”** | “OAuth or API keys?” · Cursor `mode: plan` · user said “ask if you need understanding” | **Desk chat** (same thread) | Soft: Envelope band + optional `mode: plan` + user message |

```text
Agent needs a decision that is NOT a catalog / hook / memory gate
  → ask in desk chat (or plan-mode output)
  → human answers in chat
  → agent continues

Agent needs WhatsApp / gated MCP / dangerous shell
  → *_locked or hook → Approvals card → grant → execute

Agent proposes OKF fact (low autonomy / high sensitivity)
  → MEMORY card on Approvals
```

**Do not** put clarify questions on the Approvals board in v1 (inbox noise; wrong Accept/Reject metaphor; no payload lock). Optional later: card kind `clarify` with multi-choice — only if chat UX is too weak.

**Link autonomy → desk chat (soft default):**

| `effective` | Envelope / desk-chat instruction |
| --- | --- |
| **0–20** | **Ask before changes by default** — if understanding is incomplete, ask in this chat and wait; prefer plan; do not edit/implement/push/publish/send until the human answers |
| **40–60** | Ask when blocked, ambiguous, or high-stakes; otherwise proceed |
| **80–100** | Proceed on clear tasks; still stop for hard floors and `*_locked` |

Autonomy changes **how the agent is instructed to use desk chat**. It does **not** open Approvals cards for Q&A. Soft — the model can still skip asking (especially in `agent` mode); pair low band with hooks + Gated catalog for what must not fail.

**Office Q&A** (`Office: …`) is status/knowledge without a desk agent — do not route “clarify before implement” there.

---

## 6.1 MEMORY HITL — validations discovered so far

Two layers: **algo gates** (no human) and **human queue triggers**. Autonomy 0–100 only widens/narrows which trust-ladder steps auto-pass; it does not disable hard algo rules or hard floors.

### A. Algo validations (before / instead of human)

| # | Validation | Rule | On fail |
| --- | --- | --- | --- |
| M1 | **Schema (Zod `.strict()`)** | Extractor may only emit `type`, `content`, `tags`, `citation` (+ optional `domain`, `sensitivity` suggestion). No `projects` / `scope` / `source` / `created` | One reprompt → quarantine |
| M2 | **Citation required** | Every fact cites report line or artifact; extract-only, never infer | Same |
| M3 | **Atomicity / length** | Body over ~100 words → split into multiple facts before validate | Split or quarantine |
| M4 | **Metadata stamp** | Pipeline sets `id`, `scope`, `projects: [run.project]`, `source`, `created`; may **raise** sensitivity, never lower | N/A (code path) |
| M5 | **Project stamp source** | `run.project` from agent workspace/grant lookup — never from LLM | Repo-less agent: explicit project at create **or** all writes → human queue (never silent agnostic) |
| M6 | **Agnosticism impossible at birth** | Empty `projects: []` cannot be set by extractor; facts born project-specific | Structural |
| M7 | **Lexical veto (agnostic)** | Before any promote-to-`[]`, string-check body vs run artifacts (paths, project slug, repo names). Match → block agnostic | Stay project-stamped or HITL with veto note |
| M8 | **Upsert ladder** | Exact key (scope+type+tags) → update; contradiction → supersede candidate; unsure → new+flag | Contradiction → HITL (M-H3) |
| M9 | **Arrays never edited** | Ids never removed from `projects`; arrays only grow (corroboration) or whole fact archives | Structural invariant |
| M10 | **All-links-dead archive** | On project delete: `projects ≠ ∅` ∧ every id deleted → auto-archive (no human) | Mechanical |
| M11 | **Artifacts beat prose** | Code/call/CRM claims without matching artifact → drop or quarantine, not commit as fact | Quarantine / skip |
| M12 | **Pinned immune** | `pinned: true` never auto-pruned | Skip prune candidacy |

### B. Human queue triggers (MEMORY HITL)

| # | Trigger | Why human |
| --- | --- | --- |
| M-H1 | **Scope = org** (and deferred office/BU later) | Company-wide knowledge — trust ladder top |
| M-H2 | **Scope promotion** team→floor→org | Never automatic; earned via review |
| M-H2b | **Floor connect line** create/widen | Cross-team share is gated; maturity may suggest, human approves what crosses |
| M-H3 | **Contradiction / supersede** | Two facts conflict; human picks or confirms supersede |
| M-H4 | **Project-agnostic promotion** | After corroboration (≥2 projects in array) **or** human seeding of universal fact — empty `[]` only via this gate (+ lexical veto M7) |
| M-H5 | **Sensitivity** `customer` \| `legal` (and pricing/compliance when flagged) | High blast radius if wrong |
| M-H6 | **Autonomy band low** | e.g. 0–20: almost all memory writes → queue |
| M-H7 | **Floor without artifact corroboration** | Floor write lacking artifact → escalate to queue (or block until corroboration) |
| M-H8 | **Unsure upsert** (new+flag) | Dedupe couldn’t decide match vs new |
| M-H9 | **Quarantine resolution** | Failed validation after one reprompt — human fixes or discards raw report |
| M-H10 | **Prune candidates (judgment class)** | Unused in N runs; agnostic facts whose `source` run was a **deleted** project; weak leftover links — nominate only, human archives |
| M-H11 | **Gold hygiene ack** (optional) | After project delete, confirm users cleaned gold(a,u) (or `reset`) |

### C. Explicit non-triggers (do **not** ask humans)

- Sole-project facts on project delete when **all links dead** → auto-archive (M10)
- Team + low sensitivity + mid/high autonomy → auto-commit
- Array growth `[p1]→[p1,p2]` via corroboration → automatic; only **empty `[]` promotion** needs M-H4
- Multi-project facts with a living project id still present → leave untouched (stale deleted ids stay as provenance)

---

## 6.2 ACTION HITL — validations discovered so far

### A. Algo validations (before execute)

| # | Validation | Rule | On fail |
| --- | --- | --- | --- |
| A1 | **Catalog `hil` + effective autonomy + timer** | Item `always` / `never` / `follow_autonomy`; §4.1 `effective`; elevation → Direct-like then snap (§7.2). **Does not** bypass A3 hard floors | Deny / HITL / allow |
| A2 | **Autonomy band** | When `follow_autonomy`: bands on **effective** 0–20 HITL-heavy; 80–100 allowlist + hard floors | Per band |
| A3 | **Hard floors** | External customer send, legal/binding, PII/PHI, money, prod — never auto at 100 without admin | Always HITL or deny |
| A4 | **Allowlist** | Repeated human approvals of same action type + low risk may graduate to auto-allow | Else HITL |
| A5 | **Payload lock** | Approved (or edited) payload delivered to agent must match what human saw | Re-queue |
| A6 | **Timeout** | Pending approval expires → escalate or **fail-safe reject** (especially external send) | Reject / escalate |
| A7 | **Preview required** | Card must include human-readable effect preview (MCP **name OK** on card) | Cannot approve blind |
| A8 | **Registration** | Agent may only use Direct MCP/API it registered; gated = `_locked` + grant | Deny |
| A9 | **Execute with agent** | After Accept, short-TTL grant → **agent** runs real MCP (intermediates, same `run_id`) | Escalate / expire |
| A10 | **One card ↔ one agent + run** | No cross-agent approve; grant bound to `run_id` + requester `user_id` | Structural |
| A11 | **Gated secret** | HIL MCP unlock secret is server-side only — never inject into agent prompt/chat/gold | Structural |
| A12 | **Approver allowlist** | Only actors in §6.0.2 for current `approver_mode` | Deny decide |

### B. Human queue triggers (ACTION HITL)

| # | Trigger | Examples |
| --- | --- | --- |
| A-H1 | **External send** | Slack/email/WhatsApp/SMS to customer; public social post |
| A-H2 | **Outbound call / dial** | Sales calling agent |
| A-H3 | **Money / contract** | PO, payment, signed terms, CRM stage that implies commitment |
| A-H4 | **Prod / irreversible infra** | `git push` to main, deploy, prod DB write, access grant |
| A-H5 | **PII / legal content** | Sending or writing content flagged sensitive |
| A-H6 | **CRM / ERP mutating writes** when risk ≥ system_write and not allowlisted | Ticket create may auto; account delete → HITL |
| A-H7 | **Autonomy low** | Band forces HITL even for otherwise medium actions |
| A-H8 | **Guardian / compliance flag** | Another agent or policy marks action for review |

### C. Usually auto (unless autonomy low / hard floor)

- Read-only tools, drafts saved privately, internal notes
- Team-local dry-runs, staging reads
- Allowlisted repeated safe actions after enough approvals

---

## 6.3 Shared HITL / board rules

| Rule | Detail |
| --- | --- |
| Durable queue | Survives restart; not only in-memory |
| One board, two card kinds | Tagged `memory` \| `action` only in v1; **clarify stays desk chat** (§6.0.3) |
| Action sync / memory async | Action pauses run; memory usually post-run |
| `_locked` wait | Wrapper **blocks** + internal exp backoff until Accept / Reject / `action_timeout`; harness sees one slow tool — not model-driven retry (§7.3) |
| Board + chat | Same durable card in approval board and that agent’s chat |
| Autonomy ↔ desk chat | Low band → Envelope “ask before changes by default” in **desk thread** (soft); not an Approvals card (§4 bands · §6.0.3) |
| Batch, don’t interrupt | Memory: prefer inbox. Action: pause mid-run when gate fires |
| Journal | Request → classification → human decision → deliver → ACK/outcome — append-only; link via `run_id` |
| Agent ACK (action) | Card stays until ACK (or reject/expire/dismiss); then swipe-out |
| User dismiss | Swipe/hide cancels outstanding ask; agent need not execute |
| Gold ≠ approval | Per-user gold is fallback context when card path fails; human asks agent in chat and pieces work together |
| Approvers | §6.0.2 — v1 permissive (requester ∪ org admin ∪ MCP/cred owner); later strict |
| Orchestrator ≠ free MCP user | Gated: grant unlocks **agent** to run MCP; Direct: registered only |
| Secret never in agent context | HIL unlock is server-side Accept — not paste-into-model |
| No LLM disposer | Humans (or deterministic allowlist) dispose — model does not “decide” to open HITL |
| Autonomy never bypasses hard floors | Slider cannot remove A3 / M-H5 floors without admin |
| Elevation never bypasses hard floors | `hil_timer_hours` loosens HITL on that item only — A3 still applies (§7.2) |
| Autonomy soft + hard | Low band = policy bundle: Gated catalog + MEMORY HITL + hook profile + Envelope “ask before changes” in desk chat (soft; natives may still mistake) |
| `_locked` guarantee | Inference: complete. Harness: catalog-only (no native twin) — §7.3 |

---

## 7. Capabilities catalog (Guardrails)

**v1 simplicity:** one org catalog; **grants = agent-level registration only** (no team/floor ACL matrix). Operator opens an agent in the UI → registers MCP / skill / External tool (e.g. Firecrawl). Agent never browses the full org catalog in its prompt — only its registered subset is injected at run start (**scoped injection**). Built-in **Tools** (`gold.*`) default-inherit — see §7.1.

**Compose non-coding desks:** Inference connection + catalog Tools / MCP / External tools / skills is enough for Sales/Marketing/Support/BA without a new runtime class. Coding harnesses stay for heavy implement desks. See [STACK_ADAPTERS.md](./STACK_ADAPTERS.md).

### 7.0 Guardrails tab vs Approvals

| Screen | Job |
| --- | --- |
| **Approvals** | HITL **inbox** — memory + action cards; Accept / Reject / Edit |
| **Guardrails** | **Catalog + policy** — what exists in the org, `hil` / timer, desk registration |

Guardrails is **not** a second approval queue. Autonomy slider + hard floors still live in desk/org settings; Guardrails is where capabilities and per-item `hil` are managed.

v0 may **stub** the Guardrails nav (direction visible); full catalog UI is post-v0 — [V0_SCOPE.md](./V0_SCOPE.md).

### 7.1 Four catalog kinds

| Kind | UI label | What admin adds | Notes |
| --- | --- | --- | --- |
| **MCP** | MCP | Server package / URL + auth | Protocol servers |
| **Tool** | Tools | Light **in-orchestrator desk functions** (no MCP/HTTP required) | e.g. `gold.read`, `gold.update` |
| **Skill** | Skills | Playbook (prompt + which MCP / External tool / Tool ids it needs) | Not a server — how we do work |
| **External tool** | External tools | HTTP API: Firecrawl, AWS, GitHub, custom REST | `baseUrl` + `secretRef`; presets + custom. **APIs only — not MCP** |

**Do not confuse:**

| Name | Where | What |
| --- | --- | --- |
| **Tools** (catalog) | Guardrails | Office-implemented desk functions |
| **External tools** (catalog) | Guardrails | Third-party **HTTP APIs** |
| **External agent** (Stacks) | Stacks tab | Peer agent via MCP/A2A — [STACK_ADAPTERS.md](./STACK_ADAPTERS.md) |
| Harness natives | Cursor/OpenCode | fs / shell / git / browser — **not** a catalog kind; hooks/sandbox |
| `tools.mode` | `agent.yaml` | `none` / `mediated` / `worker` — runtime class, not Guardrails |

Native stack built-ins stay out of the four-kind catalog.

#### Tools = desk functions only

Tools are **small functions the desk agent may call**, implemented by the office (not an MCP server, not an external HTTP product).

| In Tools | Not Tools |
| --- | --- |
| `gold.read` / `gold.update` (that user’s `gold(a,u)`) | OKF extract / `remember:` pipeline |
| Other light desk helpers (later: e.g. draft a card, read own recent_thread slice) | Office Q&A / `OFFICE_MODEL` jobs |
| | Packing, journal, HITL disposer, catalog admin |
| | Anything that is **orchestrator spine**, not a desk capability |

**Default inherit:** built-in `gold.read` + `gold.update` are registered on **all agent desks** (`seat_kind: agent`) unless admin unregisters / denies. **Human seats** do not get gold or these Tools — [IDE_FIRST.md](./IDE_FIRST.md).

Built-in gold Tools: default `hil: never` (own notepad). Custom Tools may set `hil` like MCP / External tools.

Secrets **should** live in vault / env refs — never deliberately in OKF facts or agent gold. Accidental leaks possible in v1 — see §10.

**Platform vs catalog:** `DATABASE_URL`, office path, process auth = **platform config** (env). Do **not** register them as External tools. v0 UI: platform settings **read-only**; passwords **masked by default**, admin **may reveal**. See [IMPLEMENTATION.md §7.1](./IMPLEMENTATION.md#71-configuration-buckets--ui-v0).

### 7.2 HIL policy on the catalog item (admin)

When adding MCP, External tool, or a custom Tool, admin sets:

| Field | Values |
| --- | --- |
| `hil` | **`always`** \| **`never`** \| **`follow_autonomy`** (three options only) |
| `hil_timer_hours` | Optional: elevate toward autonomy for N hours, then **snap back** to the **original** `hil` set at create |
| `risk_class` | **Optional** |

No agent-level `force_hil` / inherit matrix in v1. Timer elevations are **admin-started** (not the agent, not the card requester) and **journaled** (who, catalog item, N hours, original `hil`).

`hil_timer_hours` is a **clock**, not a fourth `hil` value. Stored `hil` does not change.

**“Closer to autonomy” (product rule):**

| Original `hil` | During elevation window | After snap-back |
| --- | --- | --- |
| `always` | **Direct** (`never`-like): real MCP/API bound; **no per-call HITL** | Gated again (`_locked` + card + grant) |
| `follow_autonomy` | Treat as a **higher autonomy band** (fewer HITL trips; Direct if that band allows) | Back to desk/team/org `effective` autonomy |
| `never` | Already Direct — timer is a no-op | Still `never` |

```text
effective behavior at call / unlock time:
  if within elevation window → Direct / higher band (table above)
  else → use catalog hil default
  follow_autonomy (outside window) → autonomy 0–100 band decides HITL vs allow
```

**Hard floors still apply (A3).** Elevation loosens **HITL on that catalog item**; it is not a license to ignore deny rules (mass WhatsApp, `npm publish`, prod deploy, PII send, …). Incident weekend: “Jira freely for 4h, still cannot publish.”

**Live harness / inference sessions:** tool lists are bound at `agent.start` / session (re)bind. Elevation start or snap-back does **not** hot-swap a running loop. Recycle the TTL session at window start and expiry, or the timer is cosmetic for that desk.

### 7.3 Two pools: Direct vs Gated (`_locked`)

| Pool | When | What agent runtime gets |
| --- | --- | --- |
| **Direct** | `hil: never`, or temporarily elevated (§7.2) | Real MCP / External tool bound — use freely mid-run (orchestrator does **not** validate every tool hop) |
| **Gated** | `hil: always` (default HIL) | **Real MCP / External tool is never attached.** Agent only sees a **`_locked` wrapper** name |

Example: real server `@modelcontextprotocol/server-everything` → agent-facing `@modelcontextprotocol/server-everything_locked`.

- Agent may **see and register** HIL MCPs in the UI.
- Backend: only the `_locked` entry is wired into the agent tool list. **Do not inject the real MCP name** into the agent tool list / prompt.
- A **server-side secret** is generated when the HIL MCP is created; **never paste it into the agent chat / prompt / gold** (user instructed not to share with the agent). Accept on the approval card applies the unlock **server-side**.
- Name abstraction is weak by itself. **Gate = capability path**, not the string `_locked`.

**When `_locked` actually intercepts (honest):**

| Runtime | Who owns the tool loop? | Gated catalog MCP? |
| --- | --- | --- |
| **Inference** (Bedrock / Claude API / Ollama + office tools) | **Office** | **Yes — 100%.** Model can only call what you listed. `_locked` → card → grant is real. |
| **Harness** (OpenCode / Cursor / Claude Code) | **Their** agent loop | **Yes iff** that action has **no native twin** and **no leaked creds**. Else they skip `_locked`. |

Harness native twins (fs, shell, git, browser, harness-local MCP the human added) are **not** `_locked` — use **stack hooks / sandbox** ([STACK_ADAPTERS.md](./STACK_ADAPTERS.md) §8). Catalog-only actions (e.g. **send WhatsApp** — Cursor/OpenCode do not ship that) behave like inference: agent must call `*_locked` → orchestrator.

```text
  Office injects *_locked (never the real MCP id)
       ↓
  Agent calls *_locked  →  card  →  grant  →  real MCP     ← catalog-only path
       ↓
  OR harness uses Shell/curl/browser + token / extra MCP   ← bypass; not gated
```

| Claim | Inference desk | Harness desk |
| --- | --- | --- |
| Catalog MCP `hil: always` never attached until grant | **Yes** | **Only if** harness does not also have the real server/creds |
| Native `Write` / `Shell` / harness-local MCP always HITL | N/A | **No** — hooks/sandbox |
| WhatsApp / niche CRM via **office-catalog** MCP only | Card before send | Card **if** they use `_locked`; **not if** token is in env and they `curl` |
| After Accept, further hops in that grant | Not re-gated (by design) | Same |

**Market as:** Inference HITL is complete. Harness HITL is complete **for catalog-only capabilities**. Do not claim “every harness tool call returns to the orchestrator.”

#### Wait / grant while harness (or Inference) is mid-tool-call

From the **office** view the run is paused on the action card. From **Cursor/OpenCode** the agent sees one **slow / blocking** tool call — it should **not** invent its own exp-backoff loop in the prompt.

**v1 preferred:** put wait + backoff **inside the `*_locked` wrapper** (office / MCP handler):

```text
Agent:   call whatsapp_locked.send(...)     ← one tool call, stays open
Wrapper: create action card; poll grant with exp backoff (e.g. 1s, 2s, 4s… cap)
         Accept → return success (+ forward to real MCP)
         Reject / action_timeout → return fail-safe error (esp. external send)
Agent:   continues with that tool result
```

| Pattern | Use? |
| --- | --- |
| Wrapper **blocks** + internal exp backoff until Accept / Reject / `action_timeout` | **Yes — v1** |
| Wrapper returns `pending` immediately; **model** retries `*_locked` | **No** — model may skip, invent, or spam |
| Prompt “wait and retry later” as the only waiter | Soft only — not the waiter |

Cap wait with `action_timeout` (§6.0.1). Do not wait forever (SDK / HTTP / worker idle limits). If the stack **drops** long-open tool calls: return `pending` + `approval_id` quickly, then **office resumes** the same `run_id` after Accept (`agent.send` / continue) — still not model-driven backoff.

```mermaid
sequenceDiagram
    participant A as Agent
    participant L as *_locked wrapper
    participant O as Orchestrator
    participant H as Human card
    participant M as Real MCP

    A->>L: call gated capability (tool call stays open)
    L->>O: no active grant for run_id
    O->>H: approval card (MCP name OK)
    loop Exp backoff until decide or action_timeout
        L->>O: poll grant
    end
    H->>O: Accept
    O->>L: short-TTL grant for this agent + run_id
    L->>M: forward (agent owns session / intermediates)
    M-->>L: result
    L-->>A: tool result (unblocks Cursor / Inference)
    Note over O,A: grant expires → locked again
```

**Agent remains E2E task owner:** MCP runs **with the agent** after unlock (intermediates stay in the agent loop, same `run_id`, knowledge not isolated in an office-only runner). Orchestrator = vault + HITL + grant; not a second persona chatting MCP.

### 7.4 Soft vs hard (honest split)

| Mechanism | Role |
| --- | --- |
| Registration + scoped injection | Deterministic **scope** — what this agent may request / have |
| Direct MCP mid-run (`never` or elevated) | Free use inside adapter — **not** per-call orchestrator HITL |
| `_locked` + card + grant (wrapper wait + backoff) | Deterministic **gate** before real catalog MCP is usable — **complete on Inference**; **complete on harness only when no native twin / leaked creds** |
| Stack hooks / sandbox | Gate **native** harness tools (`npm publish`, shell) — not `_locked` |
| Envelope autonomy band text | **Soft** — autonomy applies to *everything* as instruction (incl. code edits); model may still mistake. Complements hooks; never replaces `_locked` for catalog sends |

**Autonomy is for everything:** low `effective` selects a **policy bundle** (bind Gated catalog items, MEMORY HITL-heavy, optional stricter pack / `mode: plan`, **hook profile**, **soft envelope**). Soft prompt covers natives the office does not intercept. Hard layers cover what must not fail. See [STACK_ADAPTERS.md §8.2](./STACK_ADAPTERS.md#82-low-autonomy-on-harness-desks-cursor--opencode).

### 7.5 Explicit non-goals (v1)

- No team/floor capability ACL matrix  
- No orchestrator inventing facts without retrieval (office chat = retrieve + cite only — §2.9)  
- No relying on paste-key-into-model as the unlock mechanism  
- Full MCP proxy that inspects every byte — optional later; `_locked` + grant is the simple path  
- Claiming `_locked` is 100% safe against a compromised or malicious agent runtime  
- Claiming harness `_locked` intercepts **native** Cursor/OpenCode tools (fs/shell/git/browser)

---

## 8. Personas: domain × channel × risk (not a closed market list)

Persona templates are **not** an exhaustive list of industries. Markets never finish. Open axes:

| Axis | Answers | Examples |
| --- | --- | --- |
| **Domain** | What kind of work | eng, sales, legal, hr, support, marketing, finance, security, ba, ops, data, … (extensible) |
| **Channels / tools** | What can fire | git, shell, slack, email, phone, whatsapp, crm, erp, docs, … |
| **Risk class** | Default gate strictness | read_draft · system_write · external_send · money_legal_pii |

```yaml
# persona template (seating metadata — not a memory fact)
persona: sales_caller
domain: sales
channels: [phone, whatsapp]      # side-effect surfaces (descriptive)
stack: openai-compatible         # or cursor | claude | ...
workspace: null | path/to/repo
# capabilities: registered per agent in Guardrails (MCP / Tool / Skill / External tool ids)
# — not a team-level grant list in v1; gold.* Tools default-inherit agent desks
```

Coding agents are just `domain: eng` + stack defaults + registered APIs/MCPs as needed. Same office, same memory rules, same knob.

**Full agent file format + fixed Office Envelope (prepended every run):** [AGENT_DEFINITION.md](./AGENT_DEFINITION.md).

### Starter catalog (illustrative — users can add more)

| Domain family | Examples | Typical risk |
| --- | --- | --- |
| Assistant | Summarizer, briefing, research | read_draft |
| Analyst / BA | Requirements, forecasting | system_write (memory) |
| Tasker / ops | Tickets, CRM update, data entry | system_write |
| Sales / GTM | Calling, texting, outreach | external_send |
| Support / CS | Slack/email replies | external_send |
| Coding / eng | Repo, PR, deploy | system_write → prod |
| Finance / risk | Anomaly, credit, contracts | money_legal_pii |
| Legal / counsel | Contract review, redlines, policy | money_legal_pii |
| HR / people | Recruiting, policy Q&A, onboarding | money_legal_pii (PII) |
| Marketing | Campaign copy, social, brand | external_send |
| Product / PM | PRDs, roadmaps | read_draft / memory |
| Data / analytics | SQL, dashboards | system_write / PII |
| Security / SOC | Alert triage, access reviews | system_write |
| DevOps / SRE | Incidents, infra | prod |
| Procurement | RFQ, PO drafts | money_legal_pii |
| Guardian / compliance | Policy check, audit | meta — reviews others |

Regulated verticals (e.g. healthcare/PHI) may need extra hard floors — not only a persona row.

---

## 9. Module split (implementation note)

Keep two rhythms inside the orchestrator codebase (**Python / FastAPI** target):

| Module | Path | Failure mode |
| --- | --- | --- |
| **Runtime coordinator** | Routing, packing, office chat retrieve, action gates, capability grants / `_locked`, WS | Latency-sensitive; must not block on extraction |
| **Memory / HITL pipeline** | Extract, upsert, review queue | **Async job** after run; stuck extraction must never delay chat |

Shared: registry, derived index, journal, **effective autonomy** (§4.1), **capability catalog + bindings + registrations**, multi-user run isolation.

**Concurrency (v0):** async/await everywhere for I/O; `asyncio.create_task` / FastAPI BackgroundTasks for extract/export; rare `asyncio.to_thread` only for sync SDKs; **no** threading architecture; **no** Celery; **no** multiprocessing unless profiled. Later scale jobs with **arq**. Detail: [IMPLEMENTATION.md](./IMPLEMENTATION.md).

---

## 10. Security — known gaps (TODO)

Do not market these as solved. Accepted for v1; track for hardening.

| Gap | Reality | Later |
| --- | --- | --- |
| **`_locked` / grant** | Inference: intercept is complete. Harness: catalog-only path only (no native twin / leaked creds). After Accept, agent runs MCP under `run_id` — not a hard sandbox / full proxy | Full MCP proxy, short-lived scoped tokens, no raw key in agent context, stronger runtime isolation |
| **Creds in gold** | Free-text `gold(a,u)` may accidentally store API keys | Detect/redact on write; size caps; easy reset; UI warning |
| **Creds in OKF** | Fact bodies may contain secrets; DB ≠ encryption-at-rest / field scrub | Scrub pipeline; encrypt sensitive; purge + key rotation on incident |
| **Intended secret path** | Catalog vault / env refs — never in agent.yaml | Keep; audit accidental leaks |
| **Platform password reveal (v0)** | Admin UI may Show DB/platform secrets (read-only edit via env) | Optional no-reveal / vault-only for multi-tenant |

Memory-side detail: [MEMORY_ARCHITECTURE.md §9](./MEMORY_ARCHITECTURE.md#9-security--known-gaps-todo).

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-02 | Initial: pillars, responsibilities, controllability 0–100, sampling policy, dual HITL, domain×channel×risk personas |
| 2026-08-02 | §6.1–6.3: full MEMORY/ACTION validation catalogs (agnostic promotion, lexical veto, quarantine, prune, hard floors, allowlist, payload lock) |
| 2026-08-02 | §6.0 approval board: action sync / memory async cards, execute-back-to-agent + ACK, offline, configs; gold = fallback only when card path fails (not approval) |
| 2026-08-02 | Hierarchy rename box→team; floor connect-line HITL (M-H2b); office nesting deferred |
| 2026-08-02 | §7 Capabilities: org catalog MCP/Skills/API; agent-only registration; hil 3-way + timer; Direct vs `_locked` gated; grant→agent runs MCP; no ACL matrix / no orchestrator Q&A |
| 2026-08-03 | Multi-user: C(a,p,u), gold(a,u), §4.1 effective autonomy; §6.0.2 approvers; `_locked` honesty; §10 Security TODOs |
| 2026-08-03 | §2.9 Office chat (cite-bound Q&A); Python/FastAPI target; async job rules; link IMPLEMENTATION.md |
| 2026-08-04 | Platform config ≠ catalog; v0 read-only UI + admin password reveal — link IMPLEMENTATION §7.1 |
| 2026-08-04 | Link AGENT_DEFINITION.md (yaml+md, Office Envelope, workspace by stack) |
| 2026-08-04 | Link V0_SCOPE, ANALYTICS, CONNECT — channel on runs; journal for trust surface |
| 2026-08-07 | recent_thread in pack; OFFICE_MODEL for extract / office Q&A / optional thread summarize; HITL stays deterministic |
| 2026-08-10 | §2.9 knowledge: filter → top-K rank (optional `fact_embeddings`) → cite-bound phrase; link MEMORY §4 |
| 2026-08-11 | §2.10 desk UX knobs; stack hooks vs office policy; link STACK_ADAPTERS.md |
| 2026-08-12 | Human seats: MEMORY-only HITL; Connect WorkPacket hooks |
| 2026-08-12 | Catalog compose for non-coding desks; link STACK_ADAPTERS direction |
| 2026-08-14 | §7.2 elevation timer mapping + session recycle + hard floors; §7.3 `_locked` = capability path (Inference 100%; harness iff no native twin) |
| 2026-08-14 | §7 Guardrails tab vs Approvals; four kinds: MCP · Tools · Skills · External tools; gold.* default-inherit agent desks only |
| 2026-08-14 | HITL not model-decided; `_locked` wrapper wait + exp backoff; autonomy soft+hard bundle (link STACK §8.2) |
| 2026-08-14 | §4 / §6.0.3: autonomy ↔ desk chat (ask before changes at 0–20); clarify ≠ Approvals |
