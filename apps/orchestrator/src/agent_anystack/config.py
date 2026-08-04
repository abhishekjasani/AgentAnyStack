"""Platform settings from environment / .env (bucket 1 — not editable via UI in v0)."""

from functools import lru_cache

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
    database_url: str = "sqlite:///./data/office.db"

    ollama_base_url: str = "http://127.0.0.1:11434"

    pack_token_budget: int = 8000
    approver_mode: str = "permissive"


@lru_cache
def get_settings() -> Settings:
    return Settings()
