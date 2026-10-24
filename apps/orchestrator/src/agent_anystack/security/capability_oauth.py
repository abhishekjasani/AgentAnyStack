from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import httpx
from cryptography.fernet import Fernet, InvalidToken


_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_oauth_tokens (
    user_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at REAL,
    scope TEXT,
    auth_json TEXT NOT NULL,
    PRIMARY KEY (user_id, capability_id)
);
CREATE TABLE IF NOT EXISTS capability_oauth_flows (
    state_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    verifier TEXT NOT NULL,
    auth_json TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""
_FLOW_TTL_SECONDS = 600
_TOKEN_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    state: str


class CapabilityOAuthStore:
    """Encrypted, per-user OAuth token storage and PKCE flow state."""

    def __init__(self, db_path: Path, encryption_key: str) -> None:
        if not encryption_key or encryption_key == "change-me":
            raise ValueError("CAPABILITY_OAUTH_ENCRYPTION_KEY must be configured")
        try:
            self._cipher = Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("CAPABILITY_OAUTH_ENCRYPTION_KEY must be a Fernet key") from exc
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _state_hash(state: str) -> str:
        return hashlib.sha256(state.encode()).hexdigest()

    def start_authorization(
        self,
        *,
        user_id: str,
        capability_id: str,
        auth: dict[str, Any],
    ) -> OAuthStart:
        authorization_url = str(auth.get("authorization_url") or "")
        token_url = str(auth.get("token_url") or "")
        client_id = str(auth.get("client_id") or "")
        redirect_uri = str(auth.get("redirect_uri") or "")
        for label, value in (
            ("authorization_url", authorization_url),
            ("token_url", token_url),
            ("redirect_uri", redirect_uri),
        ):
            parsed = urlsplit(value)
            local_http = parsed.scheme == "http" and parsed.hostname in {
                "localhost",
                "127.0.0.1",
                "::1",
            }
            if parsed.scheme != "https" and not local_http:
                raise ValueError(f"OAuth {label} must use HTTPS")
            if not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f"OAuth {label} must be an absolute URL without credentials")
        if not client_id:
            raise ValueError("OAuth client_id is required")

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).decode().rstrip("=")
        scope = auth.get("scopes") or []
        query = dict(parse_qsl(urlsplit(authorization_url).query, keep_blank_values=True))
        query.update(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        if scope:
            query["scope"] = " ".join(str(value) for value in scope)
        parsed = urlsplit(authorization_url)
        target = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))

        safe_auth = {
            key: value
            for key, value in auth.items()
            if key not in {"client_secret", "access_token", "refresh_token"}
        }
        now = time.time()
        with self._connect() as db:
            db.execute("DELETE FROM capability_oauth_flows WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO capability_oauth_flows VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self._state_hash(state),
                    user_id,
                    capability_id,
                    self._cipher.encrypt(verifier.encode()).decode(),
                    json.dumps(safe_auth),
                    now + _FLOW_TTL_SECONDS,
                ),
            )
        return OAuthStart(target, state)

    def _get_flow(self, state: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM capability_oauth_flows WHERE state_hash = ?",
                (self._state_hash(state),),
            ).fetchone()
        if row is None or float(row["expires_at"]) < time.time():
            return None
        try:
            verifier = self._cipher.decrypt(row["verifier"].encode()).decode()
        except InvalidToken:
            return None
        return {
            "user_id": row["user_id"],
            "capability_id": row["capability_id"],
            "verifier": verifier,
            "auth": json.loads(row["auth_json"]),
        }

    async def complete_authorization(
        self,
        *,
        state: str,
        code: str,
        secret_resolver,
    ) -> dict[str, str]:
        flow = self._get_flow(state)
        if flow is None:
            raise ValueError("OAuth state is invalid, expired, or already used")
        auth = flow["auth"]
        token_url = str(auth["token_url"])
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(auth["redirect_uri"]),
            "client_id": str(auth["client_id"]),
            "code_verifier": flow["verifier"],
        }
        client_secret_ref = auth.get("client_secret_ref")
        if client_secret_ref:
            client_secret = secret_resolver(str(client_secret_ref))
            if not client_secret:
                raise ValueError("OAuth client secret is not configured")
            form["client_secret"] = client_secret
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.post(token_url, data=form)
        if response.is_error:
            raise ValueError(f"OAuth token endpoint returned HTTP {response.status_code}")
        try:
            token_data = response.json()
        except ValueError as exc:
            raise ValueError("OAuth token endpoint returned invalid JSON") from exc
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("OAuth token endpoint returned no access token")
        self.save_tokens(
            user_id=flow["user_id"],
            capability_id=flow["capability_id"],
            auth=auth,
            access_token=access_token,
            refresh_token=token_data.get("refresh_token"),
            expires_at=(time.time() + float(token_data["expires_in"]))
            if token_data.get("expires_in") is not None
            else None,
            scope=str(token_data.get("scope") or ""),
        )
        with self._connect() as db:
            db.execute(
                "DELETE FROM capability_oauth_flows WHERE state_hash = ?",
                (self._state_hash(state),),
            )
        return {"user_id": flow["user_id"], "capability_id": flow["capability_id"]}

    def save_tokens(
        self,
        *,
        user_id: str,
        capability_id: str,
        auth: dict[str, Any],
        access_token: str,
        refresh_token: str | None,
        expires_at: float | None,
        scope: str,
    ) -> None:
        safe_auth = {
            key: value
            for key, value in auth.items()
            if key not in {"client_secret", "access_token", "refresh_token"}
        }
        with self._connect() as db:
            db.execute(
                """INSERT INTO capability_oauth_tokens
                   (user_id, capability_id, access_token, refresh_token, expires_at, scope, auth_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, capability_id) DO UPDATE SET
                     access_token=excluded.access_token,
                     refresh_token=excluded.refresh_token,
                     expires_at=excluded.expires_at,
                     scope=excluded.scope,
                     auth_json=excluded.auth_json""",
                (
                    user_id,
                    capability_id,
                    self._cipher.encrypt(access_token.encode()).decode(),
                    self._cipher.encrypt(refresh_token.encode()).decode() if refresh_token else None,
                    expires_at,
                    scope,
                    json.dumps(safe_auth),
                ),
            )

    def status(self, user_id: str, capability_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT scope FROM capability_oauth_tokens WHERE user_id=? AND capability_id=?",
                (user_id, capability_id),
            ).fetchone()
        return {"connected": row is not None, "scope": row["scope"] if row else None}

    def disconnect(self, user_id: str, capability_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM capability_oauth_tokens WHERE user_id=? AND capability_id=?",
                (user_id, capability_id),
            )
        return cursor.rowcount > 0

    async def get_access_token(
        self,
        user_id: str,
        capability_id: str,
        *,
        secret_resolver,
    ) -> str | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM capability_oauth_tokens WHERE user_id=? AND capability_id=?",
                (user_id, capability_id),
            ).fetchone()
        if row is None:
            return None
        try:
            access_token = self._cipher.decrypt(row["access_token"].encode()).decode()
            refresh_token = (
                self._cipher.decrypt(row["refresh_token"].encode()).decode()
                if row["refresh_token"]
                else None
            )
        except InvalidToken:
            return None
        expiry = row["expires_at"]
        if expiry is None or float(expiry) > time.time() + 30:
            return access_token
        if not refresh_token:
            return None
        auth = json.loads(row["auth_json"])
        form = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": str(auth["client_id"]),
        }
        secret_ref = auth.get("client_secret_ref")
        if secret_ref:
            secret = secret_resolver(str(secret_ref))
            if not secret:
                return None
            form["client_secret"] = secret
        async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.post(str(auth["token_url"]), data=form)
        if response.is_error:
            return None
        try:
            token_data = response.json()
        except ValueError:
            return None
        new_access = token_data.get("access_token")
        if not isinstance(new_access, str) or not new_access:
            return None
        new_refresh = token_data.get("refresh_token") or refresh_token
        self.save_tokens(
            user_id=user_id,
            capability_id=capability_id,
            auth=auth,
            access_token=new_access,
            refresh_token=new_refresh,
            expires_at=time.time() + float(token_data["expires_in"])
            if token_data.get("expires_in") is not None
            else None,
            scope=str(token_data.get("scope") or row["scope"] or ""),
        )
        return new_access