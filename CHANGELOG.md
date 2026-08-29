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

## [0.3.26] - 2026-08-30

### Added
- Added `connection_id: str = "ollama"` field to `OrchestratorConfig` and `OrchestratorConfigUpdate` for explicit inference stack selection.
- Unified `resolve_inference_adapter` to resolve both Bedrock (IAM keys, Bearer token, BedrockProviderStore) and OpenAI-compatible inference connections (Groq, OpenRouter, Mistral, Ollama, Custom).
- Multi-provider OKF background extraction and Office Q&A conversational synthesis using resolved connection adapters.
- Safe fallback mechanism to deterministic `remember:` lines during extraction if LLM calls fail, time out, or produce malformed JSON.
- Comprehensive test suite for config serialization, Bedrock IAM resolution, dual-adapter execution, and extraction error recovery (54/54 tests passing).

## [0.3.25] - 2026-08-30

### Added
- Strongly typed `InferencePreset` Pydantic model in `adapters/connections.py` with backward-compatible subscript and attribute access.
- Typed `InferencePresetsResponse` schema model and OpenAPI documentation for `GET /stacks/connections/presets`.
- Office UI dynamic preset catalog loader (`loadInferencePresets()`) and modal/drawer binding in `apps/office-ui/app.js`.
- Expanded test suite in `apps/orchestrator/tests/test_opencode_providers.py` verifying typed model access and endpoint schemas.

## [0.3.24] - 2026-08-30

### Added
- Centralized `INFERENCE_PRESETS` in `adapters/connections.py` with official base URLs and default token limits:
  - Groq (`https://api.groq.com/openai/v1`, context: 32768, output: 4096)
  - OpenRouter (`https://openrouter.ai/api/v1`, output: 4096)
  - Mistral (`https://api.mistral.ai/v1`, context: 32768, output: 4096)
  - Together AI (`https://api.together.xyz/v1`, output: 4096)
  - DeepSeek (`https://api.deepseek.com/v1`, output: 4096)
  - OpenAI (`https://api.openai.com/v1`, output: 4096)
  - Zen (`https://opencode.ai/zen/v1`)
  - Ollama (`http://127.0.0.1:11434/v1`)
  - Custom (user-provided `base_url` + optional `api_key`)
- `GET /stacks/connections/presets` API endpoint for dynamic preset discovery.
- Comprehensive test suite for multi-provider OpenCode config injection, preset limit inheritance, and slashed model references in `test_opencode_providers.py`.

### Changed
- Replaced hardcoded provider checks in `adapters/opencode/providers.py` with generic lookup against `INFERENCE_PRESETS`.
- `resolve_inference_adapter()` automatically resolves default `base_url` from preset metadata when omitted.
- Updated Zen preset base URL to `https://opencode.ai/zen/v1`.

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

