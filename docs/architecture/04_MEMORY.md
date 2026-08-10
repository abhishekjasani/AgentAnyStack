# Memory

Users share the **room**; they do not share the **notepad**.

```mermaid
flowchart TB
    subgraph short [Short-term]
        G["gold(a,u) jsonl notes in git"]
    end
    subgraph long [Long-term shared]
        T[(Team OKF SQLite)]
        S[(Shelf floor/org OKF)]
    end
    AGENT[Agent tools append/delete/clear gold] -->|mediated write| G
    HUMAN[Human / Memory UI] -->|view only| G
    HUMAN -->|seed facts until extract| T
    RUN[Agent run] -->|pack read| G
    RUN -->|pack read| T
    RUN -->|report only| PIPE[Extract pipeline]
    PIPE -.->|later| T
```

## Pack formula (v0)

```text
C(a,p,u) ≈ gold(a,u) ∪ mem(team)
```

Shelf / floor / org ∩ `P(p)` not packed yet. Team facts are **not** filtered by `created_by_user` (audit label only).

| Tier | Store | Who writes |
| --- | --- | --- |
| Gold | `gold/<user_id>.jsonl` | **Agent** via `read_gold` / `append_gold` / `delete_gold` / `clear_gold` (Memory UI view-only; HTTP PUT for ops) |
| Team OKF | SQLite `okf_facts` (`DATABASE_URL`) | **Human seed** `POST /okf/facts` until extract |
| Shelf | — | Later |

## Modules

| Piece | Path |
| --- | --- |
| Fact model | `memory/fact.py` |
| SQLite store | `memory/store.py` |
| Pack markdown | `memory/pack.py` |
| Extract | `memory/extract.py` — post-run BackgroundTasks |
| HTTP | `api/okf.py` — `GET/POST /okf/facts`, `DELETE` archive |
| Chat | `ChatRunService` packs gold + team OKF; schedules extract on `done` |

`FactType` is only a **category** on a row (`decision`, `fact`, …). The knowledge the model uses is the free-text **`body`** (plus id for citations).

## Example flow: main → route → memory → chat

**Scenario:** Alice seeds “Retail commission is 8%.” for team `eng`, then asks desk `ba` (team `eng`): “What’s our retail commission?”

### A) Seed fact (write)

```http
POST /okf/facts
X-User-Id: alice
{"team":"eng","body":"Retail commission is 8%.","type":"fact"}
```

```mermaid
sequenceDiagram
    participant UI as Memory UI
    participant Main as main.create_app
    participant R as api/okf.create_fact
    participant F as memory.fact.OkfFact
    participant S as memory.store.OkfStore
    participant DB as data/office.db

    Note over Main: include_router(okf_router)
    UI->>R: POST /okf/facts
    R->>F: OkfFact(scope=team:eng, body=..., type=fact, created_by_user=alice)
    R->>S: upsert(fact)
    S->>DB: INSERT okf_facts
    R-->>UI: {id: fact-abc123, ...}
```

### B) Chat packs that fact (read)

```http
POST /agents/ba/chat
X-User-Id: alice
{"message":"What's our retail commission?"}
```

```mermaid
sequenceDiagram
    participant UI as Chat UI
    participant Main as main.create_app
    participant Chat as api/chat.chat
    participant Deps as get_user_id
    participant CRS as ChatRunService
    participant Office as OfficeRepository
    participant OKF as OkfStore
    participant Pack as pack_memory_sections
    participant LLM as OpenAICompatibleAdapter

    Note over Main: include_router(chat_router)
    UI->>Chat: POST /agents/ba/chat
    Chat->>Deps: X-User-Id → alice
    Chat->>CRS: stream_agent_chat(ba, alice, message)
    CRS->>Office: get_agent(ba) → team=eng
    CRS->>Office: read_persona, read_gold(ba,alice)
    CRS->>OKF: list_team_facts("eng")
    OKF-->>CRS: [OkfFact body="Retail commission is 8%."]
    CRS->>Pack: gold + team_facts → markdown sections
    Note over CRS: system = Envelope + AGENT.md + Gold? + Team OKF
    CRS->>LLM: stream_chat(messages)
    LLM-->>CRS: tokens
    CRS-->>UI: SSE token… / done
```

**Team OKF snippet in the system prompt:**

```text
## Team OKF (shared room)
- [fact-abc123] (fact, agnostic, by alice): Retail commission is 8%.
```

(`fact` = type enum; the sentence is `body`.)

### Module map for the example

| Step | Module |
| --- | --- |
| Boot | `main.create_app` registers `okf` + `chat` routers |
| Write fact | `api/okf` → `fact.OkfFact` → `store.OkfStore` |
| Identity | `deps.get_user_id` (`alice`) + path `ba` |
| Orchestrate | `runs/service.ChatRunService` |
| Desk files | `office/repository` (yaml, AGENT.md, gold) |
| Shared facts | `memory/store` |
| Prompt glue | `memory/pack` + `envelope` |
| Model | `adapters/llm.OpenAICompatibleAdapter` |

## Post-run extract (P11)

After a successful chat stream, `api/chat` schedules `BackgroundTasks` → `memory/extract.run_okf_extract` when `okf_extract_enabled` and at least one of `okf_extract_llm` / `okf_extract_remember_lines`. Chat SSE is **not** blocked.

### Example

```http
POST /agents/ba/chat
X-User-Id: alice
{"message":"remember: Retail commission is 8%.\nWhat else should I know?"}
```

Stream returns tokens as usual. After `done`, extract runs in the background and may upsert team OKF (visible on next Memory refresh / next chat pack).

```mermaid
sequenceDiagram
    participant UI as Chat UI
    participant Chat as api/chat.chat
    participant CRS as ChatRunService
    participant LLM as stream_chat
    participant BT as BackgroundTasks
    participant Ext as memory.extract
    participant Comp as complete_chat
    participant DB as OkfStore

    UI->>Chat: POST /agents/ba/chat
    Chat->>CRS: stream_agent_chat(ba, alice, message)
    CRS->>LLM: stream tokens
    LLM-->>CRS: token…
    CRS-->>UI: SSE meta / token…
    Note over CRS: accumulate assistant_text
    CRS->>CRS: journal.append
    CRS-->>Chat: done + ExtractJob (popped before SSE)
    Chat->>BT: add_task(run_okf_extract)
    Chat-->>UI: SSE done
    Note over UI,BT: stream finished — client already has reply
    BT->>Ext: ExtractJob(run_id, team, user, texts…)
    Ext->>Ext: remember: lines (when okf_extract_remember_lines)
    Ext->>Comp: JSON extract prompt (when okf_extract_llm)
    Comp-->>Ext: {"facts":[…]} or error→log
    Ext->>DB: upsert OkfFact(scope=team:eng, source_run, created_by_user)
```

### Who fills what on extract

| Field | Set by |
| --- | --- |
| `body`, proposed `type` | Extractor (LLM JSON) and/or `remember:` line |
| `scope` | Orchestrator → `team:{agent.team}` |
| `created_by_user` | Orchestrator → run `user_id` |
| `source_run` | Orchestrator → `run_id` |
| `id`, `created` | Orchestrator defaults |
| `projects` | Orchestrator → desk `workspace.project_id` if any |

Desk LLM does **not** INSERT into SQLite mid-stream.

### Steps (short)

1. Collect user message + full assistant text during the stream.
2. Deterministic: lines matching `remember: …` in the user message.
3. Soft: one non-streaming LLM call (`complete_chat`) on **`office_model`** (`OFFICE_MODEL`) — extract only, no invent. Not the desk’s `agent.model`.
4. Stamp trusted metadata → `OkfStore.upsert`.

Toggle: `OKF_EXTRACT_ENABLED` (default true). Failures are logged; they do not fail the chat response.

```text
+ OK: extract after SSE completes via BackgroundTasks
- BAD: await long extract inside the token stream
+ OK: remember: line still works if LLM extract fails
- BAD: desk agent INSERT into okf_facts mid-run
```

**Gold write:** agent-owned via `append_gold` / `delete_gold` / `clear_gold` (orchestrator-mediated; unique note ids). Memory UI is view-only.

```text
+ OK: agent tools update gold; Memory UI view-only
- BAD: model calls PUT /gold or invents user/agent ids in tool args
+ OK: delete by note id(s); each append gets a unique id (run_id = provenance only)
- BAD: delete-by-chat-run_id as the only key when multiple notes share a run

+ OK (v0): human seeds team OKF; chat packs mem(team)
- BAD: desk LLM INSERT into okf_facts

+ OK: soft extract uses configurable office_model (OFFICE_MODEL)
- BAD: extract reuses desk agent.model for office housekeeping

+ OK: pack all teammates’ room facts (created_by_user = audit only)
- BAD: filter shared OKF by user_id on pack (v0)
```

**Status:** gold tools + team OKF pack + extract + office Q&A + **OKF export** ([15_OKF_EXPORT.md](./15_OKF_EXPORT.md)). Shelf ∩ P(p) / import later.
