# SOLID · KISS · YAGNI

Coding style all agents must follow.

**SOLID (Coding Style)**
- **S**: Single Responsibility — each class or function does one clear job.
- **O**: Open/Closed — extend via new adapters or modules, avoid modifying existing stable paths.
- **L**: Liskov Substitution — implementations must be substitutable without breaking caller expectations.
- **I**: Interface Segregation — depend on small, focused protocols rather than fat interfaces.
- **D**: Dependency Inversion — depend on abstractions/protocols; wire concretions at composition root.

```text
+ OK: OfficeRepository (office/repository.py) owns desk file operations only
- BAD: God class mixing file persistence, validation, SSE streaming, and chat routing

+ OK: ExtractJob + _parse_facts_json (memory/extract.py) — extracts only, never infers
- BAD: One massive function handling LLM calling, JSON parsing, fact validation, and DB upsert

+ OK: Dedicated adapter per engine (adapters/opencode/adapter.py, adapters/bedrock.py)
- BAD: Sprawling if-stack-equals chains across routers and business services
```

**KISS (Coding Style)**
- One clear path per function. Prefer direct, readable code over clever abstractions.
- Keep functions small, flat, and focused. Avoid deep nesting and unnecessary indirection.
- Delete dead or unused code immediately.

**YAGNI (Coding Style)**
- Implement only what the current task strictly requires.
- No "might need later" parameters, speculative factory layers, or unused config fields.
- Avoid premature generalization and unnecessary design patterns.

When unsure: **prefer less code**, silently check SOLID/KISS/YAGNI, and ask the user for clarification.
