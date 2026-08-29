# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to Semantic Versioning.

## [Unreleased]

### Added
- `CONTRIBUTING.md` with beginner-friendly contribution guide
- Clean public `CHANGELOG.md`
- Simple `Makefile` for common commands (`make dev`, `make test`, `make lint`, `make format`)
- Made `docs/` public (vision documents + architecture notes)
- Updated community section (GitHub Issues + personal LinkedIn)
- Standardized naming to `PROJECT_OVERVIEW.md`

### Changed
- Softer, more welcoming language around core vision documents
- Clear standard fork + PR workflow in contribution guide

## [0.3.23] - 2026-08-29

### Added
- Multi-provider inference support for Orchestrator soft jobs (`connection_id` on Office config).
- Orchestrator-owned sampling policy with `extract_temperature` (default `0.0`) and `office_qa_temperature` (default `0.2`).
- Safe error recovery & deterministic fallbacks for OKF extraction and Office Front Desk Q&A.
- Comprehensive test suite for orchestrator config, adapter routing, and sampling policy in `test_orchestrator_config.py`.

### Changed
- Decoupled `run_okf_extract()`, `OkfSoftAnswer`, and `OfficeQaService` from concrete adapter implementations to support multi-provider duck-typed adapters.

## [0.3.22] - 2026-08-26

### Improved
- Configurable hierarchical token limits for OpenCode (model → connection → preset → defaults)
- Better compatibility with strict providers (e.g. Groq)
- Improved model registration candidate selection and lightweight health probes
- Expanded unit tests for providers and inference candidates

## [0.3.21] - 2026-08-26

### Fixed
- Inference connection candidate isolation (prevented cross-connection model leakage)
- Legacy Bedrock fallback behavior
- Cleaned stale models from catalog
- Added dedicated unit tests

## [0.3.20] - 2026-08-26

### Fixed
- OpenCode session registry cleanup after kill
- Stale session pruning on serve shutdown
- UI ghost rows in Runtimes panel
- Added runtime test suite

## [0.3.19] - 2026-08-26

### Changed
- Removed redundant "Label" field from connection form
- Simplified UI and backend to use Connection ID directly

See `docs/PROJECT_OVERVIEW.md` for the full product vision.

