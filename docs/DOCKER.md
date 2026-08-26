# Docker — Orchestrator + Office UI

> **Legacy:** Docker layout for the **TS** Fastify + Vite stack in this repo.  
> **Target:** `docker-compose` with Python FastAPI + SQLite/Postgres + UI — [IMPLEMENTATION.md](./IMPLEMENTATION.md) · [LOCAL_MODEL_STACK.md](./LOCAL_MODEL_STACK.md).

Analyst **worker stays on the EC2 host** (not in this container) for the current prototype.

## Build & run on EC2

`CURSOR_API_KEY` and `OFFICE_API_TOKEN` should already be exported in your shell.

```bash
cd ~/cursor-teams
git pull

# required: export OFFICE_API_TOKEN='your-long-secret'

docker rm -f office 2>/dev/null
docker build -t morfgage-office:v0 .
docker run -d --name office -p 8787:8787 \
  -e CURSOR_API_KEY \
  -e OFFICE_API_TOKEN \
  -e OFFICE_CONFIG_PATH=/app/agents/office.config.yaml \
  -v "$(pwd)/agents:/app/agents" \
  -v "$(pwd)/user:/app/user" \
  -v "$(pwd)/apps/orchestrator/data:/app/apps/orchestrator/data" \
  --restart unless-stopped \
  morfgage-office:v0

# login (password stays server-side; cookie is HTTP-only)
curl -s -c /tmp/office.ck -H 'Content-Type: application/json' \
  -d "{\"password\":\"$OFFICE_API_TOKEN\"}" \
  http://127.0.0.1:8787/api/auth/login
curl -s -b /tmp/office.ck http://127.0.0.1:8787/api/health
```

Open the UI → sign in with the **same password** (not visible in DevTools storage afterward). Session cookie: `office_session` (HttpOnly).

## Analyst worker (host — separate screen)

```bash
cd ~/cursor-teams

screen -S analyst
agent worker start --name analyst --verbose \
  --worker-dir ~/cursor-teams
```

Ensure Team **Allow Self-Hosted Agents** is ON and `agents/office.config.yaml` has `cursor.runtime: machine`.

## Useful commands

```bash
docker logs -f office
docker restart office
docker rm -f office
```
