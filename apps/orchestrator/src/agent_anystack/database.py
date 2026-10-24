"""Database URL helpers shared by persistence modules."""

from pathlib import Path


def sqlite_path_from_database_url(database_url: str) -> Path:
    """Convert sqlite:/// URL forms to a filesystem path."""
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"unsupported DATABASE_URL for SQLite (need sqlite): {database_url}")
    raw = database_url.removeprefix("sqlite:///")
    return Path(raw)
