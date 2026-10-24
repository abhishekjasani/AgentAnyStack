from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from agent_anystack.capabilities.apis.auth import build_auth_headers, requires_user_oauth

API_TIMEOUT_SECONDS = 10.0
MAX_API_RESPONSE_BYTES = 16_384
_PATH_FIELD = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _parse_arguments(arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _mapped_values(mapping: dict[str, str], args: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for destination, source in mapping.items():
        if source not in args:
            continue
        value = args[source]
        if isinstance(value, (str, int, float, bool)) or value is None:
            values[destination] = value
        else:
            raise ValueError(f"API argument {source} must be a scalar")
    return values


def _operation_url(item: Any, operation: Any, args: dict[str, Any]) -> str:
    parsed_base = urlsplit(item.base_url or "")
    if parsed_base.scheme not in {"http", "https"} or not parsed_base.hostname:
        raise ValueError("API descriptor base_url must be an absolute HTTP(S) URL")
    if parsed_base.username or parsed_base.password:
        raise ValueError("API descriptor base_url must not contain credentials")
    if not operation.path.startswith("/") or operation.path.startswith("//"):
        raise ValueError("API operation path must be a root-relative path")

    path_values = _mapped_values(operation.request.path, args)

    def replace_path_field(match: re.Match[str]) -> str:
        field_name = match.group(1)
        if field_name not in path_values:
            raise ValueError(f"missing API path argument: {field_name}")
        return quote(str(path_values[field_name]), safe="")

    path = _PATH_FIELD.sub(replace_path_field, operation.path)
    return f"{item.base_url.rstrip('/')}{path}"


def _environment_secret(secret_ref: str) -> str | None:
    return os.environ.get(secret_ref)


async def execute_api_operation(
    binding: Any,
    arguments: dict[str, Any] | str | None,
    *,
    secret_resolver: Callable[[str], str | None] | None = None,
    oauth_token_resolver=None,
    user_id: str | None = None,
) -> str:
    item = binding.item
    operation = next(
        (
            candidate
            for candidate in item.operations
            if candidate.callable_name == binding.callable_name
        ),
        None,
    )
    if operation is None:
        return "error: unknown API operation"
    args = _parse_arguments(arguments)
    try:
        url = _operation_url(item, operation, args)
        headers = dict(item.headers)
        auth = dict(item.auth)
        if item.secret_ref and not auth.get("secret_ref"):
            auth["secret_ref"] = item.secret_ref
        if requires_user_oauth(str(auth.get("type") or "none")):
            token = (
                await oauth_token_resolver(user_id, item.id)
                if oauth_token_resolver and user_id
                else None
            )
            if not token:
                raise ValueError("user OAuth authorization is required")
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers.update(
                await build_auth_headers(
                    auth,
                    secret_resolver or _environment_secret,
                    timeout=API_TIMEOUT_SECONDS,
                )
            )
        query = _mapped_values(operation.request.query, args)
        body = _mapped_values(operation.request.body, args)
        async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS, follow_redirects=False) as client:
            async with client.stream(
                operation.method,
                url,
                params=query,
                json=body if operation.request.body else None,
                headers=headers,
            ) as response:
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    remaining = MAX_API_RESPONSE_BYTES - len(payload)
                    payload.extend(chunk[:remaining])
                    if len(chunk) > remaining or len(payload) >= MAX_API_RESPONSE_BYTES:
                        break
                response.raise_for_status()
                text = bytes(payload).decode("utf-8", errors="replace")
                if len(payload) >= MAX_API_RESPONSE_BYTES:
                    text += "\n[response truncated]"
                try:
                    return json.dumps(json.loads(text), ensure_ascii=True, separators=(",", ":"))
                except json.JSONDecodeError:
                    return text
    except httpx.HTTPStatusError as exc:
        return f"error: API request returned HTTP {exc.response.status_code}"
    except (httpx.HTTPError, ValueError) as exc:
        return f"error: API request failed ({type(exc).__name__})"