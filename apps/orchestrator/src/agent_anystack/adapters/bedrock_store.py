"""Write-only Bedrock provider creds + verified model catalog (data dir JSON).

GET never returns secret values — only status hints.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_INFERENCE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,200}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def bedrock_data_dir(database_url: str, fallback: Path | None = None) -> Path:
    """Prefer directory next to sqlite file; else fallback ./data."""
    if database_url.startswith("sqlite:///"):
        raw = database_url.removeprefix("sqlite:///")
        db = Path(raw)
        return db.parent
    return fallback or Path("./data")


@dataclass
class BedrockCreds:
    access_key_id: str
    secret_access_key: str
    region: str
    updated_at: str | None = None

    def configured(self) -> bool:
        return bool(self.access_key_id.strip() and self.secret_access_key.strip())


@dataclass
class BedrockModelEntry:
    id: str
    display_name: str
    verified_at: str
    region: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "verified_at": self.verified_at,
            "region": self.region,
            "verified": True,
        }


class BedrockProviderStore:
    """Persists AWS keys (file) + verified inference ids. Secrets never exposed via status()."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._creds_path = self.root / "bedrock_provider.json"
        self._models_path = self.root / "bedrock_models.json"

    def status(self) -> dict[str, Any]:
        creds = self.load_creds()
        key = creds.access_key_id.strip()
        return {
            "configured": creds.configured(),
            "region": creds.region,
            "access_key_hint": (f"…{key[-4:]}" if len(key) >= 4 else None),
            "updated_at": creds.updated_at,
        }

    def load_creds(self) -> BedrockCreds:
        if not self._creds_path.is_file():
            return BedrockCreds("", "", "us-east-1")
        try:
            data = json.loads(self._creds_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return BedrockCreds("", "", "us-east-1")
        if not isinstance(data, dict):
            return BedrockCreds("", "", "us-east-1")
        return BedrockCreds(
            access_key_id=str(data.get("access_key_id") or ""),
            secret_access_key=str(data.get("secret_access_key") or ""),
            region=str(data.get("region") or "us-east-1").strip() or "us-east-1",
            updated_at=data.get("updated_at"),
        )

    def put_creds(
        self,
        *,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Write-only upsert. Empty/None fields leave existing values unchanged."""
        cur = self.load_creds()
        new_id = (access_key_id if access_key_id is not None else cur.access_key_id).strip()
        new_secret = (
            secret_access_key
            if secret_access_key is not None
            else cur.secret_access_key
        ).strip()
        new_region = (
            (region if region is not None else cur.region).strip() or "us-east-1"
        )
        if not new_id or not new_secret:
            raise ValueError(
                "access_key_id and secret_access_key are required "
                "(or leave blank only when already configured)."
            )
        payload = {
            "access_key_id": new_id,
            "secret_access_key": new_secret,
            "region": new_region,
            "updated_at": utc_now_iso(),
        }
        self._creds_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return self.status()

    def list_models(self) -> list[BedrockModelEntry]:
        if not self._models_path.is_file():
            return []
        try:
            data = json.loads(self._models_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = data.get("models") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        out: list[BedrockModelEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("id") or "").strip()
            if not mid:
                continue
            out.append(
                BedrockModelEntry(
                    id=mid,
                    display_name=str(row.get("display_name") or mid),
                    verified_at=str(row.get("verified_at") or ""),
                    region=str(row.get("region") or ""),
                )
            )
        return out

    def upsert_model(self, entry: BedrockModelEntry) -> BedrockModelEntry:
        models = [m for m in self.list_models() if m.id != entry.id]
        models.append(entry)
        models.sort(key=lambda m: m.id)
        self._write_models(models)
        return entry

    def delete_model(self, model_id: str) -> bool:
        before = self.list_models()
        after = [m for m in before if m.id != model_id]
        if len(after) == len(before):
            return False
        self._write_models(after)
        return True

    def _write_models(self, models: list[BedrockModelEntry]) -> None:
        payload = {"models": [m.as_dict() for m in models]}
        self._models_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def validate_inference_id(raw: str) -> str:
    mid = (raw or "").strip()
    if not mid or not _INFERENCE_ID.match(mid):
        raise ValueError(
            "invalid inference id — use a Bedrock model or inference profile id"
        )
    return mid


def resolve_creds(
    store: BedrockProviderStore,
    *,
    env_access_key_id: str = "",
    env_secret_access_key: str = "",
    env_region: str = "us-east-1",
) -> BedrockCreds:
    """Prefer UI-stored creds; fall back to platform env."""
    stored = store.load_creds()
    if stored.configured():
        return stored
    return BedrockCreds(
        access_key_id=(env_access_key_id or "").strip(),
        secret_access_key=(env_secret_access_key or "").strip(),
        region=(env_region or "us-east-1").strip() or "us-east-1",
    )
