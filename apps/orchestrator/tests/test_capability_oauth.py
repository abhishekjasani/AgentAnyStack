import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient

from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.agent import AgentAutonomy, AgentConfig, CapabilityRegistrations, CreateAgentRequest, Workspace
from agent_anystack.main import create_app
from agent_anystack.office.repository import OfficeRepository
from agent_anystack.security.capability_oauth import CapabilityOAuthStore


class _OAuthHandler(BaseHTTPRequestHandler):
    request_form = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        type(self).request_form = parse_qs(self.rfile.read(length).decode())
        payload = json.dumps(
            {
                "access_token": "access-user-one",
                "refresh_token": "refresh-user-one",
                "expires_in": 3600,
                "scope": "read write",
                "token_type": "Bearer",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        return


@pytest.fixture
def oauth_token_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OAuthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/token"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@pytest.mark.asyncio
async def test_oauth_store_encrypts_tokens_and_scopes_by_user(tmp_path):
    store = CapabilityOAuthStore(tmp_path / "oauth.db", Fernet.generate_key().decode())
    config = {
        "type": "oauth2_user",
        "authorization_url": "https://identity.example.test/authorize",
        "token_url": "https://identity.example.test/token",
        "client_id": "client-1",
        "redirect_uri": "https://office.example.test/capability-oauth/callback",
        "scopes": ["read", "write"],
    }

    started = store.start_authorization(
        user_id="alice",
        capability_id="crm-api",
        auth=config,
    )
    parsed = urlparse(started.authorization_url)
    query = parse_qs(parsed.query)
    assert query["state"] == [started.state]
    assert query["code_challenge_method"] == ["S256"]
    assert "code_challenge" in query

    stored_flow = store._get_flow(started.state)
    assert stored_flow is not None
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(stored_flow["verifier"].encode()).digest()
    ).decode().rstrip("=")
    assert query["code_challenge"] == [expected_challenge]

    store.save_tokens(
        user_id="alice",
        capability_id="crm-api",
        auth=config,
        access_token="alice-secret-token",
        refresh_token="alice-refresh-token",
        expires_at=4_000_000_000,
        scope="read write",
    )
    store.save_tokens(
        user_id="bob",
        capability_id="crm-api",
        auth=config,
        access_token="bob-secret-token",
        refresh_token=None,
        expires_at=4_000_000_000,
        scope="read",
    )

    assert await store.get_access_token(
        "alice", "crm-api", secret_resolver=lambda _ref: None
    ) == "alice-secret-token"
    assert await store.get_access_token(
        "bob", "crm-api", secret_resolver=lambda _ref: None
    ) == "bob-secret-token"
    raw_db = (tmp_path / "oauth.db").read_bytes()
    assert b"alice-secret-token" not in raw_db
    assert b"bob-secret-token" not in raw_db


@pytest.mark.asyncio
async def test_oauth_start_callback_and_per_user_access(tmp_path, oauth_token_server):
    office = tmp_path / "office"
    apis = office / "catalog" / "apis"
    apis.mkdir(parents=True)
    descriptor = {
        "id": "crm-api",
        "kind": "api",
        "name": "CRM API",
        "base_url": "https://crm.example.test/v1",
        "auth": {
            "type": "oauth2_user",
            "authorization_url": "https://identity.example.test/authorize",
            "token_url": oauth_token_server,
            "client_id": "crm-client",
            "redirect_uri": "http://localhost/capability-oauth/callback",
            "scopes": ["read", "write"],
        },
        "operations": [
            {
                "callable_name": "crm_lookup",
                "description": "Look up a CRM record",
                "method": "GET",
                "path": "/records/{id}",
                "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
                "request": {"path": {"id": "id"}},
            }
        ],
    }
    (apis / "crm.yaml").write_text(json.dumps(descriptor), encoding="utf-8")
    (office / "org.yaml").write_text(
        "id: demo\nname: Demo Org\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    (office / "orchestrator.yaml").write_text("{}\n", encoding="utf-8")
    settings = Settings(
        office_repo_path=str(office),
        database_url=f"sqlite:///{tmp_path}/office.db",
        projects_root=str(tmp_path / "projects"),
        capability_oauth_encryption_key=Fernet.generate_key().decode(),
        office_ui_path="",
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    repo = OfficeRepository(office)
    agent = repo.create_agent(
        CreateAgentRequest(
            id="crm-user",
            name="CRM User",
            team="sales",
            stack="openai-compatible",
            model="test-model",
            workspace=Workspace(project_id="oauth-test", path="/"),
        ),
        user_id="alice",
    )
    from agent_anystack.domain.agent import UpdateAgentRequest

    repo.update_agent(
        agent.id,
        UpdateAgentRequest(
            capability_registrations=CapabilityRegistrations(apis=["crm-api"])
        ),
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            started = await client.post(
                "/agents/crm-user/capabilities/crm-api/oauth/start",
                headers={"X-User-Id": "alice"},
            )
            assert started.status_code == 200, started.text
            flow = started.json()
            assert flow["authorization_url"].startswith(
                "https://identity.example.test/authorize?"
            )
            query = parse_qs(urlparse(flow["authorization_url"]).query)

            callback = await client.get(
                "/capability-oauth/callback",
                params={"state": flow["state"], "code": "code-alice"},
            )
            assert callback.status_code == 200, callback.text
            assert _OAuthHandler.request_form["code"] == ["code-alice"]
            assert _OAuthHandler.request_form["code_verifier"]

            status = await client.get(
                "/agents/crm-user/capabilities/crm-api/oauth/status",
                headers={"X-User-Id": "alice"},
            )
            assert status.status_code == 200
            assert status.json() == {"connected": True, "scope": "read write"}
            assert "access-user-one" not in status.text

            bob_status = await client.get(
                "/agents/crm-user/capabilities/crm-api/oauth/status",
                headers={"X-User-Id": "bob"},
            )
            assert bob_status.json() == {"connected": False, "scope": None}

            replay = await client.get(
                "/capability-oauth/callback",
                params={"state": flow["state"], "code": "replay"},
            )
            assert replay.status_code == 400
    finally:
        app.dependency_overrides.clear()
