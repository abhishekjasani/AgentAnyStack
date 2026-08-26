# Pillars

Not a chatbot. An **office** for agents.

```mermaid
flowchart TB
    ORC[Orchestrator choke point]
    P1[1 Office desks teams]
    P2[2 Controllability HITL]
    P3[3 Memory gold + OKF]
    P4[4 No lock-in git + export + BYO]
    P1 --- ORC
    P2 --- ORC
    P3 --- ORC
    P4 --- ORC
```

| Pillar | Meaning |
| --- | --- |
| Office | Desks in `office/`; UI create only |
| Controllability | Autonomy 0–100 + approvals |
| Memory | Gold notepad + shared room OKF |
| No lock-in | Git desks + OKF export + Ollama/BYO |

```text
+ OK: same rules for BA desk and sales desk
- BAD: one mega chatbot with no desks / no memory walls

+ OK: agent.yaml + AGENT.md in git → revert = restore desk
- BAD: agent persona only in a proprietary cloud DB
```

Analytics / Connect are **features under** these pillars — stubs later, not new pillars.
