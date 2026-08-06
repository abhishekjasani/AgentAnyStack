# Architecture map

Coding knowledge for AgentAnyStack. Product truth stays in [`docs/`](../).

```mermaid
flowchart LR
    MAP[00_MAP] --> P[01_PILLARS]
    MAP --> M[02_MODULES]
    MAP --> O[03_OFFICE_GIT]
    MAP --> MEM[04_MEMORY]
    MAP --> R[05_RUN_PATH]
    MAP --> H[06_HITL]
    MAP --> D[07_DOCKER]
    MAP --> S[08_SOLID_KISS]
    MAP --> U[09_UI]
    MAP --> USR[10_USER]
    MAP --> CH[11_CHAT]
    MAP --> OQ[12_OFFICE_QA]
```

| File | Topic |
| --- | --- |
| [01_PILLARS.md](./01_PILLARS.md) | Four pillars |
| [02_MODULES.md](./02_MODULES.md) | Packages / classes |
| [03_OFFICE_GIT.md](./03_OFFICE_GIT.md) | Desks on disk |
| [04_MEMORY.md](./04_MEMORY.md) | Gold vs OKF · seed + pack + extract flows |
| [05_RUN_PATH.md](./05_RUN_PATH.md) | Chat → pack → stream → journal → extract |
| [06_HITL.md](./06_HITL.md) | HITL flow: propose → decide → journal |
| [07_DOCKER.md](./07_DOCKER.md) | Compose + volumes |
| [08_SOLID_KISS.md](./08_SOLID_KISS.md) | SOLID / YAGNI |
| [09_UI.md](./09_UI.md) | Office UI shell |
| [10_USER.md](./10_USER.md) | X-User-Id stub |
| [11_CHAT.md](./11_CHAT.md) | Chat flow: main → router → modules |
| [12_OFFICE_QA.md](./12_OFFICE_QA.md) | Office Q&A flow: main → classify → journal/OKF |

```text
+ OK: read these before changing orchestrator code
- BAD: invent a Python Agent subclass package
```

**Built now (P1–P13):** health, desks, Docker, UI, chat, gold, team OKF pack, post-run extract, office Q&A, **one approval card**.  
**Not yet (rest of v0):** autonomy gate on actions, shelf ∩ P(p), OKF export.  
**Out of v0 cut:** stream-agent `append_gold` tool (human gold write only).
