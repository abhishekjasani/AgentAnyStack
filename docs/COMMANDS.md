# Morfgage Office — Commands

> **Legacy prototype grammar** (TS Fastify office). Target product: [PRODUCT_OVERVIEW.md](./PRODUCT_OVERVIEW.md) · build: [IMPLEMENTATION.md](./IMPLEMENTATION.md).  
> Also support **`Office:`** (or no role prefix) for status/knowledge Q&A without an agent — [ORCHESTRATOR.md](./ORCHESTRATOR.md) §2.9.

## Chat grammar

```
Office: what do we know about commission split?
Analyst: <your message>
Analyst: remember: <important durable fact>
reset Analyst
```

Examples:

```
Analyst: refine LAP aggregator idea for DSA and customers
Analyst: remember: Prefer LAP-first for v1 India marketplace
Analyst: compare account aggregators in India mortgage lending
reset Analyst
```

- Role chips in the UI fill `Analyst: ` for you.
- `Developer:` / `Tester:` return **not enabled** until you set `enabled: true` in `agents/office.config.yaml`.
- `remember:` writes to that agent’s **gold memory** file (`agents/memory/<id>.gold.md`, max **200** lines) without starting a Cursor run. Only store important lasting facts.
- Gold memory is prepended into the agent prompt on every live turn; agents may also append important bullets to the same file.
- **New chat** / **Delete** in the UI create separate JSON stores under `apps/orchestrator/data/chats/` (one file per conversation).

## Expand answers

Agent replies show a short **TLDR** card. Click **Expand full answer** for Findings / Sources / etc.

## Auth

Login uses an **HTTP-only session cookie**. The office password (`OFFICE_API_TOKEN`) stays on the server — it is **never** stored in `localStorage` or returned to the browser.

```bash
export OFFICE_API_TOKEN='your-long-secret'
# docker: -e OFFICE_API_TOKEN
```

Sign in with that password in the UI. **Log out** clears the session cookie.

Local-only open access (not for EC2): `OFFICE_AUTH_OPEN=1` and leave `OFFICE_API_TOKEN` unset.
