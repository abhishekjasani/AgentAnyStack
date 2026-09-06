# Contributing to AgentAnyStack

Thank you for wanting to help! This project is in early stages (v0.3.26+). We welcome contributions of all sizes.

## Quick Start

1. **Fork** this repository on GitHub
2. Clone your fork locally
3. `cp .env.example .env` (fill required values)
4. Follow the root-directory setup commands in [README.md](README.md#quick-start).
5. Run the checks below before submitting a PR.

## Read First (Mandatory)

- `README.md` — project overview
- `docs/PROJECT_OVERVIEW.md` — 360° vision and pillars
- `docs/MEMORY_ARCHITECTURE.md` — memory philosophy
- `docs/ORCHESTRATOR.md` — control plane, HITL and autonomy model
- `docs/IMPLEMENTATION.md` — current tech stack and status
- `CONTRIBUTING.md` (this file)

**Vision Note:** The top-level vision documents describe the core product philosophy. Improvements that increase clarity or add useful examples are welcome. For larger changes to the foundational ideas, we recommend starting a discussion in GitHub Discussions first.

## Development

Run from the repository root with your virtual environment activated:

```bash
python -m pip install -e './apps/orchestrator[dev]'
python -m pytest apps/orchestrator/tests
node --check apps/office-ui/app.js
node --check apps/office-ui/office-scene.js
node --test apps/office-ui/tests/*.test.mjs
```

The Makefile lint and format targets require a separately installed `ruff`. The existing repository has legacy lint findings; compare changed files with the base branch and avoid unrelated cleanup. `make dev` installs the package and prints a server command; it does not start the server. The README's explicit setup commands keep relative office/UI paths correct.

For frontend work, follow the [UI architecture checks](docs/architecture/09_UI.md#verification). Describe tested viewports and interactions in the PR. Keep live indicators tied to real backend activity.

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
- Add task-flow examples to [Office UI guide](docs/OFFICE_UI.md)

## How to Submit Changes (Standard Fork + PR workflow)

1. Create a feature branch on **your fork** (`git checkout -b feature/your-change`)
2. Make your changes
3. Run the development checks above and review relevant lint findings
4. Commit with a clear message
5. Push the branch to your fork
6. Open a Pull Request from your fork back to this repository

**PR Checklist:**
- Tests pass
- Relevant lint findings reviewed
- Changes are clear and well explained
- References any related issue (if applicable)

## Community

- Questions, ideas, and contributions: use **GitHub Issues**
- Connect with the author: [LinkedIn](https://www.linkedin.com/in/abhishek-j-81444613a/)

We appreciate your help building the agent office!

