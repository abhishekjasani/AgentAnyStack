# AgentAnyStack — Open Source & Market Research

Research notes for releasing the product as open source with Community + Enterprise tiers (Appsmith-style), including commercial competitors and GitHub / OSS landscape.

**Product name (working):** [AgentAnyStack](./PRODUCT_OVERVIEW.md) — *Any stack. One orchestrator.*  
**Build / stack decisions:** [IMPLEMENTATION.md](./IMPLEMENTATION.md) (Python orchestrator; Apache-2.0 CE intent)  
**Last updated:** 2026-08-03  
**Status:** Research only — not a product commitment.

> Coverage note: This is **not** an exhaustive crawl of every GitHub repo. Discovery used web/market roundups, product sites, and curated lists such as [awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators). Treat that list as a living index.

---

## 0. Naming & ToS (short update)

| Topic | Decision / note |
| --- | --- |
| **Public brand** | Prefer **AgentAnyStack** over “Agent Office” (name collision with pixel sims) |
| **Availability (2026-07)** | Exact `agent-anystack` looked free on GitHub/npm/PyPI; near-collision: **AgentStack** |
| **License intent** | CE = Apache-2.0; EE = commercial |
| **Cursor** | Official SDK + API key + workers = intended path |
| **Claude** | Prefer **API key / commercial terms**. Orchestrating Claude via Pro/Max OAuth as a third-party harness is ToS-risk — don’t market consumer CLI wrapping as “not automation” |

Full product thesis: [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md).

---

## 1. Positioning snapshot

**Today (prototype):** self-hostable control plane — chat grammar (`Analyst:` / `Developer:` / `Tester:`), office desks + expressions, live activity, gold memory, orchestrator API/WS, Cursor **My Machines** workers.

**Target:** multi-stack aggregator — team → floor → org scopes (floor **connect lines** for gated cross-team share; office nesting deferred), org/persona memory, adapters for Cursor / Claude / others, create·manage·explain UX.

| Layer | Crowded with | Your wedge |
| --- | --- | --- |
| Pixel “virtual office” UIs | pixel-agents, agent-office forks | Visual desks are only part of the product |
| Coding-agent harnesses | Devin, Factory, Tembo, Cursor Cloud, Amp | Orchestration + integration, not “best SWE agent” |
| Enterprise agent control planes | IBM watsonx, Lyzr, Omnithium | Coding-capable floors + operator UX |
| Open-core app platforms | Appsmith, Dify, n8n | **Business-model** comps more than feature twins |

**Name collision:** Avoid public brand **Agent Office** / AgentVerse / AgentNest / AgentSuite / AgentNexus / AgentBridge / AgentOpenWork.

---

## 2. Business & license models (Appsmith-like options)

| Model | How it works | Examples | Fit for Agent Office |
| --- | --- | --- | --- |
| **Open core** | Permissive OSS core; SSO/RBAC/audit/branding = paid | Appsmith, GitLab, Mattermost, n8n | **Best match** to Community + Enterprise |
| **Modified Apache / fair code** | Free internal use; block multi-tenant SaaS / logo strip without commercial license | Dify | Strong if cloud vendors might wrap you |
| **AGPL + commercial dual license** | Free under AGPL; pay to embed/host without copyleft | Grafana-style patterns | Anti-hosting shield; some enterprises dislike AGPL |
| **Source-available (BSL/SSPL)** | Visible source, not always “open source” | Elastic / HashiCorp-era patterns | Control + community friction |
| **Fully OSS + paid cloud only** | All code free; money = hosted SaaS + support | Supabase-ish, many indie tools | Max adoption; harder EE edition story |
| **Support / services only** | All free; sell SLAs and professional services | Classic Red Hat | Weak alone for control planes |
| **Triple stack (common winner)** | Free self-host CE + managed Cloud + Enterprise features | Appsmith, Dify, OpenHands, PostHog, n8n | Likely end state |

### Appsmith reference (CE / Business / Enterprise)

- **Community:** Apache 2.0, self-host, no user cap, no license fee for core.
- **Business / Enterprise:** SSO/SCIM, audit, custom roles, support — often via license key even when self-hosted.
- **Cloud:** Free tier with caps; paid seats for team/enterprise features.

### Typical CE vs EE feature gates

**Community (self-host, free)**

- Chat + desks + role routing
- Local / self-hosted workers
- Basic auth (shared token / simple login)
- Single org / workspace
- Gold memory, activity feed
- Docker Compose

**Business / Team**

- Multi-user seats, invites
- Multiple chats / workspaces
- Usage / cost dashboards
- Slack / GitHub integrations
- Priority support

**Enterprise**

- SAML/OIDC SSO, SCIM
- Audit logs, retention
- Fine RBAC (who can run Developer vs reset Tester)
- Secrets vault / per-agent credentials
- HA / multi-tenant (if selling hosted)
- White-label / remove branding
- Air-gapped / VPC + SLA
- Compliance packs (SOC2 access)

**Agent-specific paid wedges**

- Multi-repo / multi-team fleets
- Approval gates before Developer runs
- Policy engine (allowlisted tools/paths)
- Eval / replay / quality dashboards
- Bring-your-own runtime (Claude Code, Codex, OpenHands — not only Cursor)
- Seat or **run-minute** billing on managed cloud

### License notes specific to Agent Office

Users still need a **Cursor API key / quota** unless you diversify runtimes. That is a product dependency, not a license issue. OpenHands-style “any ACP agent” is how peers reduce lock-in for Enterprise.

---

## 3. Commercial landscape

### 3.1 Coding agents / SWE fleets

| Product | Commercial model | What it is |
| --- | --- | --- |
| **Devin (Cognition)** | SaaS / Enterprise, usage (ACU) | Autonomous SWE; can spawn managed Devins |
| **Factory.ai** | SaaS + Enterprise | Coordinator + “droids”; ticket → PR pipelines |
| **Tembo** | Cloud + self-host | Orchestrates Claude Code / Cursor / Codex in cloud VMs |
| **Cursor Cloud Agents** | Subscription + usage | Background agents inside Cursor |
| **OpenAI Codex Cloud** | Token / Plus | Parallel background coding agents |
| **GitHub Copilot coding agent** | GitHub seats + credits | Async PR agent in GitHub |
| **Google Jules** | Bundled with Google AI plans | GitHub-native async PRs |
| **Sourcegraph Amp** | Commercial | Agents in remote “orbs”; agents can spawn agents |
| **Codegen** | Commercial / usage | Slack / Linear → agents |
| **OpenHands Cloud / Enterprise** | OSS core + paid control plane | Coding agents + enterprise fleet / governance layer |

### 3.2 Enterprise agent control planes (governance-first)

| Product | Focus |
| --- | --- |
| **IBM watsonx Orchestrate** | Cross-vendor agent control plane |
| **Lyzr Control Plane** | Govern agents across LangGraph, CrewAI, Bedrock, etc. |
| **Omnithium** | Enterprise agentic control plane (orchestration + governance + tracing) |
| **Salesforce Agentforce** | CRM-native agents (Flex Credits or per-conversation pricing) |
| **Microsoft Copilot Studio** | M365 / Power Platform agents |
| **Ema.ai** | “AI employees” for HR / CX / Finance (enterprise pricing; marketplace listings from ~$10k/mo) |
| **Rasa** | Enterprise conversational + multi-agent runtime |
| **CrewAI Enterprise / AMP / Factory** | OSS framework + paid cloud / SSO / VPC |

### 3.3 Open-core platforms (business-model comps)

| Product | License / model |
| --- | --- |
| **Appsmith** | Apache CE + Business / Enterprise |
| **Dify** | Modified Apache + Enterprise (restricts multi-tenant SaaS / logo removal without deal) |
| **n8n** | Fair-code + Cloud / Enterprise |
| **ToolJet** | Open-core internal tools |
| **Langfuse** | OSS + Cloud / Enterprise observability |

---

## 4. Open source / GitHub landscape

### 4.0 Are there repos similar to *this* project?

**Short answer:** Yes, there are neighbors — but almost none match the **full** Agent Office stack.

What Agent Office uniquely combines today:

| Piece | This project (`cursor_teams`) |
| --- | --- |
| Web app | Chat + office desks UI (browser) |
| Control plane | Self-hosted Fastify orchestrator + WebSocket |
| Command grammar | `Analyst:` / `Developer:` / `Tester:` / `reset` / `remember:` |
| Runtime | Cursor SDK + **My Machines** self-hosted workers |
| Config | YAML agents, prompts, gold memory |
| Deploy | Docker office + host-side workers (EC2) |
| Purpose | Route real coding/research work through Cursor agents |

#### First Google hit: [harishkotra/agent-office](https://github.com/harishkotra/agent-office) (~195★)

**Same brand words (“Agent Office”, desks, activity). Different product.**

| | **harishkotra/agent-office** | **This project** |
| --- | --- | --- |
| What it is | Pixel-art **simulation** of agents in an office | **Control plane** for real Cursor coding agents |
| LLM | Local Ollama / OpenAI-compatible | Cursor SDK (Composer / frontier via Cursor) |
| Agents do | Think loops, walk to desks, talk, hire interns, sandbox JS | Real repo work via My Machines workers |
| UI | Phaser.js game + React overlay | Chat half + office desks (expressions, live activity) |
| Memory | SQLite + Ollama embeddings | Gold memory markdown + chat transcripts |
| Sync | Colyseus game rooms | Fastify API + WebSocket |
| Lock-in | “Zero lock-in” (any OpenAI-compatible API) | Cursor API key + workers |
| Inspired by | [pixel-agents](https://github.com/pablodelucca/pixel-agents) | Morfgage / Cursor self-hosted agents |

Treat Google “agent office” results as **name collision**, not competitors for your architecture — unless you also want a pixel simulation layer.

Most other GitHub “similars” only overlap **1–2** pieces:

| Overlap type | Examples | What’s missing vs this project |
| --- | --- | --- |
| **Closest overall** | [submato/ai-team](https://github.com/submato/ai-team) | Cursor SDK + multi-agent UI, but **desktop/Electron + kanban**, not web office + machine workers |
| Visual office / sim | harishkotra/agent-office, pixel-agents, agent-virtual-office | Characters/desks; **no** Cursor ChatOps control plane |
| Cursor orchestration inside Cursor | MCP orchestrators, KS-Cursor-Orchestrator, cursor/plugins orchestrate | Runs **inside Cursor chat/MCP**, not a standalone office product |
| Multi-CLI harness | agent-orchestrator, thurbox, agentsmesh | Parallel terminals/worktrees; usually **not** Cursor SDK office + role chat |
| Config packs | Prathmesh2000/cursor_agent-orchestrator | Rules/skills/roles inside the IDE — **not** a deployable server |

So: **similar names and metaphors exist; a near-clone of this architecture is rare.** For OSS, pick a distinct public name so you don’t lose SEO to pixel sims.

### 4.1 Same metaphor (“office / desks / characters”)

Mostly **visual monitors / simulations**, not full ChatOps control planes.

| Project | Notes |
| --- | --- |
| **pixel-agents** ([pixel-agents-hq/pixel-agents](https://github.com/pixel-agents-hq/pixel-agents)) | VS Code extension + CLI pixel office |
| **KbWen/agent-virtual-office** | Browser pixel coworkers (Claude / Codex / Gemini) |
| **Agent-Office** (e.g. quisumego / DebisLimbuHub variants) | Pixel office + Codex / Claude backends |
| **falkoro/agent-office** | Observes local CLIs in a shared office UI |
| **claw-empire / Star-Office-UI / openclaw-office** | OpenClaw ecosystem virtual offices |
| **keshrath/agent-desk** | Electron control center (terminals + dashboards) |

### 4.2 Multi-agent harness / IDE orchestrators

| Project | Notes |
| --- | --- |
| **AgentWrapper/agent-orchestrator** | Parallel agents, worktrees, CI feedback loops |
| **Composio agent-orchestrator** | Parallel coding agents |
| **thurbox, nimbalyst, jean, parallel-code, Proliferate** | Multi-session / worktree orchestrators |
| **agentsmesh** | Remote AgentPods + Kanban |
| **agent-teams-ai** | Desktop multi-provider agent teams |
| **submato/ai-team** | Cursor SDK + CEO chat + kanban (close feature neighbor) |
| **Cursor MCP orchestrators** | Propose / confirm / execute multi-agent from Cursor chat |

Living index: [andyrewlee/awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators).

### 4.3 Frameworks (infra, not “office”)

LangGraph, CrewAI, AutoGen, Semantic Kernel, OpenHands SDK, and similar — orchestration libraries rather than office UX products.

---

## 5. Where Agent Office sits

```
Visual office UIs (pixel-agents, agent-office forks)
        ↑ overlap: desks, expressions, live status
Agent Office: chat + desks + role agents + self-hosted workers + Cursor SDK
        ↑ overlap: multi-agent SWE coordination
Harnesses (AO, Tembo, Factory, Devin, OpenHands Control Plane)
        ↑ overlap: enterprise governance
Control planes (Lyzr, watsonx, Omnithium) — usually not coding-desk-first
```

**Narrow wedge:** self-hostable **Agent Office control plane** (chat grammar, desks, activity, My Machines workers, gold memory) — between cute visualizers and full Devin/Factory SaaS.

---

## 6. Go-to-market options (for you)

| Path | Examples | Pros | Cons |
| --- | --- | --- | --- |
| Open core CE + EE | Appsmith, Dify, OpenHands | Clear community story | Must build EE features enterprises buy |
| Fully commercial SaaS | Devin, Factory, Tembo | Faster revenue | Weak “open source community” narrative |
| OSS + managed cloud only | Many indie tools | Max forks | Easy for clouds to host you |
| Marketplace / OEM | Ema on Azure, Agentforce partners | Distribution | Less brand ownership |
| Framework + EE cloud | CrewAI | Dev adoption | Commodity unless UX is unique |

### Practical recommendation (research opinion)

1. **Open core** — Apache 2.0 (or Dify-style modified Apache) for office UI + orchestrator.
2. **Enterprise proprietary module** — SSO, audit, RBAC, multi-tenant, policies.
3. **Optional Cloud** — hosted office + workers; charge per seat or per agent-run.
4. Position against **OpenHands Control Plane** (fleet ops) and **AI Team / Tembo** (multi-agent coding UX), not against Dify workflow builders.
5. Diversify beyond Cursor for Enterprise (ACP / Claude Code / Codex adapters) to reduce single-vendor risk.

---

## 7. Suggested competitive matrix (next pass)

Axes to score later (1–5) for Agent Office vs Tembo vs OpenHands vs pixel-agents vs AI Team vs Devin vs Factory:

1. Self-hostable control plane  
2. Visual office / desks UX  
3. Role-based multi-agent chat  
4. Runtime agnostic (not Cursor-only)  
5. Worker / VM isolation  
6. Enterprise SSO / audit / RBAC  
7. Ticket / Slack / Linear intake  
8. Open-source license clarity  
9. Managed cloud offering  
10. Pricing transparency  

---

## 8. Sources (sampled)

- Appsmith pricing / open-source positioning  
- Dify license (modified Apache 2.0) and Enterprise packaging  
- OpenHands Agent Control Plane / Agent Canvas announcements  
- Commercial coding agents: Devin, Factory, Tembo, Cursor, Codex, Amp, Copilot, Jules  
- Enterprise control planes: IBM watsonx Orchestrate, Lyzr, Omnithium, Agentforce, Copilot Studio, Ema, CrewAI  
- GitHub / lists: awesome-agent-orchestrators, pixel-agents, agent-virtual-office, agent-desk, ai-team  

---

## 9. Changelog

| Date | Change |
| --- | --- |
| 2026-08-03 | Link IMPLEMENTATION.md; Python orchestrator + Apache-2.0 CE still preferred |
| 2026-08-02 | Target hierarchy: team → floor → org; floor connect lines; office nesting deferred |
| 2026-07-29 | Rename framing to AgentAnyStack; §0 naming/ToS; link PRODUCT_OVERVIEW |
| 2026-07-21 | Initial research doc: models, commercial, OSS, positioning |
| 2026-08-03 | Link IMPLEMENTATION.md; Python orchestrator + Apache-2.0 CE still preferred |
