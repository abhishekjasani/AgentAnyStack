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
    # Soft LLM (OKF extract + optional Office Q&A phrasing) — not desk agent.model
    model: str = Field(default="llama3.2", min_length=1)
    office_qa_llm: bool = False
    okf_extract_enabled: bool = True
    pack_token_budget: int = Field(default=8000, ge=500, le=200_000)
    gold_max_chars: int = Field(default=64_000, ge=1, le=1_000_000)
    recent_history_days: int = Field(default=7, ge=0, le=90)
    recent_history_char_budget: int = Field(default=6_000, ge=0, le=100_000)
    approver_mode: str = Field(default="permissive")

    # --- Planned (not wired yet; reserved / ignored if present) ---
    # TODO: extract_temperature: float — soft-job sampling (docs §5)
    # TODO: office_qa_phrase_style: short|formal
    # TODO: soft_job_max_tokens: int
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
    pack_token_budget: int | None = Field(default=None, ge=500, le=200_000)
    gold_max_chars: int | None = Field(default=None, ge=1, le=1_000_000)
    recent_history_days: int | None = Field(default=None, ge=0, le=90)
    recent_history_char_budget: int | None = Field(default=None, ge=0, le=100_000)
    approver_mode: str | None = None
