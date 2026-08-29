"""Stacks connection records — office plugs engines by kind (not ephemeral serve).

Desks reference ``connection_id``. Optional ``stack`` on the desk is a denormalized
product alias for older yaml / display. Ephemeral OpenCode serve processes are
runtime under a connection — not a substitute for the connection itself.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agent_anystack.adapters.bedrock_store import bedrock_data_dir
from pydantic import BaseModel, ConfigDict

Kind = Literal["inference", "agent_runtime", "external"]
Status = Literal["unknown", "connected", "error", "disabled"]

# product id → desk ``stack`` string (chat/adapters)
PRODUCT_TO_STACK: dict[str, str] = {
    "ollama": "openai-compatible",
    "bedrock": "bedrock",
    "opencode": "opencode",
}

STACK_TO_PRODUCT: dict[str, str] = {v: k for k, v in PRODUCT_TO_STACK.items()}


class InferencePreset(BaseModel):
    """Factory preset blueprint for OpenAI-compatible inference providers."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    base_url: str
    requires_api_key: bool = True
    default_context_limit: int | None = None
    default_output_limit: int | None = None

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


INFERENCE_PRESETS: dict[str, InferencePreset] = {
    "ollama": InferencePreset(
        id="ollama",
        name="Ollama",
        base_url="http://127.0.0.1:11434/v1",
        requires_api_key=False,
        default_context_limit=None,
        default_output_limit=None,
    ),
    "groq": InferencePreset(
        id="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        requires_api_key=True,
        default_context_limit=32768,
        default_output_limit=4096,
    ),
    "openrouter": InferencePreset(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        requires_api_key=True,
        default_context_limit=None,
        default_output_limit=4096,
    ),
    "mistral": InferencePreset(
        id="mistral",
        name="Mistral",
        base_url="https://api.mistral.ai/v1",
        requires_api_key=True,
        default_context_limit=32768,
        default_output_limit=4096,
    ),
    "together": InferencePreset(
        id="together",
        name="Together AI",
        base_url="https://api.together.xyz/v1",
        requires_api_key=True,
        default_context_limit=None,
        default_output_limit=4096,
    ),
    "deepseek": InferencePreset(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        requires_api_key=True,
        default_context_limit=None,
        default_output_limit=4096,
    ),
    "openai": InferencePreset(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        requires_api_key=True,
        default_context_limit=None,
        default_output_limit=4096,
    ),
    "zen": InferencePreset(
        id="zen",
        name="Zen",
        base_url="https://opencode.ai/zen/v1",
        requires_api_key=True,
        default_context_limit=None,
        default_output_limit=None,
    ),
    "custom": InferencePreset(
        id="custom",
        name="Custom",
        base_url="",
        requires_api_key=False,
        default_context_limit=None,
        default_output_limit=None,
    ),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class VerifiedInferenceModel:
    """Model verified on an Inference connection card."""

    model_id: str
    display_name: str
    verified_at: str
    region: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_verified_model(row: dict[str, Any]) -> VerifiedInferenceModel | None:
    mid = str(row.get("model_id") or "").strip()
    if not mid:
        return None
    return VerifiedInferenceModel(
        model_id=mid,
        display_name=str(row.get("display_name") or mid),
        verified_at=str(row.get("verified_at") or ""),
        region=row.get("region"),
    )


@dataclass
class RegisteredOpencodeModel:
    """Model proven via OpenCode session.chat — desk dropdown source."""

    inference_connection_id: str
    inference_model_id: str
    display_name: str
    provider_id: str
    model_id: str
    ref: str
    tested_at: str
    inference_product: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_registered_model(row: dict[str, Any]) -> RegisteredOpencodeModel | None:
    ref = str(row.get("ref") or "").strip()
    provider_id = str(row.get("provider_id") or "").strip()
    model_id = str(row.get("model_id") or "").strip()
    inference_model_id = str(row.get("inference_model_id") or model_id).strip()
    if not ref and provider_id and model_id:
        ref = f"{provider_id}/{model_id}"
    if not ref:
        return None
    return RegisteredOpencodeModel(
        inference_connection_id=str(row.get("inference_connection_id") or ""),
        inference_model_id=inference_model_id,
        display_name=str(row.get("display_name") or inference_model_id or ref),
        provider_id=provider_id,
        model_id=model_id or inference_model_id,
        ref=ref,
        tested_at=str(row.get("tested_at") or ""),
        inference_product=str(row.get("inference_product") or ""),
    )


# Lookup aliases so desks/API can use oc-local while stored id stays opencode.
CONNECTION_ALIASES: dict[str, str] = {
    "oc-local": "opencode",
    "ollama-local": "ollama",
    "bed-prod": "bedrock",
}


_DEFAULTS: tuple[dict[str, Any], ...] = (
    {
        "id": "ollama",
        "kind": "inference",
        "product": "ollama",
        "label": "ollama",
        "aliases": ["ollama-local"],
        "enabled": True,
        "status": "unknown",
    },
    {
        "id": "bedrock",
        "kind": "inference",
        "product": "bedrock",
        "label": "bedrock",
        "aliases": ["bed-prod"],
        "enabled": True,
        "status": "unknown",
    },
    {
        "id": "opencode",
        "kind": "agent_runtime",
        "product": "opencode",
        "label": "opencode",
        "aliases": ["oc-local"],
        "enabled": True,
        "status": "unknown",
        "registered_models": [],
    },
)


@dataclass
class StackConnection:
    id: str
    kind: Kind
    product: str
    label: str = ""
    enabled: bool = True
    status: Status = "unknown"
    last_error: str | None = None
    tested_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    registered_models: list[RegisteredOpencodeModel] = field(default_factory=list)
    verified_models: list[VerifiedInferenceModel] = field(default_factory=list)

    def stack(self) -> str:
        """Desk stack alias for this product."""
        return PRODUCT_TO_STACK.get(self.product, self.product)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stack"] = self.stack()
        d["kind_label"] = _kind_label(self.kind)
        d["registered_models"] = [m.as_dict() for m in self.registered_models]
        d["verified_models"] = [m.as_dict() for m in self.verified_models]
        return d

    def find_registered(self, model: str) -> RegisteredOpencodeModel | None:
        raw = (model or "").strip()
        if not raw:
            return None
        for m in self.registered_models:
            if raw in (m.ref, m.inference_model_id, m.model_id, f"{m.provider_id}/{m.model_id}"):
                return m
        return None


def _kind_label(kind: str) -> str:
    if kind == "inference":
        return "Inference"
    if kind == "agent_runtime":
        return "Coding harness"
    if kind == "external":
        return "External agents"
    return kind


class ConnectionStore:
    """JSON store under data/stacks_connections.json (next to sqlite)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "stacks_connections.json"
        self.ensure_seeded()

    def ensure_seeded(self) -> None:
        if not self.path.is_file():
            self._write_raw([dict(d) for d in _DEFAULTS])
            return
        rows = self._read_raw()
        by_id = {r["id"]: r for r in rows if r.get("id")}
        changed = False
        for d in _DEFAULTS:
            if d["id"] in by_id:
                aliases = list(d.get("aliases") or [])
                cur = list(by_id[d["id"]].get("aliases") or [])
                merged = list(dict.fromkeys([*cur, *aliases]))
                if merged != cur:
                    by_id[d["id"]]["aliases"] = merged
                    changed = True
        if changed:
            self._write_raw(list(by_id.values()))

    def list(self) -> list[StackConnection]:
        return [self._parse(r) for r in self._read_raw() if r.get("id")]

    def get(self, connection_id: str) -> StackConnection | None:
        cid = (connection_id or "").strip()
        mapped = CONNECTION_ALIASES.get(cid, cid)
        for c in self.list():
            if c.id == cid or c.id == mapped or cid in c.aliases or mapped in c.aliases:
                return c
        return None

    def get_required(self, connection_id: str) -> StackConnection:
        c = self.get(connection_id)
        if c is None:
            raise ConnectionNotFound(connection_id)
        return c

    def upsert(self, conn: StackConnection) -> StackConnection:
        rows = self._read_raw()
        out: list[dict[str, Any]] = []
        found = False
        payload = self._to_raw(conn)
        for r in rows:
            if r.get("id") == conn.id:
                out.append(payload)
                found = True
            else:
                out.append(r)
        if not found:
            out.append(payload)
        self._write_raw(out)
        return conn

    def set_enabled(self, connection_id: str, enabled: bool) -> StackConnection:
        c = self.get_required(connection_id)
        c.enabled = bool(enabled)
        if not c.enabled:
            c.status = "disabled"
            c.last_error = None
        elif c.status == "disabled":
            c.status = "unknown"
        return self.upsert(c)

    def set_test_result(
        self,
        connection_id: str,
        *,
        ok: bool,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> StackConnection:
        c = self.get_required(connection_id)
        c.tested_at = utc_now_iso()
        if meta:
            c.meta = {**c.meta, **meta}
        if not c.enabled:
            c.status = "disabled"
            c.last_error = error
            return self.upsert(c)
        if ok:
            c.status = "connected"
            c.last_error = None
        else:
            c.status = "error"
            c.last_error = error or "test failed"
        return self.upsert(c)

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(data, dict) and isinstance(data.get("connections"), list):
            return [r for r in data["connections"] if isinstance(r, dict)]
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return []

    def _write_raw(self, rows: list[dict[str, Any]]) -> None:
        payload = {"connections": rows, "updated_at": utc_now_iso()}
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def delete_connection(self, connection_id: str) -> bool:
        cid = (connection_id or "").strip()
        rows = self._read_raw()
        filtered = [r for r in rows if r.get("id") != cid]
        if len(filtered) == len(rows):
            return False
        # Also clean up registered models on other connections that referenced the deleted connection
        for r in filtered:
            if "registered_models" in r and isinstance(r["registered_models"], list):
                r["registered_models"] = [
                    m
                    for m in r["registered_models"]
                    if isinstance(m, dict) and m.get("inference_connection_id") != cid
                ]
        self._write_raw(filtered)
        return True

    def upsert_registered_model(
        self, connection_id: str, entry: RegisteredOpencodeModel
    ) -> StackConnection:
        c = self.get_required(connection_id)
        rest = [m for m in c.registered_models if m.ref != entry.ref]
        rest.append(entry)
        rest.sort(key=lambda m: m.ref)
        c.registered_models = rest
        return self.upsert(c)

    def remove_registered_model(self, connection_id: str, ref: str) -> StackConnection:
        c = self.get_required(connection_id)
        before = len(c.registered_models)
        c.registered_models = [
            m for m in c.registered_models if m.ref != ref and m.inference_model_id != ref
        ]
        if len(c.registered_models) == before:
            raise KeyError(f"registered model not found: {ref}")
        return self.upsert(c)

    def upsert_verified_model(
        self, connection_id: str, entry: VerifiedInferenceModel
    ) -> StackConnection:
        c = self.get_required(connection_id)
        rest = [m for m in c.verified_models if m.model_id != entry.model_id]
        rest.append(entry)
        rest.sort(key=lambda m: m.model_id)
        c.verified_models = rest
        return self.upsert(c)

    def remove_verified_model(self, connection_id: str, model_id: str) -> StackConnection:
        c = self.get_required(connection_id)
        before = len(c.verified_models)
        c.verified_models = [
            m for m in c.verified_models if m.model_id != model_id
        ]
        if len(c.verified_models) == before:
            raise KeyError(f"verified model not found: {model_id}")
        return self.upsert(c)

    @staticmethod
    def _to_raw(c: StackConnection) -> dict[str, Any]:
        return {
            "id": c.id,
            "kind": c.kind,
            "product": c.product,
            "label": c.label,
            "enabled": c.enabled,
            "status": c.status,
            "last_error": c.last_error,
            "tested_at": c.tested_at,
            "meta": c.meta or {},
            "aliases": list(c.aliases or []),
            "registered_models": [m.as_dict() for m in c.registered_models],
            "verified_models": [m.as_dict() for m in c.verified_models],
        }

    @staticmethod
    def _parse(row: dict[str, Any]) -> StackConnection:
        kind = row.get("kind") or "inference"
        if kind not in ("inference", "agent_runtime", "external"):
            kind = "inference"
        status = row.get("status") or "unknown"
        if status not in ("unknown", "connected", "error", "disabled"):
            status = "unknown"
        aliases = [str(a) for a in (row.get("aliases") or []) if str(a).strip()]
        for d in _DEFAULTS:
            if d["id"] == row.get("id"):
                for a in d.get("aliases") or []:
                    if a not in aliases:
                        aliases.append(str(a))
        registered: list[RegisteredOpencodeModel] = []
        for item in row.get("registered_models") or []:
            if isinstance(item, dict):
                parsed = parse_registered_model(item)
                if parsed:
                    registered.append(parsed)
        verified: list[VerifiedInferenceModel] = []
        for item in row.get("verified_models") or []:
            if isinstance(item, dict):
                p_ver = parse_verified_model(item)
                if p_ver:
                    verified.append(p_ver)
        return StackConnection(
            id=str(row["id"]),
            kind=kind,  # type: ignore[arg-type]
            product=str(row.get("product") or row["id"]),
            label=str(row.get("label") or row["id"]),
            enabled=bool(row.get("enabled", True)),
            status=status,  # type: ignore[arg-type]
            last_error=row.get("last_error"),
            tested_at=row.get("tested_at"),
            meta=dict(row.get("meta") or {}),
            aliases=aliases,
            registered_models=registered,
            verified_models=verified,
        )


class ConnectionNotFound(KeyError):
    def __init__(self, connection_id: str) -> None:
        self.connection_id = connection_id
        super().__init__(f"connection not found: {connection_id}")


class ConnectionDisabled(ValueError):
    def __init__(self, connection_id: str) -> None:
        self.connection_id = connection_id
        super().__init__(
            f"connection '{connection_id}' is disabled — enable it on Stacks first"
        )


def connection_store_from_database_url(database_url: str) -> ConnectionStore:
    return ConnectionStore(bedrock_data_dir(database_url))


def resolve_desk_stack(
    *,
    connection_id: str | None,
    stack: str | None,
    store: ConnectionStore,
    require_enabled: bool = True,
) -> tuple[str, str | None]:
    """Return (stack, connection_id). Prefer connection; fall back to stack string."""
    cid = (connection_id or "").strip() or None
    if cid:
        conn = store.get_required(cid)
        if require_enabled and not conn.enabled:
            raise ConnectionDisabled(cid)
        return conn.stack(), conn.id
    sid = (stack or "").strip()
    if not sid:
        raise ValueError("connection_id or stack is required")
    # Legacy desk: map stack → default connection id when seeded.
    product = STACK_TO_PRODUCT.get(sid)
    if product:
        default = store.get(product)
        if default is not None:
            if require_enabled and not default.enabled:
                raise ConnectionDisabled(default.id)
            return default.stack(), default.id
    return sid, None


def resolve_inference_adapter(
    *,
    connection_id: str | None,
    store: ConnectionStore,
    settings: Any,
) -> Any:
    """Resolve an LLM adapter (OpenAI-compatible or Bedrock) for soft-jobs or inference desks."""
    from agent_anystack.adapters.bedrock import BedrockAdapter
    from agent_anystack.adapters.bedrock_store import BedrockProviderStore, resolve_creds
    from agent_anystack.adapters.llm import OpenAICompatibleAdapter

    cid = (connection_id or "").strip() or None
    conn = store.get(cid) if cid else None

    if conn and (conn.product == "bedrock" or conn.stack() == "bedrock"):
        meta = conn.meta or {}
        auth = meta.get("auth") or "api_key"
        region = meta.get("region") or getattr(settings, "aws_region", "us-east-1")
        api_key = meta.get("api_key") or getattr(settings, "aws_bearer_token_bedrock", "")
        akid = meta.get("aws_access_key_id") or getattr(settings, "aws_access_key_id", "")
        secret = meta.get("aws_secret_access_key") or getattr(settings, "aws_secret_access_key", "")
        session_token = meta.get("aws_session_token") or getattr(settings, "aws_session_token", "")
        if not (api_key or (akid and secret)):
            db_url = getattr(settings, "database_url", "sqlite:///./data/office.db")
            creds = resolve_creds(
                BedrockProviderStore(bedrock_data_dir(db_url)),
                env_access_key_id=akid or getattr(settings, "aws_access_key_id", ""),
                env_secret_access_key=secret or getattr(settings, "aws_secret_access_key", ""),
                env_session_token=session_token or getattr(settings, "aws_session_token", ""),
                env_region=region or getattr(settings, "aws_region", "us-east-1"),
                env_api_key=api_key or getattr(settings, "aws_bearer_token_bedrock", ""),
            )
            akid = creds.access_key_id
            secret = creds.secret_access_key
            session_token = creds.session_token
            api_key = creds.api_key
            auth = creds.auth_mode
            region = creds.region

        return BedrockAdapter(
            access_key_id=akid,
            secret_access_key=secret,
            session_token=session_token,
            api_key=api_key,
            auth_mode=auth,
            region=region,
            timeout=getattr(settings, "openai_compatible_timeout", 300.0),
        )

    if conn:
        meta = conn.meta or {}
        preset = (meta.get("preset") or "").lower()
        preset_base_url = INFERENCE_PRESETS.get(preset, {}).get("base_url") if preset else None
        base_url = (meta.get("base_url") or "").strip() or preset_base_url or getattr(
            settings, "openai_compatible_base_url", "http://127.0.0.1:11434/v1"
        )
        api_key = (meta.get("api_key") or "").strip() or None
        return OpenAICompatibleAdapter(
            base_url=base_url,
            api_key=api_key,
            timeout=getattr(settings, "openai_compatible_timeout", 300.0),
        )

    return OpenAICompatibleAdapter(
        base_url=getattr(settings, "openai_compatible_base_url", "http://127.0.0.1:11434/v1"),
        timeout=getattr(settings, "openai_compatible_timeout", 300.0),
    )
