# Run path

How a chat turn will flow (chat phase later).

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant ORC as RunService
    participant P as Packer
    participant A as StackAdapter
    participant J as Journal

    U->>API: POST /agents/id/chat
    API->>ORC: new run_id + user_id
    ORC->>P: pack C(a,p,u)
    ORC->>A: stream Envelope + AGENT.md + memory + msg
    A-->>U: tokens
    ORC->>J: log run
    ORC-->>ORC: BackgroundTasks extract
```

## Prompt order (every run)

```text
1. Office Envelope (fixed)
2. AGENT.md persona
3. Tools schema (scoped)
4. Packed memory C(a,p,u)
5. User message
```

```text
+ OK: Envelope = musts + workspace + autonomy intent; persona = role; gold pack = user scope
- BAD: persona says ignore approvals / read all office files

+ OK: channel=office_ui on journal
- BAD: invent company facts in office Q&A with no citations
```

**Status:** Envelope + Ollama adapter + journal = **P8 done**. Gold/OKF pack still stubbed empty.
