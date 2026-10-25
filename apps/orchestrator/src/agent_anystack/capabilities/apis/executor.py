from __future__ import annotations

import base64
import binascii
import json
import os
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx

from agent_anystack.capabilities.apis.auth import build_auth_headers, requires_user_oauth

API_TIMEOUT_SECONDS = 10.0
MAX_API_RESPONSE_BYTES = 16_384
MAX_API_REQUEST_BYTES = 1_048_576
MAX_PAGINATION_PAGES = 20
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


def _mapped_values(
    mapping: dict[str, str],
    args: dict[str, Any],
    *,
    allow_complex: bool = False,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for destination, source in mapping.items():
        if source not in args:
            continue
        value = args[source]
        if allow_complex or isinstance(value, (str, int, float, bool)) or value is None:
            values[destination] = value
        else:
            raise ValueError(f"API argument {source} must be a scalar")
    return values


def _mapped_headers(mapping: dict[str, str], args: dict[str, Any]) -> dict[str, str]:
    values = _mapped_values(mapping, args)
    headers: dict[str, str] = {}
    for name, value in values.items():
        if not isinstance(value, str) or "\r" in value or "\n" in value:
            raise ValueError(f"API header argument for {name} must be safe text")
        headers[name] = value
    return headers


def _set_json_pointer(target: dict[str, Any], pointer: str, value: Any) -> None:
    """Set a top-level body key or an RFC 6901 object path such as /user/name."""
    if not pointer.startswith("/"):
        target[pointer] = value
        return
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    if not parts or any(part == "" for part in parts):
        raise ValueError("body JSON Pointer must identify a non-empty object path")
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise ValueError("body JSON Pointer conflicts with an existing value")
        current = child
    current[parts[-1]] = value


def _json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("response selection must use a JSON Pointer")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise ValueError("response JSON Pointer did not match the API response")
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise ValueError("response JSON Pointer did not match the API response")
            current = current[index]
        else:
            raise ValueError("response JSON Pointer did not match the API response")
    return current


def _build_json_body(mapping: dict[str, str], args: dict[str, Any]) -> dict[str, Any]:
    values = _mapped_values(mapping, args, allow_complex=True)
    body: dict[str, Any] = {}
    for destination, value in values.items():
        _set_json_pointer(body, destination, value)
    return body


def _decode_base64(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError("binary request argument must be base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("binary request argument is not valid base64") from exc
    if len(decoded) > MAX_API_REQUEST_BYTES:
        raise ValueError("decoded request body exceeds 1 MiB limit")
    return decoded


async def _read_response(response: httpx.Response, remaining_bytes: int) -> tuple[bytes, bool]:
    payload = bytearray()
    truncated = False
    async for chunk in response.aiter_bytes():
        room = remaining_bytes - len(payload)
        if room <= 0:
            truncated = True
            break
        payload.extend(chunk[:room])
        if len(chunk) > room:
            truncated = True
            break
    return bytes(payload), truncated


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
    capability_call_id: str | None = None,
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
        headers.update(_mapped_headers(operation.request.headers, args))
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
        if operation.idempotency_key_header and capability_call_id:
            headers[operation.idempotency_key_header] = capability_call_id
        body_values = _mapped_values(
            operation.request.body,
            args,
            allow_complex=operation.request.body_encoding == "json",
        )
        request_kwargs: dict[str, Any] = {"headers": headers}
        body_encoding = operation.request.body_encoding
        if body_encoding == "json":
            json_body: dict[str, Any] = {}
            for destination, value in body_values.items():
                _set_json_pointer(json_body, destination, value)
            encoded_body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            if len(encoded_body) > MAX_API_REQUEST_BYTES:
                raise ValueError("request body exceeds 1 MiB limit")
            request_kwargs["json"] = json_body if operation.request.body else None
            if operation.request.body_content_type:
                headers["Content-Type"] = operation.request.body_content_type
        elif body_encoding == "form_urlencoded":
            request_kwargs["data"] = body_values
            encoded_size = len(urlencode(body_values, doseq=False).encode("ascii"))
            if encoded_size > MAX_API_REQUEST_BYTES:
                raise ValueError("request body exceeds 1 MiB limit")
            if operation.request.body_content_type:
                headers["Content-Type"] = operation.request.body_content_type
        elif body_encoding == "multipart":
            multipart_fields: dict[str, str] = {}
            multipart_files: dict[str, tuple[str, bytes, str]] = {}
            for field_name, value in body_values.items():
                if field_name in operation.request.binary_fields:
                    binary = _decode_base64(value)
                    multipart_files[field_name] = (
                        "upload.bin",
                        binary,
                        operation.request.body_content_type or "application/octet-stream",
                    )
                elif isinstance(value, (str, int, float, bool)) or value is None:
                    multipart_fields[field_name] = "" if value is None else str(value)
                else:
                    raise ValueError("multipart text fields must be scalar")
            unknown_binary = set(operation.request.binary_fields) - set(body_values)
            if unknown_binary:
                raise ValueError("multipart binary field has no mapped value")
            encoded_size = sum(len(value.encode("utf-8")) for value in multipart_fields.values())
            encoded_size += sum(len(value[1]) for value in multipart_files.values())
            encoded_size += sum(
                512 + len(name.encode("utf-8")) * 4
                for name in (*multipart_fields.keys(), *multipart_files.keys())
            )
            if encoded_size > MAX_API_REQUEST_BYTES:
                raise ValueError("request body exceeds 1 MiB limit")
            request_kwargs["data"] = multipart_fields
            request_kwargs["files"] = multipart_files
        else:
            raw_value = args.get(operation.request.raw_body_argument or "")
            raw_body = _decode_base64(raw_value)
            request_kwargs["content"] = raw_body
            headers["Content-Type"] = (
                operation.request.body_content_type or "application/octet-stream"
            )

        pagination = operation.pagination
        if pagination:
            if pagination.mode == "cursor" and pagination.request_parameter in query:
                raise ValueError("cursor pagination parameter is reserved for the executor")
            if pagination.mode == "page" and pagination.request_parameter in query:
                raise ValueError("page pagination parameter is reserved for the executor")

        total_bytes = 0
        page_values: list[Any] = []
        aggregate_items: list[Any] = []
        last_status = 0
        last_headers = httpx.Headers()
        truncated = False
        page_value: str | int | None = pagination.initial_value if pagination else None
        seen_cursors: set[str] = (
            {str(page_value)}
            if pagination and pagination.mode == "cursor" and page_value is not None
            else set()
        )
        has_more_pages = False
        max_pages = min(pagination.max_pages, MAX_PAGINATION_PAGES) if pagination else 1

        async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS, follow_redirects=False) as client:
            for _page_index in range(max_pages):
                page_query = dict(query)
                if pagination and page_value is not None:
                    page_query[pagination.request_parameter] = page_value
                async with client.stream(
                    operation.method,
                    url,
                    params=page_query,
                    **request_kwargs,
                ) as response:
                    response.raise_for_status()
                    last_status = response.status_code
                    last_headers = response.headers
                    page_body, was_truncated = await _read_response(
                        response,
                        MAX_API_RESPONSE_BYTES - total_bytes,
                    )
                total_bytes += len(page_body)
                truncated = truncated or was_truncated
                if pagination and was_truncated:
                    raise ValueError("paginated API response exceeds 16 KiB aggregate limit")

                raw_text = page_body.decode("utf-8", errors="replace")
                if pagination or operation.response.select:
                    try:
                        page_json = json.loads(raw_text)
                    except json.JSONDecodeError as exc:
                        raise ValueError("API response is not valid JSON for configured mapping") from exc
                else:
                    try:
                        page_json = json.loads(raw_text)
                    except json.JSONDecodeError:
                        page_json = raw_text
                page_values.append(page_json)

                if not pagination:
                    break
                if pagination.items_pointer:
                    items = _json_pointer(page_json, pagination.items_pointer)
                    if not isinstance(items, list):
                        raise ValueError("pagination items_pointer must select a JSON array")
                    aggregate_items.extend(items)

                if pagination.mode == "cursor":
                    next_cursor = _json_pointer(page_json, pagination.next_value_pointer or "")
                    if next_cursor is None or next_cursor == "":
                        has_more_pages = False
                        break
                    has_more_pages = True
                    cursor_key = str(next_cursor)
                    if cursor_key in seen_cursors:
                        raise ValueError("pagination cursor repeated; stopping to prevent a loop")
                    seen_cursors.add(cursor_key)
                    page_value = next_cursor
                else:
                    has_more = _json_pointer(page_json, pagination.has_more_pointer or "")
                    if has_more is not True:
                        has_more_pages = False
                        break
                    has_more_pages = True
                    page_value = int(page_value or 1) + 1

        if pagination:
            result_data: Any = (
                {"items": aggregate_items, "page_count": len(page_values)}
                if pagination.items_pointer
                else {"pages": page_values, "page_count": len(page_values)}
            )
            if result_data is not None:
                result_data["has_more"] = has_more_pages
        else:
            result_data = page_values[0]

        if operation.response.body_encoding == "base64":
            result_data = {"base64": base64.b64encode(page_body).decode("ascii")}
        elif operation.response.body_encoding == "text" and not pagination:
            result_data = page_body.decode("utf-8", errors="replace")
        elif operation.response.body_encoding == "json" and not isinstance(result_data, (dict, list)):
            raise ValueError("API response was not a JSON object or array")
        if operation.response.select:
            if not isinstance(result_data, (dict, list)):
                raise ValueError("response selection requires JSON data")
            result_data = {
                output_name: _json_pointer(result_data, pointer)
                for output_name, pointer in operation.response.select.items()
            }
        if truncated:
            if operation.response.select or operation.pagination:
                raise ValueError("response mapping cannot be applied to truncated data")
            if isinstance(result_data, str):
                result_data += "\n[response truncated]"
            else:
                result_data = {"data": result_data, "truncated": True}
        if operation.response.include_status or operation.response.headers:
            result_data = {"data": result_data}
            if operation.response.include_status:
                result_data["status"] = last_status
            if operation.response.headers:
                result_data["headers"] = {
                    name: last_headers.get(name)
                    for name in operation.response.headers
                    if last_headers.get(name) is not None
                }
        return json.dumps(result_data, ensure_ascii=True, separators=(",", ":")) if not isinstance(result_data, str) else result_data
    except httpx.HTTPStatusError as exc:
        return f"error: API request returned HTTP {exc.response.status_code}"
    except (httpx.HTTPError, ValueError) as exc:
        return f"error: API request failed ({type(exc).__name__})"