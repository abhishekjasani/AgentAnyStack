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

Kind = Literal["inference", "agent_runtime", "external"]
Status = Literal["unknown", "connected", "error", "disabled"]

# product id → desk ``stack`` string (chat/adapters)
PRODUCT_TO_STACK: dict[str, str] = {
    "ollama": "openai-compatible",
    "bedrock": "bedrock",
    "opencode": "opencode",
}

STACK_TO_PRODUCT: dict[str, str] = {v: k for k, v in PRODUCT_TO_STACK.items()}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class StackConnection:
    id: str
    kind: Kind
    product: str
    label: str
    enabled: bool = True
    status: Status = "unknown"
    last_error: str | None = None
    tested_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def stack(self) -> str:
        """Desk stack alias for this product."""
        return PRODUCT_TO_STACK.get(self.product, self.product)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stack"] = self.stack()
        d["kind_label"] = _kind_label(self.kind)
        return d


def _kind_label(kind: str) -> str:
    if kind == "inference":
        return "Inference"
    if kind == "agent_runtime":
        return "Agent runtime"
    if kind == "external":
        return "External agent"
    return kind


_DEFAULTS: tuple[dict[str, Any], ...] = (
    {
        "id": "ollama",
        "kind": "inference",
        "product": "ollama",
        "label": "Ollama",
        "enabled": True,
        "status": "unknown",
    },
    {
        "id": "bedrock",
        "kind": "inference",
        "product": "bedrock",
        "label": "AWS Bedrock",
        "enabled": True,
        "status": "unknown",
    },
    {
        "id": "opencode",
        "kind": "agent_runtime",
        "product": "opencode",
        "label": "OpenCode",
        "enabled": True,
        "status": "unknown",
    },
)


class ConnectionStore:
    """JSON store under data/stacks_connections.json (next to sqlite)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "stacks_connections.json"
        self.ensure_seeded()

    def ensure_seeded(self) -> None:
        rows = self._read_raw()
        by_id = {r["id"]: r for r in rows if r.get("id")}
        changed = False
        for d in _DEFAULTS:
            if d["id"] not in by_id:
                by_id[d["id"]] = dict(d)
                changed = True
        if changed or not self.path.is_file():
            self._write_raw(list(by_id.values()))

    def list(self) -> list[StackConnection]:
        return [self._parse(r) for r in self._read_raw() if r.get("id")]

    def get(self, connection_id: str) -> StackConnection | None:
        cid = (connection_id or "").strip()
        for c in self.list():
            if c.id == cid:
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
        }

    @staticmethod
    def _parse(row: dict[str, Any]) -> StackConnection:
        kind = row.get("kind") or "inference"
        if kind not in ("inference", "agent_runtime", "external"):
            kind = "inference"
        status = row.get("status") or "unknown"
        if status not in ("unknown", "connected", "error", "disabled"):
            status = "unknown"
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
