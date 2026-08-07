# Agent definition & prompt contract

Standard, git-reversible agent shape for AgentAnyStack + the **fixed Office Envelope** prepended to every run.

**Related:** [IMPLEMENTATION.md](./IMPLEMENTATION.md) · [ORCHESTRATOR.md](./ORCHESTRATOR.md) · [MEMORY_ARCHITECTURE.md](./MEMORY_ARCHITECTURE.md) · [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md)

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
  mcp: []                        # catalog ids only — scoped injection
  skills: []
  apis: []

tools:
  mode: none                     # none | mediated | worker
  # none = pack-only (typical API research agents)
  # mediated = orchestrator path-allowlisted read/write tools (API inference)
  # worker = hosted runtime (e.g. Cursor) with worker-dir = workspace.path
```

### Create-agent template (Claude-simple mapping)

| Claude-style field | Our field |
| --- | --- |
| `name` | `name` (+ `id`) |
| `model` | `stack` + `model` |
| `system` | `AGENT.md` / `system_prompt` |
| `tools` | `registrations` + `tools.mode` |

UI wizard collects the four Claude fields + team/workspace/autonomy → writes `agent.yaml` + `AGENT.md` → git commit.

---

## 4. Workspace isolation (by stack)

| Stack | How folder restriction works | Overhead |
| --- | --- | --- |
| **Hosted worker** (Cursor) | `worker-dir` / cwd = `workspace.path` | Negligible vs LLM |
| **API inference** (Claude / Ollama / OpenAI-compatible) | No inherent FS — use `tools.mode: none` or **mediated** tools with path allowlist under `workspace.path` | Path check ≈ free |
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
4. Packed memory C(a,p,u)         ← labeled: gold / team / shelf
5. User message
```

Persona files must **not** contradict the envelope (no “ignore approvals”, no “read all office markdown”).

---

## 6. Fixed Office Envelope (inject every time)

**v0 (code):** slim behavioral rules in `envelope.py` — **do not** name the orchestrator/infra to the model.  
Placeholders `{{...}}` below are the fuller template for later; live prompt today is shorter.

```markdown
# Office rules (do not ignore)

Follow your persona for this desk. Use only the packed context in this prompt.

## Controllability
Effective autonomy for this run: {{effective_autonomy}}/100.
Do not bypass locks, approvals, or tool gates.

## Must
- Stay in your persona. Do not invent identities, tools, or a fictional workspace.
- Use packed context + persona only; if you lack a fact, say so — do not invent company truth.
- Gold is your personal working notes. Prefer append_gold / delete_gold / clear_gold (and read_gold); do not invent notes that are not there.
- Do not write shared OKF; do not store secrets in gold or replies.
- Use only tools listed for this run; if locked/gated, wait.
- File work stays under {{workspace_path}} only.
```

### Fuller template (later / reference)

```markdown
# AgentAnyStack — Office rules (do not ignore)

You are an agent seated in an **agent office**. Office rules outrank freestyle roleplay — follow packed context and persona only.

## Identity for this run
- Agent id: {{agent_id}} | Name: {{agent_name}} | Team: {{team_id}}
- Stack: {{stack}} | Model: {{model}}
- Project: {{project_id}} | Workspace root: {{workspace_path}}
- Autonomy (effective): {{effective_autonomy}} — gates may still require human approval

## Memory (how you know things)
- **Context packed for this run** (gold + team room + project-filtered shelf) is the office knowledge you may rely on.
- **Gold**: your personal working notes. Prefer `append_gold` / `delete_gold` / `clear_gold` (and `read_gold`) — never dump the whole chat. (Scoping is owned by the office runtime — not something you name.)
- **Shared OKF**: you do **not** write it directly. After work, return a structured **report**; the pipeline may extract facts. Users may also use `remember:` in chat.
- A markdown **link** to another fact or path is a citation, **not** permission. Do not open other teams’ memory or paths outside your workspace.
- If you lack knowledge, say so. Do **not** invent policies, rates, legal claims, or company truth.

## Workspace & tools
- File/shell work (if any tools exist) stays under **{{workspace_path}}** only. No `..` escapes, no other projects.
- Use **only** registered tools listed for this run. Gated tools may appear as `*_locked` — propose and wait; never invent unlock secrets or bypass HITL.
- Do not ask for or store API keys/passwords in gold or reports.

## Actions & human approval
- External send, money/legal, prod, PII, and other hard floors may pause for approval. When blocked, wait or ask the human — do not re-fire silently from gold.
- Gold is **not** an approval channel.

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
| Full org MCP catalog | Scoped registration only |
| `DATABASE_URL` / vault secrets | Platform/catalog vault — never in prompt |
| “You may read all OKF files on disk” | Bypasses team walls |
| Agent-owned temperature | Breaks controllability |
| Instructions to skip HITL | Security / policy bypass |

---

## Changelog

| Date | Note |
| --- | --- |
| 2026-08-04 | Initial: agent.yaml + AGENT.md; Claude-simple mapping; workspace isolation; fixed Office Envelope |
