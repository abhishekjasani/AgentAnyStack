"""Platform settings from environment / .env (bucket 1 — not editable via UI in v0)."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8787
    secret_key: str = "change-me"
    office_api_token: str = "change-me"

    office_repo_path: str = "./office"
    office_ui_path: str = "./apps/office-ui"
    database_url: str = "sqlite:///./data/office.db"

    # Default local engine = Ollama OpenAI /v1. Point at vLLM etc. via same env.
    # OLLAMA_BASE_URL still accepted (host or …/v1); adapter normalizes to …/v1.
    openai_compatible_base_url: str = Field(
        default="http://127.0.0.1:11434/v1",
        validation_alias=AliasChoices(
            "OPENAI_COMPATIBLE_BASE_URL",
            "OLLAMA_BASE_URL",
        ),
    )

    pack_token_budget: int = 8000
    gold_max_chars: int = Field(default=64_000, ge=1, le=1_000_000)
    # Desk chat packs recent channel history (data/channel/<user>.jsonl) — continuity only.
    recent_history_days: int = Field(default=7, ge=0, le=90)
    recent_history_char_budget: int = Field(default=6_000, ge=0, le=100_000)
    okf_extract_enabled: bool = True
    office_qa_llm: bool = False
    office_qa_model: str = "llama3.2"
    approver_mode: str = "permissive"
    # Community: sole admin. Enterprise: expand list / RBAC; edition switch later.
    org_admins: str = Field(
        default="admin",
        validation_alias=AliasChoices("ORG_ADMINS"),
    )
    # For on-demand Stacks GPU health (docker exec nvidia-smi when CLI available).
    ollama_container_name: str = Field(
        default="agentanystack-ollama-1",
        validation_alias=AliasChoices("OLLAMA_CONTAINER_NAME"),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
