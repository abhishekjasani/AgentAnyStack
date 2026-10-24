from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from agent_anystack.capabilities.apis.auth import build_auth_headers, requires_user_oauth
from agent_anystack.capabilities.binding import CapabilityBinding
from agent_anystack.capabilities.catalog import CapabilityCatalogService, CapabilityKind
from agent_anystack.domain.agent import AgentConfig

MCP_TIMEOUT_SECONDS = 20.0


def _callable_name(server_id: str, remote_name: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9_-]+", "_", f"mcp_{server_id}_{remote_name}").strip("_")
    if len(raw) <= 64:
        return raw
    suffix = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"{raw[:55]}_{suffix}"


async def _list_tools(client: Client) -> list[Any]:
    tools: list[Any] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            return tools


async def discover_mcp_bindings(
    catalog: CapabilityCatalogService,
    agent: AgentConfig,
    *,
    secret_resolver,
    user_id: str,
    oauth_token_resolver=None,
) -> dict[str, CapabilityBinding]:
    bindings: dict[str, CapabilityBinding] = {}
    for item_id in catalog.resolve_for_agent(agent):
        item = catalog.get(item_id)
        if item is None or item.kind != CapabilityKind.mcp:
            continue
        remote_tools = await discover_mcp_tools(
            item,
            secret_resolver=secret_resolver,
            user_id=user_id,
            oauth_token_resolver=oauth_token_resolver,
        )
        for remote_tool in remote_tools:
            name = _callable_name(item.id, remote_tool.name)
            if name in bindings:
                raise ValueError(f"duplicate capability callable_name: {name}")
            bindings[name] = CapabilityBinding(
                callable_name=name,
                kind=CapabilityKind.mcp,
                item=item,
                operation=remote_tool.name,
                schema={
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": remote_tool.description or remote_tool.title or remote_tool.name,
                        "parameters": remote_tool.input_schema
                        or {"type": "object", "properties": {}},
                    },
                },
            )
    return bindings


async def discover_mcp_tools(
    item: Any,
    *,
    secret_resolver,
    user_id: str | None = None,
    oauth_token_resolver=None,
) -> list[Any]:
    auth = dict(item.auth)
    if item.secret_ref and not auth.get("secret_ref"):
        auth["secret_ref"] = item.secret_ref
    headers = dict(item.headers)
    if requires_user_oauth(str(auth.get("type") or "none")):
        token = (
            await oauth_token_resolver(user_id, item.id)
            if oauth_token_resolver and user_id
            else None
        )
        if not token:
            raise ValueError("user OAuth authorization is required to discover MCP tools")
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers.update(
            await build_auth_headers(auth, secret_resolver, timeout=MCP_TIMEOUT_SECONDS)
        )
    async with httpx2.AsyncClient(
        headers=headers,
        timeout=httpx2.Timeout(5.0, read=MCP_TIMEOUT_SECONDS),
    ) as http_client:
        transport = streamable_http_client(
            item.server_url or "",
            http_client=http_client,
        )
        async with Client(transport) as client:
            return await _list_tools(client)


async def call_mcp_tool(
    binding: CapabilityBinding,
    arguments: dict[str, Any],
    *,
    secret_resolver,
    oauth_token_resolver=None,
    user_id: str | None = None,
) -> str:
    item = binding.item
    auth = dict(item.auth)
    if item.secret_ref and not auth.get("secret_ref"):
        auth["secret_ref"] = item.secret_ref
    headers = dict(item.headers)
    if requires_user_oauth(str(auth.get("type") or "none")):
        token = (
            await oauth_token_resolver(user_id, item.id)
            if oauth_token_resolver and user_id
            else None
        )
        if not token:
            return "error: user OAuth authorization is required"
        headers["Authorization"] = f"Bearer {token}"
    else:
        headers.update(
            await build_auth_headers(auth, secret_resolver or os.environ.get, timeout=MCP_TIMEOUT_SECONDS)
        )
    async with httpx2.AsyncClient(
        headers=headers,
        timeout=httpx2.Timeout(5.0, read=MCP_TIMEOUT_SECONDS),
    ) as http_client:
        transport = streamable_http_client(item.server_url or "", http_client=http_client)
        async with Client(transport) as client:
            result = await client.call_tool(binding.operation or "", arguments)
    if result.is_error:
        texts = [block.text for block in result.content if isinstance(block, TextContent)]
        return "error: " + ("\n".join(texts) or "MCP tool failed")
    if result.structured_content is not None:
        return json.dumps(result.structured_content, ensure_ascii=True, separators=(",", ":"))
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join(texts)[:16_384]
