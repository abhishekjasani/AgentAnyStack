# Makefile for AgentAnyStack

.PHONY: dev test lint format help

help:
	@echo "AgentAnyStack development commands"
	@echo "  make dev     - Install dependencies and start orchestrator"
	@echo "  make test    - Run all tests"
	@echo "  make lint    - Run linter (ruff)"
	@echo "  make format  - Format code"
	@echo "  make help    - Show this help"

dev:
	cd apps/orchestrator && python -m venv .venv && \
	source .venv/bin/activate && \
	pip install -e . && \
	echo "Run: uvicorn agent_anystack.main:app --reload --port 8787"

test:
	cd apps/orchestrator && python -m pytest

lint:
	cd apps/orchestrator && python -m ruff check .

format:
	cd apps/orchestrator && python -m ruff format .

# For root level (if needed later)
install:
	pip install -e ./apps/orchestrator

