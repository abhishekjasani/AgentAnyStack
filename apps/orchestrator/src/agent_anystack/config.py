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
    okf_extract_enabled: bool = True
    approver_mode: str = "permissive"


@lru_cache
def get_settings() -> Settings:
    return Settings()
