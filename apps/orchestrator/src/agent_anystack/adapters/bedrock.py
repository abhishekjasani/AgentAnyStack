"""AWS Bedrock Runtime adapter — IAM keys or Bedrock API key + Region.

Uses Converse / ConverseStream. Desk stack=`bedrock`; Office soft jobs stay openai-compatible.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

from agent_anystack.adapters.llm import ChatTurnResult, StackError, ToolCallRequest

_BEARER_LOCK = threading.Lock()


class BedrockAdapter:
    """Bedrock Converse API — IAM access key or Amazon Bedrock API key."""

    def __init__(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        session_token: str = "",
        api_key: str = "",
        auth_mode: str = "iam",
        timeout: float = 300.0,
    ) -> None:
        self.access_key_id = (access_key_id or "").strip()
        self.secret_access_key = (secret_access_key or "").strip()
        self.session_token = (session_token or "").strip()
        self.api_key = (api_key or "").strip()
        self.auth_mode = (auth_mode or "iam").strip() or "iam"
        self.region = (region or "").strip() or "us-east-1"
        self.timeout = timeout

    def uses_api_key(self) -> bool:
        return self.auth_mode == "api_key" and bool(self.api_key)

    def configured(self) -> bool:
        if self.uses_api_key():
            return True
        return bool(self.access_key_id and self.secret_access_key)

    @contextmanager
    def _bearer_env(self) -> Iterator[None]:
        if not self.uses_api_key():
            yield
            return
        iam_keys = (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        )
        with _BEARER_LOCK:
            prev_bearer = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
            prev_iam = {k: os.environ.get(k) for k in iam_keys}
            os.environ["AWS_BEARER_TOKEN_BEDROCK"] = self.api_key
            for k in iam_keys:
                os.environ.pop(k, None)
            try:
                yield
            finally:
                if prev_bearer is None:
                    os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)
                else:
                    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = prev_bearer
                for k, v in prev_iam.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def _boto_kwargs(self) -> dict[str, Any]:
        if not self.configured():
            raise StackError(
                "Bedrock not configured — set IAM access key + secret, "
                "or a Bedrock API key, plus region.",
                code="bedrock_not_configured",
            )
        try:
            from botocore.config import Config
        except ImportError as exc:
            raise StackError(
                "boto3 is required for the bedrock stack.",
                code="bedrock_missing_dep",
            ) from exc
        kwargs: dict[str, Any] = {
            "region_name": self.region,
            "config": Config(
                read_timeout=int(self.timeout),
                connect_timeout=min(60, int(self.timeout)),
                retries={"max_attempts": 2},
            ),
        }
        if not self.uses_api_key():
            kwargs["aws_access_key_id"] = self.access_key_id
            kwargs["aws_secret_access_key"] = self.secret_access_key
            if self.session_token:
                kwargs["aws_session_token"] = self.session_token
        return kwargs

    def _client(self, service: str = "bedrock-runtime") -> Any:
        try:
            import boto3
        except ImportError as exc:
            raise StackError(
                "boto3 is required for the bedrock stack.",
                code="bedrock_missing_dep",
            ) from exc
        return boto3.client(service, **self._boto_kwargs())

    async def test_credentials(self) -> dict[str, str]:
        """IAM: STS GetCallerIdentity. API key: Bedrock runtime probe (no model)."""
        if self.uses_api_key():
            return await self._test_api_key()

        def _run() -> dict[str, str]:
            client = self._client("sts")
            ident = client.get_caller_identity()
            return {
                "account": str(ident.get("Account") or ""),
                "arn": str(ident.get("Arn") or ""),
                "user_id": str(ident.get("UserId") or ""),
                "region": self.region,
                "auth": "iam",
            }

        try:
            return await asyncio.to_thread(_run)
        except StackError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StackError(
                f"AWS credential check failed: {exc}",
                code="bedrock_creds_invalid",
            ) from exc

    async def _test_api_key(self) -> dict[str, str]:
        import httpx

        url = (
            f"https://bedrock-runtime.{self.region}.amazonaws.com"
            "/model/_aas-creds-probe/converse"
        )
        try:
            async with httpx.AsyncClient(timeout=min(30.0, float(self.timeout))) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    json={
                        "messages": [
                            {"role": "user", "content": [{"text": "ping"}]}
                        ]
                    },
                )
        except httpx.HTTPError as exc:
            raise StackError(
                f"Bedrock API key check failed: {exc}",
                code="bedrock_creds_invalid",
            ) from exc
        if resp.status_code in (401, 403):
            raise StackError(
                f"Bedrock API key rejected ({resp.status_code})",
                code="bedrock_creds_invalid",
            )
        return {
            "account": "",
            "arn": "",
            "user_id": "",
            "region": self.region,
            "auth": "api_key",
        }

    async def list_models(self) -> list[str]:
        """Discover Bedrock foundation models or return curated Bedrock model IDs."""
        if not self.configured():
            return []
        if self.uses_api_key():
            return [
                "amazon.nova-lite-v1:0",
                "amazon.nova-micro-v1:0",
                "amazon.nova-pro-v1:0",
                "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "anthropic.claude-3-haiku-20240307-v1:0",
                "us.meta.llama3-3-70b-instruct-v1:0",
            ]

        def _run() -> list[str]:
            client = self._client("bedrock")
            res = client.list_foundation_models(byInferenceType="ON_DEMAND")
            summaries = res.get("modelSummaries") or []
            return [str(m["modelId"]) for m in summaries if m.get("modelId")]

        try:
            return await asyncio.to_thread(_run)
        except Exception:
            return [
                "amazon.nova-lite-v1:0",
                "amazon.nova-micro-v1:0",
                "amazon.nova-pro-v1:0",
                "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "anthropic.claude-3-haiku-20240307-v1:0",
                "us.meta.llama3-3-70b-instruct-v1:0",
            ]

    async def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        system, converse_messages = _to_converse_messages(messages)
        kwargs = _converse_kwargs(
            model=model,
            system=system,
            messages=converse_messages,
            max_tokens=max_tokens,
        )
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        def _run() -> None:
            try:
                with self._bearer_env():
                    client = self._client()
                    resp = client.converse_stream(**kwargs)
                    stream = resp.get("stream")
                    if stream is None:
                        queue.put_nowait(("error", StackError(
                            "Bedrock converse_stream returned no stream.",
                            code="bedrock_empty_stream",
                        )))
                        return
                    for event in stream:
                        if "contentBlockDelta" in event:
                            delta = event["contentBlockDelta"].get("delta") or {}
                            text = delta.get("text") or ""
                            if text:
                                queue.put_nowait(("delta", text))
                        elif "messageStop" in event:
                            break
                        elif "internalServerException" in event:
                            queue.put_nowait(("error", StackError(
                                str(event["internalServerException"]),
                                code="bedrock_http",
                            )))
                            return
                        elif "validationException" in event:
                            queue.put_nowait(("error", StackError(
                                str(event["validationException"]),
                                code="bedrock_validation",
                            )))
                            return
                    queue.put_nowait(("done", None))
            except StackError as exc:
                queue.put_nowait(("error", exc))
            except Exception as exc:  # noqa: BLE001
                queue.put_nowait((
                    "error",
                    StackError(f"Bedrock stream failed: {exc}", code="bedrock_error"),
                ))

        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(None, _run)
        while True:
            kind, payload = await queue.get()
            if kind == "delta":
                yield str(payload)
            elif kind == "done":
                await fut
                return
            elif kind == "error":
                await fut
                raise payload

    async def complete_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        turn = await self.complete_chat_turn(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return turn.content.strip()

    async def complete_chat_turn(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> ChatTurnResult:
        system, converse_messages = _to_converse_messages(messages)
        kwargs = _converse_kwargs(
            model=model,
            system=system,
            messages=converse_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
        )

        def _run() -> ChatTurnResult:
            try:
                with self._bearer_env():
                    client = self._client()
                    resp = client.converse(**kwargs)
            except StackError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise StackError(
                    f"Bedrock converse failed: {exc}",
                    code="bedrock_error",
                ) from exc
            return _parse_converse_output(resp)

        return await asyncio.to_thread(_run)


def _converse_kwargs(
    *,
    model: str,
    system: list[dict[str, str]],
    messages: list[dict[str, Any]],
    max_tokens: int | None,
    temperature: float | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not messages:
        messages = [{"role": "user", "content": [{"text": "(empty)"}]}]
    kwargs: dict[str, Any] = {
        "modelId": model,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    inference: dict[str, Any] = {}
    if max_tokens is not None and max_tokens > 0:
        inference["maxTokens"] = int(max_tokens)
    if temperature is not None:
        inference["temperature"] = float(temperature)
    if inference:
        kwargs["inferenceConfig"] = inference
    tool_cfg = _openai_tools_to_bedrock(tools)
    if tool_cfg:
        kwargs["toolConfig"] = tool_cfg
    return kwargs


def _openai_tools_to_bedrock(
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not tools:
        return None
    specs: list[dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") if t.get("type") == "function" else t
        if not isinstance(fn, dict):
            continue
        name = fn.get("name") or ""
        if not name:
            continue
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        specs.append({
            "toolSpec": {
                "name": name,
                "description": fn.get("description") or name,
                "inputSchema": {"json": params},
            }
        })
    if not specs:
        return None
    return {"tools": specs}


def _to_converse_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """OpenAI-style messages → Bedrock system + messages (no system role in messages)."""
    system: list[dict[str, str]] = []
    out: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def _flush_tools() -> None:
        nonlocal pending_tool_results
        if pending_tool_results:
            out.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []

    for msg in messages:
        role = (msg.get("role") or "").strip()
        content = msg.get("content")
        if role == "system":
            text = content if isinstance(content, str) else str(content or "")
            if text.strip():
                system.append({"text": text})
            continue
        if role == "tool":
            tool_id = str(msg.get("tool_call_id") or msg.get("id") or "tool")
            body = content if isinstance(content, str) else json.dumps(content)
            pending_tool_results.append({
                "toolResult": {
                    "toolUseId": tool_id,
                    "content": [{"text": body}],
                }
            })
            continue
        _flush_tools()
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            if isinstance(content, str) and content:
                blocks.append({"text": content})
            for tc in msg.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    parsed = {"raw": str(raw_args)}
                blocks.append({
                    "toolUse": {
                        "toolUseId": str(tc.get("id") or name),
                        "name": name,
                        "input": parsed if isinstance(parsed, dict) else {"value": parsed},
                    }
                })
            if blocks:
                out.append({"role": "assistant", "content": blocks})
            continue
        # user
        text = content if isinstance(content, str) else str(content or "")
        out.append({"role": "user", "content": [{"text": text or "(empty)"}]})

    _flush_tools()
    return system, out


def _parse_converse_output(resp: dict[str, Any]) -> ChatTurnResult:
    message = (resp.get("output") or {}).get("message") or {}
    blocks = message.get("content") or []
    texts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if "text" in block and block["text"]:
            texts.append(str(block["text"]))
        tool_use = block.get("toolUse")
        if isinstance(tool_use, dict) and tool_use.get("name"):
            inp = tool_use.get("input")
            if isinstance(inp, dict):
                args_s = json.dumps(inp, ensure_ascii=False)
            else:
                args_s = str(inp or "{}")
            tool_calls.append(
                ToolCallRequest(
                    id=str(tool_use.get("toolUseId") or tool_use["name"]),
                    name=str(tool_use["name"]),
                    arguments=args_s,
                )
            )
    return ChatTurnResult(content="".join(texts), tool_calls=tool_calls)
