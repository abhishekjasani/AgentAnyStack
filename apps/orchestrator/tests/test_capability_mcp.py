from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from mcp.types import TextContent

from agent_anystack.capabilities.catalog import CapabilityCatalogService
from agent_anystack.capabilities.mcp import client as mcp_client
from agent_anystack.capabilities.mcp.client import discover_mcp_bindings
from agent_anystack.capabilities.registry import ToolContext, dispatch
from agent_anystack.domain.agent import AgentConfig, CapabilityRegistrations


class FakeMcpClient:
    def __init__(self, _transport):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def list_tools(self, cursor=None):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="search",
                    title="Search records",
                    description="Search records by text",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                )
            ],
            next_cursor=None,
        )

    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            is_error=False,
            structured_content={"remote_name": name, "arguments": arguments},
            content=[TextContent(type="text", text="ok")],
        )


@pytest.mark.asyncio
async def test_registered_mcp_server_discovers_and_dispatches_namespaced_tool(
    tmp_path: Path,
    monkeypatch,
):
    mcp_dir = tmp_path / "catalog" / "mcp"
    mcp_dir.mkdir(parents=True)
    descriptor = {
        "id": "crm-server",
        "kind": "mcp",
        "name": "CRM",
        "server_url": "https://mcp.example.test/mcp",
        "auth": {"type": "none"},
    }
    (mcp_dir / "crm.yaml").write_text(
        yaml.safe_dump(descriptor, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_client, "Client", FakeMcpClient)
    monkeypatch.setattr(mcp_client, "streamable_http_client", lambda *_args, **_kwargs: object())
    catalog = CapabilityCatalogService(tmp_path)
    agent = AgentConfig(
        id="crm-agent",
        name="CRM Agent",
        team="sales",
        stack="openai-compatible",
        model="test-model",
        capability_registrations=CapabilityRegistrations(mcp=["crm-server"]),
    )

    bindings = await discover_mcp_bindings(
        catalog,
        agent,
        secret_resolver=lambda _ref: None,
        user_id="alice",
    )

    assert set(bindings) == {"mcp_crm-server_search"}
    binding = bindings["mcp_crm-server_search"]
    assert binding.kind.value == "mcp"
    assert binding.operation == "search"
    assert binding.schema["function"]["parameters"]["required"] == ["query"]

    result = await dispatch(
        binding,
        {"query": "open ticket"},
        ToolContext(repo=None, agent=agent, user_id="alice", run_id="run-mcp"),
    )
    assert '"remote_name":"search"' in result
    assert '"query":"open ticket"' in result


@pytest.mark.asyncio
async def test_unregistered_mcp_server_is_not_discovered(tmp_path: Path, monkeypatch):
    mcp_dir = tmp_path / "catalog" / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "crm.yaml").write_text(
        "id: crm-server\nkind: mcp\nname: CRM\nserver_url: https://mcp.example.test/mcp\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_client, "Client", FakeMcpClient)
    monkeypatch.setattr(mcp_client, "streamable_http_client", lambda *_args, **_kwargs: object())
    catalog = CapabilityCatalogService(tmp_path)
    agent = AgentConfig(
        id="other-agent",
        name="Other Agent",
        team="ops",
        stack="openai-compatible",
        model="test-model",
        capability_registrations=CapabilityRegistrations(),
    )

    bindings = await discover_mcp_bindings(
        catalog,
        agent,
        secret_resolver=lambda _ref: None,
        user_id="alice",
    )

    assert bindings == {}
