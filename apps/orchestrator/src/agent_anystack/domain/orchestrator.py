"""Office front-desk / soft-orchestrator config from office/orchestrator.yaml.

Not a desk persona — soft LLM jobs + channel pack knobs only.
Desk agents keep agent.yaml (model, autonomy, AGENT.md, gold).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OrchestratorConfig(BaseModel):
    """Pinned Office card settings (git-backed under office/)."""

    model_config = ConfigDict(extra="ignore")

    id: str = "office"
    name: str = "Office"
    # Soft LLM (OKF extract + optional Office Q&A phrasing) — not desk agent.model.
    # Soft jobs are always openai-compatible / Ollama; no stack field on Office.
    model: str = Field(default="llama3.2", min_length=1)
    office_qa_llm: bool = False
    # Master: schedule post-desk OKF extract job.
    okf_extract_enabled: bool = True
    # Soft LLM infer from user+assistant turn (Office model).
    okf_extract_llm: bool = True
    # Deterministic `remember: …` lines in the user message.
    okf_extract_remember_lines: bool = True
    pack_token_budget: int = Field(default=8000, ge=500, le=200_000)
    gold_max_chars: int = Field(default=64_000, ge=1, le=1_000_000)
    recent_history_days: int = Field(default=7, ge=0, le=90)
    recent_history_char_budget: int = Field(default=6_000, ge=0, le=100_000)
    approver_mode: str = Field(default="permissive")
    # -1 = use pack_token_budget as max_input ceiling; else absolute ceiling.
    default_max_input_tokens: int = Field(default=-1, ge=-1, le=200_000)
    # Soft default max_tokens; -1 = omit max_tokens on the wire.
    default_max_output_tokens: int = Field(default=1024, ge=-1, le=100_000)

    # --- Planned (not wired yet; reserved / ignored if present) ---
    # TODO: extract_temperature: float — soft-job sampling (ORCHESTRATOR.md §5)
    # TODO: office_qa_phrase_style: short|formal
    # TODO: default_project_id: str — pack filter when projects exist
    # TODO: extract_schema_version: str
    # TODO: restart_ollama_on_flush: bool — Stacks flush helper
    # Team scope lives on desks / OKF UI — not on Office soft-job config.


class OrchestratorConfigUpdate(BaseModel):
    """Partial update from Team → Configure Office."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1)
    office_qa_llm: bool | None = None
    okf_extract_enabled: bool | None = None
    okf_extract_llm: bool | None = None
    okf_extract_remember_lines: bool | None = None
    pack_token_budget: int | None = Field(default=None, ge=500, le=200_000)
    gold_max_chars: int | None = Field(default=None, ge=1, le=1_000_000)
    recent_history_days: int | None = Field(default=None, ge=0, le=90)
    recent_history_char_budget: int | None = Field(default=None, ge=0, le=100_000)
    approver_mode: str | None = None
    default_max_input_tokens: int | None = Field(default=None, ge=-1, le=200_000)
    default_max_output_tokens: int | None = Field(default=None, ge=-1, le=100_000)
