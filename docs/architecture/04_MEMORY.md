# Memory

Users share the **room**; they do not share the **notepad**.

```mermaid
flowchart TB
    subgraph short [Short-term]
        G["gold(a,u) markdown in git"]
    end
    subgraph long [Long-term shared]
        T[(Team OKF SQLite)]
        S[(Shelf floor/org OKF)]
    end
    HUMAN[Human / Memory UI] -->|v0 write| G
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

| Tier | Store | Who writes (v0) |
| --- | --- | --- |
| Gold | `gold/<user_id>.md` | **Human** via `PUT /gold` / Memory UI |
| Team OKF | SQLite `okf_facts` (`DATABASE_URL`) | **Human seed** `POST /okf/facts` until extract |
| Shelf | — | Later |

## Modules

| Piece | Path |
| --- | --- |
| Fact model | `memory/fact.py` |
| SQLite store | `memory/store.py` |
| Pack markdown | `memory/pack.py` |
| HTTP | `api/okf.py` — `GET/POST /okf/facts`, `DELETE` archive |
| Chat | `ChatRunService` packs gold + team OKF into system prompt |

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

Chat run path detail: [11_CHAT.md](./11_CHAT.md).

## Who writes gold

**v0 decision:** gold write is **human-only**. Do not build `append_gold` for the stream agent in this cut.

```text
+ OK (v0): human edits gold; agent uses packed notes in chat
- BAD (v0): stream agent writes gold / append_gold tool

+ OK (v0): human seeds team OKF; chat packs mem(team)
- BAD: desk LLM INSERT into okf_facts

+ OK: extract after run via BackgroundTasks (next)
- BAD: await long extract inside chat response

+ OK: pack all teammates’ room facts (created_by_user = audit only)
- BAD: filter shared OKF by user_id on pack (v0)
```

**Status (P10):** gold + **SQLite team OKF pack** done. Extract / shelf / export still later.
