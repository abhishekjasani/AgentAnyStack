# User id (community vs multi-user)

API always carries who is acting (`X-User-Id`). **Community default = one admin.** Multi-user plumbing is already there; a later edition switch can lock “no extra users.”

```mermaid
flowchart LR
    UI[UI user · default admin]
    H["Header X-User-Id"]
    API[get_user_id]
    GOLD["gold/admin.md"]
    UI --> H --> API --> GOLD
```

| Piece | Role |
| --- | --- |
| Default user | `admin` (community sole seat) |
| `ORG_ADMINS` | default `admin` — may decide any HITL card |
| `X-User-Id` | Stub identity on every request |
| `GET /me` | Echo `{ "user_id": "…" }` |
| UI | Default **admin**; alice/bob optional for multi-user demos |

```text
+ OK: community ships as admin; gold → gold/admin.md
- BAD: default a crowd of stub users as org admins

+ OK: keep X-User-Id multi-user-ready for enterprise later
- BAD: remove user_id from gold/journal now and re-plumb later

+ OK: curl -H "X-User-Id: admin" http://127.0.0.1:8787/me
- BAD: real passwords / SSO in this phase
```

**Later:** community switch = single allowed user (`admin`); enterprise cloud = multi-user + RBAC.
