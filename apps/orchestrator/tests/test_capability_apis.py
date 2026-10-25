import json
import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from agent_anystack.adapters.llm import ChatTurnResult, ToolCallRequest
from agent_anystack.capabilities.binding import build_bindings
from agent_anystack.capabilities.catalog import CapabilityCatalogService
from agent_anystack.domain.agent import AgentConfig, CapabilityRegistrations
from agent_anystack.office.repository import OfficeRepository
from agent_anystack.runs.journal import RunJournal
from agent_anystack.runs.service import ChatRunService


class _ApiHandler(BaseHTTPRequestHandler):
    last_request: dict | None = None
    requests: list[dict] = []
    token_form: dict[str, list[str]] | None = None

    def _send_json(self, payload):
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        type(self).last_request = {
            "path": parsed.path,
            "query": query,
            "authorization": self.headers.get("Authorization"),
            "host": self.headers.get("Host"),
            "idempotency_key": self.headers.get("Idempotency-Key"),
            "story_id": self.headers.get("X-Story-Id"),
        }
        type(self).requests.append(type(self).last_request)
        if parsed.path == "/pages":
            page = int(query.get("page", ["1"])[0])
            self._send_json({"results": [page], "has_more": page < 3})
            return
        if parsed.path == "/nested":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Request-Id", "req-42")
            self.end_headers()
            self.wfile.write(b'{"data":{"record":{"id":"R-7","name":"June"}}}')
            return
        if parsed.path == "/cursor":
            cursor = query.get("cursor", [""])[0]
            if not cursor:
                self._send_json({"items": ["first"], "next": "cursor-2"})
            else:
                self._send_json({"items": ["second"], "next": None})
            return
        self._send_json({"ok": True, "value": "x" * 30_000})

    def do_POST(self):
        parsed = urlparse(self.path)
        payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        content_type = self.headers.get("Content-Type", "")
        if parsed.path == "/oauth/token":
            type(self).token_form = parse_qs(payload.decode())
            self._send_json({"access_token": "oauth-access-token"})
            return
        type(self).last_request = {
            "path": parsed.path,
            "query": parse_qs(parsed.query),
            "authorization": self.headers.get("Authorization"),
            "host": self.headers.get("Host"),
            "idempotency_key": self.headers.get("Idempotency-Key"),
            "story_id": self.headers.get("X-Story-Id"),
            "content_type": content_type,
            "body": json.loads(payload) if payload and "application/json" in content_type else None,
            "body_raw": payload,
        }
        type(self).requests.append(type(self).last_request)
        self._send_json({"ok": True, "value": "x" * 30_000})

    def log_message(self, _format, *_args):
        return


@pytest.fixture
def local_api_server():
    _ApiHandler.last_request = None
    _ApiHandler.requests = []
    _ApiHandler.token_form = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _api_catalog(office_root: Path, base_url: str) -> CapabilityCatalogService:
    apis_dir = office_root / "catalog" / "apis"
    apis_dir.mkdir(parents=True)
    descriptor = {
        "id": "inventory-api",
        "kind": "api",
        "name": "Inventory API",
        "description": "Read inventory data",
        "base_url": base_url,
        "auth": {"type": "bearer", "secret_ref": "INVENTORY_TOKEN"},
        "headers": {"Accept": "application/json"},
        "operations": [
            {
                "callable_name": "inventory_lookup",
                "description": "Look up inventory by SKU",
                "method": "GET",
                "path": "/inventory/{sku}",
                "parameters": {
                    "type": "object",
                    "properties": {"sku": {"type": "string"}, "host": {"type": "string"}},
                    "required": ["sku"],
                    "additionalProperties": False,
                },
                "request": {"path": {"sku": "sku"}, "query": {"include": "include"}},
            },
            {
                "callable_name": "inventory_count",
                "description": "Count inventory items",
                "method": "GET",
                "path": "/inventory/count",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "callable_name": "inventory_create",
                "description": "Create an inventory item",
                "method": "POST",
                "path": "/inventory",
                "parameters": {
                    "type": "object",
                    "properties": {"sku": {"type": "string"}, "name": {"type": "string"}},
                    "required": ["sku", "name"],
                    "additionalProperties": False,
                },
                "request": {"body": {"sku": "sku", "name": "name"}},
                "idempotency_key_header": "Idempotency-Key",
            },
        ],
    }
    (apis_dir / "inventory.yaml").write_text(
        yaml.safe_dump(descriptor, sort_keys=False),
        encoding="utf-8",
    )
    return CapabilityCatalogService(office_root)


def _rewrite_operation(tmp_path: Path, callable_name: str, update: dict) -> CapabilityCatalogService:
    descriptor_path = tmp_path / "catalog" / "apis" / "inventory.yaml"
    descriptor = yaml.safe_load(descriptor_path.read_text(encoding="utf-8"))
    operation = next(
        op for op in descriptor["operations"] if op["callable_name"] == callable_name
    )
    operation.update(update)
    descriptor_path.write_text(yaml.safe_dump(descriptor, sort_keys=False), encoding="utf-8")
    return CapabilityCatalogService(tmp_path)


def _api_agent() -> AgentConfig:
    return AgentConfig(
        id="inventory-agent",
        name="Inventory Agent",
        team="ops",
        stack="openai-compatible",
        model="test-model",
        capability_registrations=CapabilityRegistrations(apis=["inventory-api"]),
    )


def test_rest_descriptor_builds_one_tool_binding_per_operation(tmp_path, local_api_server):
    catalog = _api_catalog(tmp_path, local_api_server)

    bindings = build_bindings(catalog, _api_agent())

    assert set(bindings) == {
        "inventory_lookup",
        "inventory_count",
        "inventory_create",
    }
    binding = bindings["inventory_lookup"]
    assert binding.callable_name == "inventory_lookup"
    assert binding.item.operations[0].callable_name == "inventory_lookup"
    assert binding.operation == "inventory_lookup"
    assert binding.schema["function"]["parameters"]["required"] == ["sku"]


def test_legacy_api_tool_name_loads_as_callable_name(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    descriptor_path = tmp_path / "catalog" / "apis" / "inventory.yaml"
    descriptor_path.write_text(
        descriptor_path.read_text(encoding="utf-8").replace(
            "callable_name:", "tool_name:"
        ),
        encoding="utf-8",
    )

    catalog = CapabilityCatalogService(tmp_path)
    operation = catalog.get("inventory-api").operations[0]

    assert operation.callable_name == "inventory_lookup"
    assert "callable_name" in operation.model_dump()
    assert "tool_name" not in operation.model_dump()


@pytest.mark.asyncio
async def test_rest_dispatch_maps_arguments_and_uses_fixed_host(tmp_path, local_api_server):
    catalog = _api_catalog(tmp_path, local_api_server)
    binding = build_bindings(catalog, _api_agent())["inventory_lookup"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    result = await dispatch(
        binding,
        {"sku": "sku-42", "include": "stock", "host": "attacker.invalid"},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="test-user",
            run_id="run-api-test",
            secret_resolver=lambda name: "test-token" if name == "INVENTORY_TOKEN" else None,
        ),
    )

    assert '"ok": true' in result
    assert "[response truncated]" in result
    assert len(result) < 17_000
    assert _ApiHandler.last_request == {
        "path": "/inventory/sku-42",
        "query": {"include": ["stock"]},
        "authorization": "Bearer test-token",
        "host": urlparse(local_api_server).netloc,
        "idempotency_key": None,
        "story_id": None,
    }
    assert "test-token" not in result


@pytest.mark.asyncio
async def test_rest_dispatch_maps_body_fields(tmp_path, local_api_server):
    catalog = _api_catalog(tmp_path, local_api_server)
    binding = build_bindings(catalog, _api_agent())["inventory_create"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    await dispatch(
        binding,
        {"sku": "sku-99", "name": "Widget", "host": "attacker.invalid"},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            capability_call_id="capcall-test-123",
            secret_resolver=lambda ref: "test-token" if ref == "INVENTORY_TOKEN" else None,
        ),
    )

    assert _ApiHandler.last_request["path"] == "/inventory"
    assert _ApiHandler.last_request["body"] == {"sku": "sku-99", "name": "Widget"}
    assert _ApiHandler.last_request["host"] == urlparse(local_api_server).netloc
    assert _ApiHandler.last_request["idempotency_key"] == "capcall-test-123"


@pytest.mark.asyncio
async def test_nested_json_dynamic_header_and_response_selection(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_lookup",
        {
            "path": "/nested",
            "parameters": {
                "type": "object",
                "properties": {"story_id": {"type": "string"}},
                "required": ["story_id"],
                "additionalProperties": False,
            },
            "request": {"headers": {"X-Story-Id": "story_id"}},
            "response": {
                "select": {"record_id": "/data/record/id"},
                "include_status": True,
                "headers": ["X-Request-Id"],
            },
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_lookup"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    result = json.loads(await dispatch(
        binding,
        {"story_id": "harbor-17"},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    ))

    assert _ApiHandler.last_request["story_id"] == "harbor-17"
    assert result == {
        "data": {"record_id": "R-7"},
        "status": 200,
        "headers": {"X-Request-Id": "req-42"},
    }


@pytest.mark.asyncio
async def test_nested_json_body_mapping(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_create",
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["city", "tags"],
                "additionalProperties": False,
            },
            "request": {
                "body": {
                    "/customer/address/city": "city",
                    "/tags": "tags",
                }
            },
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_create"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    await dispatch(
        binding,
        {"city": "San Francisco", "tags": ["fiction", "harbor"]},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    )

    assert _ApiHandler.last_request["body"] == {
        "customer": {"address": {"city": "San Francisco"}},
        "tags": ["fiction", "harbor"],
    }


@pytest.mark.asyncio
async def test_form_urlencoded_dynamic_header(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_create",
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "return_to": {"type": "string"},
                    "story_id": {"type": "string"},
                },
                "required": ["return_to", "story_id"],
                "additionalProperties": False,
            },
            "request": {
                "body": {"return_to": "return_to"},
                "headers": {"X-Story-Id": "story_id"},
                "body_encoding": "form_urlencoded",
            },
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_create"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    result = await dispatch(
        binding,
        {"return_to": "https://example.test/a b", "story_id": "story-9"},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    )

    assert '"ok": true' in result
    assert _ApiHandler.last_request["story_id"] == "story-9"
    assert b"return_to=https%3A%2F%2Fexample.test%2Fa+b" in _ApiHandler.last_request["body_raw"]


@pytest.mark.asyncio
async def test_multipart_base64_binary_upload(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_create",
        {
            "parameters": {
                "type": "object",
                "properties": {
                    "caption": {"type": "string"},
                    "attachment_b64": {"type": "string", "description": "Base64 file bytes"},
                },
                "required": ["caption", "attachment_b64"],
                "additionalProperties": False,
            },
            "request": {
                "body": {"caption": "caption", "attachment": "attachment_b64"},
                "body_encoding": "multipart",
                "binary_fields": ["attachment"],
            },
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_create"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    await dispatch(
        binding,
        {"caption": "June's story", "attachment_b64": base64.b64encode(b"story-card").decode()},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    )

    request = _ApiHandler.last_request
    assert request["content_type"].startswith("multipart/form-data; boundary=")
    assert b"name=\"caption\"" in request["body_raw"]
    assert b"filename=\"upload.bin\"" in request["body_raw"]
    assert b"story-card" in request["body_raw"]


@pytest.mark.asyncio
async def test_raw_base64_body_and_content_type(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_create",
        {
            "parameters": {
                "type": "object",
                "properties": {"file_b64": {"type": "string"}},
                "required": ["file_b64"],
                "additionalProperties": False,
            },
            "request": {
                "body_encoding": "raw_base64",
                "raw_body_argument": "file_b64",
                "body_content_type": "application/octet-stream",
            },
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_create"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    await dispatch(
        binding,
        {"file_b64": base64.b64encode(b"binary-story").decode()},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    )

    assert _ApiHandler.last_request["content_type"] == "application/octet-stream"
    assert _ApiHandler.last_request["body_raw"] == b"binary-story"


@pytest.mark.asyncio
async def test_bounded_page_pagination_and_response_extraction(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_count",
        {
            "path": "/pages",
            "pagination": {
                "mode": "page",
                "request_parameter": "page",
                "has_more_pointer": "/has_more",
                "items_pointer": "/results",
                "max_pages": 3,
            },
            "response": {
                "select": {"results": "/items", "pages_read": "/page_count"},
                "include_status": True,
                "headers": ["Content-Type"],
            },
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_count"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    result = json.loads(await dispatch(
        binding,
        {},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    ))

    assert [request["query"]["page"][0] for request in _ApiHandler.requests] == ["1", "2", "3"]
    assert result == {
        "data": {"results": [1, 2, 3], "pages_read": 3},
        "status": 200,
        "headers": {"Content-Type": "application/json"},
    }


@pytest.mark.asyncio
async def test_cursor_pagination_aggregates_selected_items(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_count",
        {
            "path": "/cursor",
            "pagination": {
                "mode": "cursor",
                "request_parameter": "cursor",
                "next_value_pointer": "/next",
                "items_pointer": "/items",
                "max_pages": 4,
            },
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_count"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    result = json.loads(await dispatch(
        binding,
        {},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    ))

    assert [request["query"].get("cursor", [""])[0] for request in _ApiHandler.requests] == ["", "cursor-2"]
    assert result == {"items": ["first", "second"], "page_count": 2, "has_more": False}


@pytest.mark.asyncio
async def test_invalid_response_pointer_returns_safe_executor_error(tmp_path, local_api_server):
    _api_catalog(tmp_path, local_api_server)
    catalog = _rewrite_operation(
        tmp_path,
        "inventory_count",
        {
            "path": "/nested",
            "response": {"select": {"missing": "/data/no-such-field"}},
        },
    )
    binding = build_bindings(catalog, _api_agent())["inventory_count"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    result = await dispatch(
        binding,
        {},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda _name: "test-token",
        ),
    )

    assert result == "error: API request failed (ValueError)"


@pytest.mark.asyncio
async def test_oauth_client_credentials_auth_executes_at_call_time(
    tmp_path,
    local_api_server,
):
    _api_catalog(tmp_path, local_api_server)
    descriptor_path = tmp_path / "catalog" / "apis" / "inventory.yaml"
    descriptor = descriptor_path.read_text(encoding="utf-8")
    descriptor_path.write_text(
        descriptor.replace(
            "auth:\n  type: bearer\n  secret_ref: INVENTORY_TOKEN",
            "auth:\n  type: oauth2_client_credentials\n"
            f"  token_url: {local_api_server}/oauth/token\n"
            "  client_id: inventory-client\n"
            "  client_secret_ref: INVENTORY_CLIENT_SECRET\n",
        ),
        encoding="utf-8",
    )
    catalog = CapabilityCatalogService(tmp_path)
    binding = build_bindings(catalog, _api_agent())["inventory_lookup"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    result = await dispatch(
        binding,
        {"sku": "sku-oauth"},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="u",
            run_id="r",
            secret_resolver=lambda ref: "client-secret" if ref == "INVENTORY_CLIENT_SECRET" else None,
        ),
    )

    assert _ApiHandler.token_form == {
        "grant_type": ["client_credentials"],
        "client_id": ["inventory-client"],
        "client_secret": ["client-secret"],
    }
    assert _ApiHandler.last_request["authorization"] == "Bearer oauth-access-token"
    assert "client-secret" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("auth", "secrets", "expected"),
    [
        ({"type": "none"}, {}, {}),
        (
            {"type": "api_key", "secret_ref": "API_KEY", "header": "X-API-Key"},
            {"API_KEY": "key-value"},
            {"X-API-Key": "key-value"},
        ),
        (
            {"type": "basic", "username_ref": "USER", "password_ref": "PASS"},
            {"USER": "alice", "PASS": "wonderland"},
            {"Authorization": "Basic YWxpY2U6d29uZGVybGFuZA=="},
        ),
    ],
)
async def test_explicit_api_auth_schemes(auth, secrets, expected):
    from agent_anystack.capabilities.apis.auth import build_auth_headers

    headers = await build_auth_headers(
        auth,
        secrets.get,
        timeout=1,
    )

    assert headers == expected


@pytest.mark.asyncio
async def test_user_oauth_token_is_used_for_api_call(tmp_path, local_api_server):
    catalog = _api_catalog(tmp_path, local_api_server)
    descriptor_path = tmp_path / "catalog" / "apis" / "inventory.yaml"
    descriptor = yaml.safe_load(descriptor_path.read_text(encoding="utf-8"))
    descriptor["auth"] = {
        "type": "oauth2_user",
        "authorization_url": "https://identity.example.test/authorize",
        "token_url": "https://identity.example.test/token",
        "client_id": "inventory-client",
        "redirect_uri": "https://office.example.test/capability-oauth/callback",
        "scopes": ["inventory.read"],
    }
    descriptor_path.write_text(yaml.safe_dump(descriptor, sort_keys=False), encoding="utf-8")
    catalog = CapabilityCatalogService(tmp_path)
    binding = build_bindings(catalog, _api_agent())["inventory_lookup"]

    from agent_anystack.capabilities.registry import ToolContext, dispatch

    async def user_token(user_id, capability_id):
        assert user_id == "alice"
        assert capability_id == "inventory-api"
        return "alice-access-token"

    result = await dispatch(
        binding,
        {"sku": "oauth-sku"},
        ToolContext(
            repo=None,
            agent=_api_agent(),
            user_id="alice",
            run_id="oauth-run",
            oauth_token_resolver=user_token,
        ),
    )

    assert _ApiHandler.last_request["authorization"] == "Bearer alice-access-token"
    assert "alice-access-token" not in result


def test_api_descriptor_rejects_unknown_auth_type(tmp_path, local_api_server):
    descriptor = _api_catalog(tmp_path, local_api_server)
    path = tmp_path / "catalog" / "apis" / "inventory.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("type: bearer", "type: magic"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown API auth type: magic"):
        CapabilityCatalogService(tmp_path)


def test_api_operation_rejects_absolute_url_path():
    from pydantic import ValidationError

    from agent_anystack.capabilities.catalog import ApiOperation

    with pytest.raises(ValidationError, match="root-relative path"):
        ApiOperation(
            callable_name="unsafe",
            description="Unsafe URL",
            method="GET",
            path="https://attacker.invalid/steal",
            parameters={"type": "object", "properties": {}},
        )


@pytest.mark.asyncio
async def test_chat_tool_loop_offers_and_dispatches_api_operation(
    tmp_path,
    local_api_server,
    monkeypatch,
    caplog,
):
    from unittest.mock import AsyncMock, MagicMock

    _api_catalog(tmp_path, local_api_server)
    (tmp_path / "org.yaml").write_text(
        "id: demo\nname: Demo Org\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INVENTORY_TOKEN", "test-token")
    journal = RunJournal(tmp_path / "journal.jsonl")
    service = ChatRunService(
        repo=OfficeRepository(tmp_path),
        journal=journal,
        openai_compatible_base_url="http://unused.invalid/v1",
        okf=MagicMock(),
        database_url=f"sqlite:///{tmp_path}/api-test.db",
    )
    adapter = MagicMock()
    adapter.complete_chat_turn = AsyncMock(
        side_effect=[
            ChatTurnResult(
                tool_calls=[
                    ToolCallRequest(
                        id="api-call-1",
                        name="inventory_lookup",
                        arguments='{"sku":"sku-chat","include":"availability"}',
                    )
                ]
            ),
            ChatTurnResult(content="Inventory checked"),
        ]
    )

    events = [
        event
        async for event in service._run_with_gold_tools(
            adapter=adapter,
            model="test-model",
            messages=[{"role": "user", "content": "check stock"}],
            agent=_api_agent(),
            user_id="test-user",
            run_id="run-api-chat",
        )
    ]

    offered_tools = adapter.complete_chat_turn.call_args_list[0].kwargs["tools"]
    assert "inventory_lookup" in {
        tool["function"]["name"] for tool in offered_tools
    }
    assert _ApiHandler.last_request["path"] == "/inventory/sku-chat"
    assert _ApiHandler.last_request["query"] == {"include": ["availability"]}
    assert "test-token" not in str(events)
    assert "test-token" not in caplog.text
    call_entry = next(
        entry for entry in journal._read_all() if entry.entry_type == "capability_call"
    )
    assert call_entry.capability_kind == "api"
    assert call_entry.callable_name == "inventory_lookup"
    assert call_entry.operation == "inventory_lookup"