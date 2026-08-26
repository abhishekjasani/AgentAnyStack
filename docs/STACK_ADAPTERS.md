# Stack adapters & coding runtimes

**Purpose:** How AgentAnyStack integrates **execution engines** behind agent desks — three connection kinds, adapter families, Stacks-tab UX — without rebuilding each product’s tool harness or settings console.

**Related:** [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) · [AGENT_DEFINITION.md](./AGENT_DEFINITION.md) · [ORCHESTRATOR.md](./ORCHESTRATOR.md) · [IMPLEMENTATION.md](./IMPLEMENTATION.md) · [IDE_FIRST.md](./IDE_FIRST.md)

---

## 1. Strategy (agreed)

**Do not build a parallel coding-agent tool platform** (homemade `read_file` / git / shell suite to “match Cursor”).

| Coding desks | Non-coding desks |
| --- | --- |
| Use mature **coding harnesses**: **OpenCode**, **Cursor**, **Claude Code** (`tools.mode: worker`) | **Inference** APIs (Bedrock / Claude API / Ollama) with `tools.mode: none` (+ light MCP) |

- **Office** = desks, pack `C(a,p,u)`, Envelope, HITL, gold/OKF, office Q&A, Connect  
- **Stack connection** = BYO engine (keys / endpoints) registered on the **Stacks** tab  
- MCP/skills = catalog extras — not a substitute coding runtime  
- **Abstract setup complexity** for users (wizard + adapter), **don’t** clone every vendor’s full UI  

Slogan: *integrate, don’t replace stacks.*

**IDE-only developers:** **human seats** — BYO IDE agent; office = pack + WorkPacket sync + MEMORY HITL only. See [IDE_FIRST.md](./IDE_FIRST.md). Human seats are **not** a fourth stack kind.

### Desks are the hero; runtimes stay few

Too many **runtime classes** shadow different kinds of **desks**. Cap Stacks kinds at **~2–3 forever**. New products (Cursor, v0, Harvey) are **tiles under an existing kind**, not new kinds.

| Hero (many) | Plumbing (few) |
| --- | --- |
| Developer, Sales, Marketing, Support, BA, … | **Inference** · **Coding harness** · **External** |
| Desk templates + pack + HITL | OpenCode, Cursor, Bedrock as *options inside* kinds |

```text
Wrong:  “We support 12 runtime classes”
Right:  “We seat many desks; each picks one of ~2–3 connection kinds”
```

**User-facing language:** say **Connect Cursor / OpenCode / Bedrock** (connection, product). Reserve **adapter** for engineering (`HarnessAdapter`, `adapters/opencode/`). Never “Add Cursor adapter” in the UI.

### Any-stack feasibility (honest)

| Layer | Feasible? |
| --- | --- |
| One office: desks, pack/OKF, HITL, Connect | **Yes** |
| Few connection kinds + many desk templates | **Yes** |
| Equal deep twins of Cursor + Canva + Harvey in year one | **No** |

Thesis: *any runtime that talks to the orchestrator can get a desk and share scoped memory.*  
Not: *we deeply embed every vertical AI product equally.*

**Coding wedge is OK:** ship OpenCode/Cursor first for eng; keep office core domain-agnostic; seat Sales/Marketing early on **Inference + catalog** so the product doesn’t become coding-only by accident.

### Compose desks without a new harness (Inference + catalog)

Besides sophisticated coding harnesses, orgs **fairly build** most desks from:

```text
Inference connection  +  Guardrails catalog (MCP / Tools / Skills / External tools)
  → Sales / Marketing / Support / BA / research desks
```

| Desk | Typical power |
| --- | --- |
| Developer (heavy coding) | **Coding harness** |
| Sales, marketing, support, BA, ops | **Inference** + External tools (Firecrawl/CRM/…) + MCP/skills + gold.* Tools |
| Design/legal/clinical “full product” | Later harness or Connect — don’t block v1 |

Register creds in catalog → desk registration → scoped injection + `hil` ([ORCHESTRATOR.md](./ORCHESTRATOR.md) §7).  
**Limit:** APIs ≠ Canva canvas / Cursor repo brain — don’t overclaim.

### Core desks vs core runtimes

| Core **desks** (org essentials) | Core **runtimes** (v1 engines) |
| --- | --- |
| Developer, QA, BA, Sales, Marketing, Support, … | **OpenCode** (OSS harness) + **one Inference** (Ollama/Bedrock/Claude API) |
| Templates in `office/` | Cursor etc. optional later |

Minimum proof set: **Developer** (harness) + **one GTM or knowledge desk** (Inference + MCP).

### When “product as runtime” fails (hedge)

Single harness-as-product fails on ToS/SDK churn, context fight vs OKF, credential tenancy, over-promising native magic, weak HITL, or IDE users bypassing the office runner. Hedge: **multi-connection + strong memory + human seats** — office owns the junction, not the vendor.

---

## 2. Three connection kinds (Stacks tab)

Everything a user **adds under Stacks** is one of:

| # | Kind | What it is | Examples | Desk `tools.mode` |
| --- | --- | --- | --- | --- |
| **1. Inference** | Model API only — office or harness supplies tools (or none) | Bedrock, Claude API, OpenAI, Ollama | `none` (or light MCP) |
| **2. Coding harness** | Specialized product with native tools / agent loop | OpenCode, Cursor, Claude Code | `worker` |
| **3. External agent** | Agent already running elsewhere; office routes / packs | Google ADK, A2A peer, remote agent via MCP | Connect-style **bridge** — not classic `create` worker |

**Harness may use Inference for models** when the product allows (e.g. OpenCode → Bedrock/Ollama via **Test & register** + hard provider inject). Office stores the registered `(provider_id, model_id)` pairs; **does not** reimplement the harness’s full model-router UI. Soft catalog-only “Models via” without inject is forbidden.

**Domain products** (v0-by-Vercel, Julius, Harvey, Abridge, Miro Assist, …) are useful **roadmap analogies** (design / data / legal / clinical / PM harnesses). Treat as future harness or Connect partners — **not** the v1 adapter queue.

### Adapter families (backend)

```text
StackAdapter          # shared: health, credentials ref, capability flags
  InferenceAdapter    # chat completions ± mediated/MCP tools
  HarnessAdapter      # create/resume/send/stream/cancel/dispose + native tools
ExternalAgentBridge   # invoke/subscribe MCP/A2A — separate from spawn-cwd workers
```

| Policy | Rule |
| --- | --- |
| One mega-`if cursor / harvey / abridge` adapter | **No** |
| Capability flags (`models?`, `native_tools?`, `modes?`) | **Yes** |
| Passthrough advanced config opaque to core | **Yes** |
| Frontend themes by **kind** (1 / 2 / 3) | **Yes** |

### Other axes (not stack kinds)

| Axis | Examples |
| --- | --- |
| **Seat kind** | `agent` vs `human` |
| **Domain × channel × risk** | Persona templates |
| **Who holds credentials** | BYO vs office-orchestrated |
| **Local cwd vs cloud VM vs remote peer** | Isolation story |
| **Memory participation** | Full pack vs WorkPacket-only |

---

## 3. Stacks tab UX (what user adds & how it looks)

**Stacks = connect engines.** Not create agents. Desks pick a **connected** stack later (Team → Add agent).

### Empty → Add stack

```text
Stacks
  No connections yet.
  [ Add stack ]

Add stack
  1) Kind:  Inference | Coding harness | External agent (v1: stub/Soon)
  2) Product (by kind):
       Inference → Bedrock | Claude API | OpenAI-compatible (Ollama) | …
       Harness   → OpenCode | Cursor (later) | …
  3) Credentials / endpoint / region  → connection_id e.g. bed-prod, ollama-local, oc-local
  4) Inference: Verify & add / discover models into that connection’s catalog
  5) OpenCode: select candidates from Inference catalogs → Test & register
     (no default linked models; hard-inject providers on serve — not UI-only “Models via”)
  6) Test → Save
```

**Fields (examples)**

| Kind · product | User adds |
| --- | --- |
| Inference · Bedrock | Credentials (IAM access key + secret or Bedrock API key + region); **Verify & add** model IDs |
| Inference · OpenAI-compatible | Presets (Ollama, Groq, Zen, Custom base URL & API key); **Verify & add** model IDs |
| Local Models (Ollama) | Top-level tab outside Stacks for curated local pull (SSE), GPU status, flush, delete, and **1-click Enable as Inference** |
| Harness · OpenCode | Spawn rules; **registered models** via Test & register from Inference |
| Harness · Cursor | API key — **out of Create UI until adapter exists** |

### Visible list = **connection cards** (not one card per model)

```text
┌─────────────────────────────┐  ┌─────────────────────────────┐
│ oc-local (OpenCode)         │  │ bed-prod (Bedrock)          │
│ Coding harness              │  │ Inference                   │
│ Registered: Nova Lite ✓     │  │ Verified: Nova Lite, …      │
│ Serves / sessions (runtime) │  │ Region · Test               │
│ [Edit] [Test & register]    │  │ [Edit] [Verify & add]       │
└─────────────────────────────┘  └─────────────────────────────┘
```

| On Stacks | Not on Stacks |
| --- | --- |
| Inference / harness / external **connections** | Agent name, persona, team |
| Status, registered/verified models, used-by desks | Autonomy, pack depth |
| Product tiles (“Connect OpenCode”) | Label “adapter” in UI |
| Test / edit credentials | Full domain marketplace as live equals in v1 |

Models appear **inside** an Inference card (verified list) and **inside** an OpenCode card (registered list), not as separate stack rows.

### Desk creation (elsewhere — Team)

```text
Team → Add agent
  → connection (from Stacks) → stack derived from product
  → model from that connection’s list
       Inference → verified catalog
       OpenCode  → registered list only (Test & register)
  → workspace / pack / autonomy
  → writes agent.yaml  (connection_id + stack + model — never ses_ / port)
```

Desk badge example: `OpenCode · Nova Lite` or `Ollama · qwen2.5:7b`.

**Rule:** `stack` = adapter family; `connection_id` = Stacks profile; `model` = engine id. See [18_OPENCODE.md](./architecture/18_OPENCODE.md).

---

## 4. “One agent” means one desk session (not one office brain)

```text
BA desk  →  epic / facts → team OKF (or remember:)
                ↓
Dev desk chat  →  orchestrator packs C(a,p,u)
                ↓
Harness session  →  create/resume (TTL-scoped to this desk + user)
                ↓
send(Envelope + AGENT.md + pack + user message)
                ↓
Native harness tools in workspace.path
                ↓
idle TTL → dispose; optional store session id for resume
```

| Claim | True? |
| --- | --- |
| One TTL-scoped harness session on the **Dev desk** can complete an epic | **Yes**, if BA context is **in the pack** |
| That session uses **the stack’s own tools** | **Yes** |
| One session shared across BA + Dev + Tester desks | **No** |
| Office must reimplement those tools | **No** |
| Bare Inference alone equals Cursor-class coding | **No** — use a harness |

---

## 5. Core vs adapters (contributor mastery)

```text
┌─────────────────────────────────────────────┐
│  CORE (stable)                              │
│  desks · pack · Envelope · HITL · gold/OKF  │
│  journal · autonomy · Connect · agent.yaml  │
└─────────────────────────────────────────────┘
         ▲           ▲           ▲
    opencode/    cursor/    openai_compat/ + bridges/
```

| Layer | Owner | Scope |
| --- | --- | --- |
| **Core** | Product team | Never fork per stack |
| **`StackAdapter` / bridge contract** | Core | Lifecycle + capabilities |
| **`adapters/opencode/`** | OpenCode-fluent | Multi-model, Bedrock link |
| **`adapters/cursor/`** | Cursor-fluent | SDK, modes, hooks |
| **`adapters/claude_code/`** | Claude Code | CLI/SDK |
| **`adapters/openai_compat/`** | Inference | Bedrock/Ollama/Claude API |
| **`bridges/`** | External/MCP/A2A | Peer agents |
| **UI** | Frontend | Stacks by kind; desk wizard uses connections |

**v1 integration queue:** open/flexible first — **OpenCode** (+ Bedrock models) → Cursor or Claude Code → External stub. Seat **essential desks** (Developer + Sales/Marketing or Support) on harness and/or Inference+catalog. Keep thin HITL alive; deepen approvals after 1–2 harnesses. Human seats = [IDE_FIRST.md](./IDE_FIRST.md) **v2**.

Upstream feature parity (full OpenCode router UI, Cursor IDE chrome) is **out of scope**. Passthrough or “open in product.”

---

## 6. Cursor SDK notes (coding harness)

| Capability | SDK today | Office use |
| --- | --- | --- |
| `mode: "agent"` \| `"plan"` | On `create` and per-`send` | Desk **default** + rare per-send override |
| `mode: "ask"` | **Not** first-class in SDK | Prefer office Q&A; don’t fake Ask in chat |
| Native tools | Worker runs | After `send(envelope + pack)` |
| Hooks | File-based | Adapter/policy; blocks → Approvals |
| HITL headless | No IDE prompts | Office board + `_locked` (catalog-only; wrapper wait) + hooks/sandbox (natives) |

BYO keys — [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) Runtime & ToS.

---

## 7. UX: modes, pack cut, hooks — don’t cockpit the chat

| Control | Where | Not where |
| --- | --- | --- |
| Conversation mode | Desk default / ⋯ override | Permanent Ask/Plan/Agent bar |
| Pack depth | Desk Memory + pill | Composer formula editor |
| Stack hooks | Adapter / policy files | Chat checkboxes |
| Approvals | Approval board | Inline with Stacks cards |

---

## 8. Stack hooks vs office policy

| Kind | Example | Lives in |
| --- | --- | --- |
| **Stack hooks** | Gate `npm publish` | Cursor hooks / harness |
| **Connect hooks (human seats)** | Git/CI → WorkPacket | [IDE_FIRST.md](./IDE_FIRST.md) |
| **Office policy** | Require Jira ticket | Orchestrator |

### 8.1 Catalog HITL (`_locked`) vs harness natives

Gate is the **capability path**, not the string `_locked`. Office never injects the real MCP id into the agent tool list — only `*_locked`. Detail: [ORCHESTRATOR.md §7.2–7.3](./ORCHESTRATOR.md#72-hil-policy-on-the-catalog-item-admin).

| Runtime | `_locked` intercept? |
| --- | --- |
| **Inference** (office owns the tool list) | **100%.** Model can only call listed tools. |
| **Harness** + catalog action with **no native twin** (e.g. send WhatsApp) | **Same as inference** — they must hit `*_locked` → card → grant. |
| **Harness** + **native twin** (fs, shell, git, browser, extra MCP in the product) or **leaked creds** (`.env`, gold, prompt) | **Not gated.** They skip `_locked`. Use **stack hooks / sandbox**. |

```text
  *_locked → orchestrator card → grant → real MCP     ← catalog-only (WhatsApp, niche CRM, …)
  Shell / curl / browser + token / harness MCP        ← bypass; hooks, not _locked
```

Do **not** market: “every OpenCode/Cursor tool call returns to the orchestrator.”  
Do market: “Inference HITL is complete. Harness HITL is complete for **catalog-only** capabilities.”

**Elevation** (`hil_timer_hours`): temporarily Direct on that catalog item, then snap back. Recycle the harness TTL session at window start/end or a live loop keeps the old tool list. Elevation does **not** bypass hard floors (publish / mass send / prod).

### 8.2 Low autonomy on harness desks (Cursor / OpenCode)

Low `effective` autonomy is a **policy bundle** the adapter applies at `agent.start` / session bind — not a prompt the model invents. Cursor still owns fs/shell/git; the slider alone does **not** turn those off.

| Layer | Who owns it | Low band (e.g. 0–20) |
| --- | --- | --- |
| **Office catalog** | Orchestrator | `follow_autonomy` / `always` → inject `*_locked` only. HITL = card → grant. Wrapper **blocks** with internal exp backoff ([ORCHESTRATOR.md §7.3](./ORCHESTRATOR.md#73-two-pools-direct-vs-gated-_locked)). |
| **Harness natives** | Cursor / OpenCode loop | Unchanged unless **hooks / sandbox / mode**. Soft envelope tells the model to wait on humans for edits/push/publish — **can mistake**. |
| **MEMORY** | Orchestrator after run | Almost all OKF writes → MEMORY cards (complete). |
| **Sampling** | Often not controllable on BYO harness | Do not rely on “be more careful.” |

**Adapter maps `effective` → hook / sandbox profile (example):**

| Band | Cursor hooks / sandbox |
| --- | --- |
| **0–20** | Deny or HITL: `npm publish`, `git push` (esp. main), prod kubectl, broad `curl`, global installs; keep work under `workspace.path` |
| **40–60** | HITL publish/prod; allow local commit, test, PR to non-main |
| **80–100** | Allowlist grows; hard floors remain |

Hook **block** → same **Approvals** board as MCP HITL. Recycle TTL session when autonomy changes mid-desk.

**Soft prompt is required** (Office Envelope): autonomy applies to **everything** as instruction — including code change, commit, push — so natives without a twin still get guidance. Pair with hooks for what must not fail.

| Say | Don’t say |
| --- | --- |
| “At 15 the desk is **instructed** to wait on humans for code and sends; catalog + memory + hooks **enforce** what we can.” | “At 15 Cursor **cannot** change code without approval.” |
| “Soft prompt covers natives we don’t intercept; mistakes possible.” | Prompt-only HITL for WhatsApp / catalog sends |

```text
effective = 15
  → *_locked for follow_autonomy catalog
  → MEMORY HITL-heavy
  → strict hook profile (if shipped)
  → envelope: wait on humans for edit/push/publish/send; call *_locked and wait
  → optional mode: plan (UX, not a sandbox)
```

---

## 9. Guardrails catalog (reminder)

Four kinds — [ORCHESTRATOR.md](./ORCHESTRATOR.md) §7: **MCP · Tools · Skills · External tools**.

| Catalog | Not catalog |
| --- | --- |
| **Tools** = light office desk functions (`gold.read` / `gold.update`; default-inherit agent desks) | Orchestrator spine (OKF extract, office Q&A, pack) |
| **External tools** = HTTP APIs only (Firecrawl, …) | MCP servers (those are **MCP**) |
| Skills = playbooks | **External agent** Stacks kind (MCP/A2A peer) |
| | Native harness fs/shell/git — hooks, not a fifth kind |

UI: **Guardrails** tab (policy + catalog). **Approvals** = HITL inbox. **Stacks** = connections.

---

## 10. Suggested layout

```text
adapters/
  opencode/          # v1 first harness
  cursor/
  claude_code/
  openai_compat/     # inference
bridges/
  mcp_a2a/           # external agents (later)
```

---

## 11. OpenCode slice A (shipped `0.3.0`)

First harness implementation. Full coding note: [architecture/18_OPENCODE.md](./architecture/18_OPENCODE.md).

### SemVer

- **0.3.0** — OpenCode slice A  
- **0.3.1** — Stacks connections  
- **0.3.2** — Runtime registry / idle TTL  
- **0.3.3** — OpenCode registered models (below)  
- **0.3.x** — further minors on the same line  

### Decisions (slice A)

| Topic | Choice |
| --- | --- |
| Serve lifecycle | AAS spawns/supervises `opencode serve` (never user-global serve) |
| Serve key (`0.3.2+`) | **`(connection_id, workspace.path)`** — one serve; users/desks isolated by `ses_…` |
| Docker | OpenCode **CLI in orchestrator image** — **not** a Compose `opencode` service |
| SDK | Official **`opencode_ai`** / **`AsyncOpencode`**; nested `extra_body.model` required |
| Slice A | Chat + thinking; permission auto-`once`; no question UI |
| Pack / OKF / thinking | Unchanged rules in [18_OPENCODE.md](./architecture/18_OPENCODE.md) |

---

## 12. OpenCode registered models (shipped `0.3.3`)

| Topic | Choice |
| --- | --- |
| Two catalogs | Inference **verified** vs OpenCode **registered** — desk OpenCode dropdown = registered only |
| Defaults | **No** auto-link of Inference models onto OpenCode |
| Soft “Models via” only | **No** — AAS must inject provider config on serve from Inference secretRef / base_url |
| Test & register | Same path as chat: `ensure_serve` → inject → `session.chat` + `/event`. **Pass** = ≥1 assistant token then `session.idle`. Refuse if Inference Test is already `error` |
| Desk chat idle | Ignore `session.idle` until `session.chat` is in flight; journal `error` if the turn ends with no tokens (`0.3.5`) |
| Discover pair | Try candidates (CLI models list + known provider names); **persist first success** — do not guess forever |
| Agent UI | Connection (OpenCode) + flat model list only — no Bedrock vs Ollama picker |
| Cursor in Create UI | **Keep out** until real adapter |
| Seed rename | With this cut: prefer `oc-local` / `ollama-local` / `bed-prod` with aliases from `opencode` / `ollama` / `bedrock` |

### Layout reminder

```text
adapters/opencode/   # serve.py · runtime.py · events.py · adapter.py · providers.py (0.3.3)
```

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-11 | Initial: worker-stack strategy; TTL desk session; core vs adapters |
| 2026-08-11 | Link IDE_FIRST |
| 2026-08-12 | Human seats / WorkPacket hooks |
| 2026-08-12 | Three kinds (Inference / Harness / External); Stacks tab UX; OpenCode-first queue; other axes |
| 2026-08-12 | Desks hero / few kinds; any-stack feasibility; Inference+catalog compose; UI≠adapter; coding wedge |
| 2026-08-14 | §8.1 `_locked` guarantee: Inference 100%; harness iff no native twin; elevation + session recycle |
| 2026-08-14 | §9 Guardrails four kinds; External tools ≠ External agent ≠ Tools |
| 2026-08-14 | §8.2 low-autonomy harness bundle: soft prompt + hooks + `_locked` wait |
| 2026-08-16 | §11 OpenCode slice A: AAS-managed serve per workdir; thinking store; no OKF from thinking; AsyncOpencode + big-pickle default |
| 2026-08-16 | OpenCode slice A target SemVer **0.3.0**; single-line fixes on 0.3.x after cut |
| 2026-08-16 | OpenCode: CLI in orchestrator image (not Compose service); later autonomy gates permissions but grant=`once`; slice C = question UI |
| 2026-08-17 | §3 / §12: connection_id vs stack vs model; serve key (connection, cwd); two catalogs; Test & register hard-wire; Cursor out of UI; rename aliases in 0.3.3 |
| 2026-08-18 | §12 Test & register: wait for assistant tokens + session.idle; refuse if Inference Test is error (`0.3.4`) |
| 2026-08-18 | Desk OpenCode chat: ignore empty `session.idle` before `session.chat`; journal `error` if no tokens (`0.3.5`) |
| 2026-08-18 | Bedrock auth: IAM access key + secret **or** Bedrock API key + region (`0.3.6`) |
| 2026-08-18 | OpenCode thinking: match `sessionID` on event envelope; harvest reasoning parts after idle (`0.3.7`) |

