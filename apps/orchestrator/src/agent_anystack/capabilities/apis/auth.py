from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import httpx

SecretResolver = Callable[[str], str | None]
AuthHandler = Callable[..., Any]


def _required_secret(auth: dict[str, Any], key: str, resolve: SecretResolver) -> str:
    ref = auth.get(key)
    value = resolve(str(ref)) if ref else None
    if not value:
        raise ValueError(f"API authentication secret is not configured: {key}")
    return value


def _none_auth(auth: dict[str, Any], resolve: SecretResolver) -> dict[str, str]:
    del auth, resolve
    return {}


def _api_key_auth(auth: dict[str, Any], resolve: SecretResolver) -> dict[str, str]:
    value = _required_secret(auth, "secret_ref", resolve)
    header = str(auth.get("header") or "X-API-Key")
    prefix = str(auth.get("prefix") or "")
    return {header: f"{prefix}{value}"}


def _bearer_auth(auth: dict[str, Any], resolve: SecretResolver) -> dict[str, str]:
    value = _required_secret(auth, "secret_ref", resolve)
    return {"Authorization": f"Bearer {value}"}


def _basic_auth(auth: dict[str, Any], resolve: SecretResolver) -> dict[str, str]:
    username = _required_secret(auth, "username_ref", resolve)
    password = _required_secret(auth, "password_ref", resolve)
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


async def _oauth2_client_credentials_auth(
    auth: dict[str, Any],
    resolve: SecretResolver,
    *,
    timeout: float,
) -> dict[str, str]:
    token_url = str(auth.get("token_url") or "")
    client_id = str(auth.get("client_id") or "")
    if not token_url or not client_id:
        raise ValueError("OAuth2 client credentials requires token_url and client_id")
    client_secret = _required_secret(auth, "client_secret_ref", resolve)
    form: dict[str, str] = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if auth.get("scope"):
        form["scope"] = str(auth["scope"])
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(token_url, data=form)
    if response.is_error:
        raise ValueError(f"OAuth2 token endpoint returned HTTP {response.status_code}")
    try:
        token = response.json().get("access_token")
    except (ValueError, AttributeError):
        token = None
    if not isinstance(token, str) or not token:
        raise ValueError("OAuth2 token endpoint returned no access token")
    return {"Authorization": f"Bearer {token}"}


AUTH_HANDLERS: dict[str, AuthHandler] = {
    "none": _none_auth,
    "api_key": _api_key_auth,
    "bearer": _bearer_auth,
    "basic": _basic_auth,
    "oauth2_client_credentials": _oauth2_client_credentials_auth,
}


def has_auth_handler(auth_type: str) -> bool:
    return auth_type in AUTH_HANDLERS


async def build_auth_headers(
    auth: dict[str, Any],
    secret_resolver: SecretResolver,
    *,
    timeout: float,
) -> dict[str, str]:
    auth_type = str(auth.get("type") or "none")
    handler = AUTH_HANDLERS.get(auth_type)
    if handler is None:
        raise ValueError(f"unsupported API auth type: {auth_type}")
    if auth_type == "oauth2_client_credentials":
        return await handler(auth, secret_resolver, timeout=timeout)
    return handler(auth, secret_resolver)