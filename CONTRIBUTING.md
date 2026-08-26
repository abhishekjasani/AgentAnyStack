# Contributing to AgentAnyStack

Thank you for wanting to help! This project is in early stages (v0.3.21+). We welcome contributions of all sizes.

## Quick Start

1. Fork and clone the repo
2. `cp .env.example .env` (fill in required values)
3. `cd apps/orchestrator && make dev` (or follow README quickstart)
4. Run `make test` and `make lint` before submitting PRs

## Read First (Mandatory)

- `README.md` — project overview
- `docs/PRODUCT_OVERVIEW.md` — 360° vision and pillars
- `docs/MEMORY_ARCHITECTURE.md` — memory philosophy
- `docs/ORCHESTRATOR.md` — control plane, HITL and autonomy model
- `docs/IMPLEMENTATION.md` — current tech stack and status
- `CONTRIBUTING.md` (this file)

**Vision Note:** The top-level vision documents describe the core product philosophy. Improvements that increase clarity or add useful examples are welcome. For larger changes to the foundational ideas, we recommend starting a discussion in GitHub Discussions first.

## Development

```bash
make dev      # install + start orchestrator
make test     # run tests
make lint     # run ruff
make format   # format code
```

- Use Python 3.12+
- Follow existing style (async, Pydantic, SOLID/KISS — see `docs/architecture/08_SOLID_KISS.md`)
- Write tests for new features
- Keep changes small and focused

## Good First Issues

Look for issues labeled `good-first-issue`. Common starters:
- Improve test coverage
- Fix documentation typos or outdated references
- Small adapter improvements
- UI polish in `apps/office-ui/`
- Add examples to `USE_CASES_MEMORY.md`

## How to Submit Changes

1. Create a branch (`git checkout -b feature/your-change`)
2. Make your changes
3. Run `make test && make lint`
4. Commit with clear message
5. Open a Pull Request

**PR Checklist:**
- Tests pass
- Linting passes
- Updates to canonical docs where needed
- Clear description of what changed and why
- References any related issue

## Community

- Questions, ideas, and contributions: use **GitHub Issues**
- Connect with the author: [LinkedIn](https://www.linkedin.com/in/abhishek-j-81444613a/)

We appreciate your help building the agent office!

