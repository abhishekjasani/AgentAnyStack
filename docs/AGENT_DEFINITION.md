# Agent definition & prompt contract

Standard, git-reversible agent shape for AgentAnyStack + the **fixed Office Envelope** prepended to every run.

**Related:** [IMPLEMENTATION.md](./IMPLEMENTATION.md) · [ORCHESTRATOR.md](./ORCHESTRATOR.md) · [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) · [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) · [STACK_ADAPTERS.md](./STACK_ADAPTERS.md)

---

## 1. Design goals

- **Claude-simple create UX:** name, model, system/persona, tools — few core fields.
- **Office extensions:** team, stack, persona axes, autonomy, workspace/project, registrations.
- **Git-reversible:** YAML + markdown in the office repo; UI save = commit; revert = restore desk.
- **Prompt split:** fixed **Office Envelope** (orchestrator) + per-desk **`AGENT.md`** (persona).

---

## 2. On-disk layout (per agent)

```text
office/teams/<team-id>/agents/<agent-id>/
  agent.yaml          # machine contract
  AGENT.md            # persona / system prompt (human-editable)
  gold/<user_id>.md   # per-user notepad (runtime)
```

---

## 3. `agent.yaml` schema (v0)

```yaml
id: developer
name: Developer
team: eng

stack: cursor                    # cursor | claude | openai-compatible
model: composer-2.5              # stack-specific model id

persona:
  domain: eng                    # eng | sales | support | legal | ba | ...
  channels: [git, shell]         # descriptive side-effect surfaces
  risk_class: system_write       # read_draft | system_write | external_send | money_legal_pii

autonomy:
  default: 50
  max: 70                        # must be ≤ org.max_autonomy

workspace:
  project_id: loan-portal-01H8   # immutable registry id; derives run.project
  path: /work/loan-portal        # only tree tools may touch (no office/memory FS)
  # optional later:
  # allow_globs: ["src/**", "docs/**"]
  # deny_globs: ["secrets/**", ".env"]

system_prompt_file: ./AGENT.md   # preferred for long personas
# system_prompt: "..."           # optional inline for tiny agents

registrations:
  mcp: []                        # Guardrails catalog ids — scoped injection
  tools: []                      # extra Tools; gold.read/update default-inherit agent desks
  skills: []
  external_tools: []             # HTTP APIs (Firecrawl, …) — not MCP

tools:
  mode: none                     # none | mediated | worker
  # none = pack-only (typical API research / sales / support desks)
  # mediated = thin allowlisted tools or MCP — extras only; NOT a full coding harness
  # worker = Cursor / Claude Code / OpenCode — native tools in workspace.path
  # Coding desks: prefer worker stacks. See STACK_ADAPTERS.md
```

### Create-agent template (Claude-simple mapping)

| Claude-style field | Our field |
| --- | --- |
| `name` | `name` (+ `id`) |
| `model` | `stack` + `model` |
| `system` | `AGENT.md` / `system_prompt` |
| `tools` | `registrations` + `tools.mode` (Guardrails Tools ≠ `tools.mode`) |

UI wizard collects the four Claude fields + team/workspace/autonomy → writes `agent.yaml` + `AGENT.md` → git commit.

**Optional desk defaults (advanced — not chat chrome):** conversation `mode` for worker stacks (`agent` \| `plan` where SDK supports it); **pack depth** (`full` \| `gold+team` \| `gold`); office **policy** refs (e.g. `require_work_item: jira`). See [STACK_ADAPTERS.md](./STACK_ADAPTERS.md) §5–6.

**Human seats** (`seat_kind: human`): no `stack` / `model` / autonomy / gold — IDE users BYO Cursor/Claude; office = pack + WorkPacket sync + MEMORY HITL only. No `gold.*` Tools. See [IDE_FIRST.md](./IDE_FIRST.md).

---

## 4. Workspace isolation (by stack)

| Stack | How folder restriction works | Overhead |
| --- | --- | --- |
| **Hosted worker** (Cursor / Claude Code / OpenCode) | `worker-dir` / cwd = `workspace.path`; **native stack tools** | Negligible vs LLM |
| **API inference** (Bedrock / Ollama / OpenAI-compatible) | No inherent FS — `tools.mode: none` or light MCP; do **not** expect Cursor-class coding | Path check ≈ free |
| **Same FastAPI event loop** | Do **not** expect Linux chroot per asyncio task | N/A — isolate at worker/tool boundary |

Path allowlist: resolve paths; reject escapes outside `workspace.path`.  
Cross-team **same project** sharing the same path is intentional; team OKF isolation stays in packing, not chroot.

Agents must **not** mount or browse `office/memory/` export trees.

---

## 5. Prompt assembly order (every run)

```text
1. Fixed Office Envelope          ← orchestrator template (this doc §6)
2. Persona AGENT.md               ← desk-specific
3. Registered tools schema        ← scoped only
4. Packed memory C(a,p,u)         ← labeled: Recent thread · gold · team · shelf
5. User message
```

Persona files must **not** contradict the envelope (no “ignore approvals”, no “read all office markdown”).

Soft orchestrator jobs (OKF extract, office Q&A, optional thread summarize) use **`OFFICE_MODEL`**, not the desk `model`. HITL stays deterministic.

---

## 6. Fixed Office Envelope (inject every time)

Placeholders `{{...}}` filled by orchestrator per run.

```markdown
# AgentAnyStack — Office rules (do not ignore)

You are an agent seated in an **agent office**. The orchestrator controls memory packing, approvals, and tools. You do not outrank it.

## Identity for this run
- Agent id: {{agent_id}} | Name: {{agent_name}} | Team: {{team_id}}
- User id: {{user_id}} (your notepad is gold for this user only)
- Stack: {{stack}} | Model: {{model}}
- Project: {{project_id}} | Workspace root: {{workspace_path}}
- Autonomy (effective): {{effective_autonomy}} — gates may still require human approval
- Autonomy applies to **all** side effects (catalog sends **and** file/shell/git when those tools exist). At **low** bands: prefer plan / ask the human before edit, commit, push, publish, or external send. Soft instruction — do not invent unlocks or bypass `*_locked`.

## Memory (how you know things)
- **Recent thread** (or summary) is short-lived chat continuity for this user — not gold and not shared OKF.
- **Gold + team room + project-filtered shelf** is the office knowledge you may rely on.
- **Gold**: short-term notes for (you, this user). Read/update via Tools `gold.read` / `gold.update`. Durable bullets only — never dump the whole chat.
- **Shared OKF**: you do **not** write it directly. After work, return a structured **report**; the pipeline may extract facts. Users may also use `remember:` in chat.
- A markdown **link** to another fact or path is a citation, **not** permission. Do not open other teams’ memory or paths outside your workspace.
- If you lack knowledge, say so. Do **not** invent policies, rates, legal claims, or company truth.

## Workspace & tools
- File/shell work (if any tools exist) stays under **{{workspace_path}}** only. No `..` escapes, no other projects.
- Use **only** registered tools listed for this run. Gated tools appear as `*_locked` (never the real MCP name) — call once and **wait** for the tool result (office may pause for human approval). Never invent unlock secrets, poll/retry inventively, `curl` around HITL, or use leaked creds.
- Do not ask for or store API keys/passwords in gold or reports.

## Actions & human approval
- External send, money/legal, prod, PII, and other hard floors may pause for approval. When a gated tool is in flight, wait for its return — do not re-fire silently from gold or chat.
- At low autonomy, treat code changes and irreversible git/shell the same way: confirm with the human when unsure. Gold is **not** an approval channel.

## How you work
- Follow your **persona** section for mission, tone, and output shape.
- Prefer artifacts and packed facts over guesses.
- Be concise unless the persona asks for a template.
- Do not set sampling / “be more creative” overrides — the office owns that.

## Report (end of non-trivial work)
When you finish a substantial task, include:

## Done
## Decisions
## Phase
(plus citations to files/urls/ids you used)
```

---

## 7. `AGENT.md` persona (variable only)

Keep desk-specific content here, for example:

```markdown
# {{name}} — {{one-line role}}

## Mission
…

## Must
…

## Must not
…

## Reply shape (optional)
…
```

No office-wide law duplication unless a temporary override is explicitly product-approved (discouraged).

---

## 8. What not to put in prompts

| Avoid | Why |
| --- | --- |
| Full org Guardrails catalog | Scoped registration only (`gold.*` default-inherit) |
| `DATABASE_URL` / vault secrets | Platform/catalog vault — never in prompt |
| “You may read all OKF files on disk” | Bypasses team walls |
| Agent-owned temperature | Breaks controllability |
| Instructions to skip HITL | Security / policy bypass |
| Real MCP id / unlock secret in prompt | Gated path is `*_locked` + server-side grant only |

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-04 | Initial: agent.yaml + AGENT.md; Claude-simple mapping; workspace isolation; fixed Office Envelope |
| 2026-08-07 | Pack labels include Recent thread; OFFICE_MODEL note for soft jobs |
| 2026-08-11 | Worker stacks preferred for coding; desk defaults for mode/pack; link STACK_ADAPTERS.md |
| 2026-08-12 | Human seats pointer → IDE_FIRST (no gold/autonomy) |
| 2026-08-14 | Envelope: `*_locked` only; do not invent bypass / leaked creds |
| 2026-08-14 | registrations: tools + external_tools; gold.* default-inherit agent desks |
| 2026-08-14 | Envelope: autonomy-for-everything soft guidance; wait on `*_locked` (no model backoff) |
