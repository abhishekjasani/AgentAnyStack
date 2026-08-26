# Worker bootstrap — Agent Office

> **Legacy:** Cursor My Machines workers for the **TS** prototype in this repo.  
> **Target:** Python orchestrator adapters — [IMPLEMENTATION.md](./IMPLEMENTATION.md). Keep this file as ops reference for Cursor `runtime: machine` until the Python Cursor adapter exists.

Self-hosted My Machines workers on EC2 (or local). **One worker process per role** (`--name` must match `workerName` in the agent config).

## Prerequisites

1. Dashboard → Cloud Agents → **Allow Self-Hosted Agents** ON.
2. Cursor GitHub App authorized on `abhishek-jasani/cursor-teams` (primary repo / `main`).
3. Checkout parent office repo on the host (`~/cursor-teams`). Nested `morfgage/` can live inside it.
4. Orchestrator: `cursor.runtime: machine`, `CURSOR_API_KEY` + `OFFICE_API_TOKEN` set.

Parent-only `--worker-dir` is enough (nested `morfgage/` is already on disk).

## Analyst

```bash
cd ~/cursor-teams
screen -S analyst
agent worker start --name analyst --verbose \
  --worker-dir ~/cursor-teams
# Ctrl-A D to detach
```

## Developer

```bash
cd ~/cursor-teams
screen -S developer
agent worker start --name developer --verbose \
  --worker-dir ~/cursor-teams
# Ctrl-A D to detach
```

## Tester

```bash
cd ~/cursor-teams
screen -S tester
agent worker start --name tester --verbose \
  --worker-dir ~/cursor-teams
# Ctrl-A D to detach
```

## Useful screen commands

```bash
screen -ls
screen -r analyst      # or developer / tester
# detach: Ctrl-A then D
```

## Chat usage

```
Analyst: <research / refine>
Developer: <implement ticket>
Tester: <verify / test>
reset Analyst|Developer|Tester|all
```

In the Office UI, chips fill the role prefix. Each desk shows live/session status for that worker.

## Optional second worker-dir

Only if you want a separate git registration for product:

```bash
agent worker start --name developer --verbose \
  --worker-dir ~/cursor-teams \
  --worker-dir ~/cursor-teams/morfgage
```

SDK still binds **one** primary repo (`cursor-teams`). Extra `--worker-dir` is filesystem access only.
