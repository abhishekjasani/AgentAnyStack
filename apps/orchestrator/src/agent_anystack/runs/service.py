"""Chat run orchestration — pack, envelope, gold tools / OpenCode harness, journal, extract."""

from __future__ import annotations

import os
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from agent_anystack.adapters import StackError
from agent_anystack.adapters.bedrock import BedrockAdapter
from agent_anystack.adapters.bedrock_store import (
    BedrockProviderStore,
    bedrock_data_dir,
    resolve_creds,
)
from agent_anystack.adapters.connections import (
    ConnectionDisabled,
    ConnectionNotFound,
    connection_store_from_database_url,
    resolve_desk_stack,
)
from agent_anystack.adapters.llm import OpenAICompatibleAdapter, TokenUsage
from agent_anystack.adapters.opencode import OpenCodeAdapter
from agent_anystack.adapters.stack_models import (
    StackSelectionError,
    resolve_desk_runtime,
)
from agent_anystack.adapters.thinking import append_thinking
from agent_anystack.channel_history import (
    ChannelHistoryStore,
    ChannelMessage,
    new_message_id,
    utc_now as channel_utc_now,
)
from agent_anystack.capabilities.binding import CapabilityBinding, build_bindings
from agent_anystack.capabilities.call_store import (
    CapabilityCallRecord,
    CapabilityCallStore,
    new_capability_call_id,
)
from agent_anystack.capabilities.catalog import (
    CapabilityCatalogItem,
    CapabilityCatalogService,
)
from agent_anystack.capabilities.registry import ToolContext, dispatch
from agent_anystack.capabilities.skills import render_registered_skill_prompt
from agent_anystack.capabilities.mcp.client import discover_mcp_bindings
from agent_anystack.domain.agent import AgentConfig
from agent_anystack.database import sqlite_path_from_database_url
from agent_anystack.envelope import build_office_envelope
from agent_anystack.hitl.autonomy import compute_effective
from agent_anystack.hitl import (
    ApprovalService,
    ApprovalStatus,
    ApprovalStore,
    GATED_ACTION_TYPE,
)
from agent_anystack.hitl.service import ApprovalGateDeniedError
from agent_anystack.limits import (
    approx_tokens,
    resolve_run_limits,
    truncate_messages_to_input,
)
from agent_anystack.memory import ExtractJob, OkfStore, pack_memory_sections
from agent_anystack.office import OfficeRepository
from agent_anystack.runs.journal import JournalEntry, RunJournal, new_run_id, utc_now
from agent_anystack.security.capability_oauth import CapabilityOAuthStore

MAX_TOOL_ROUNDS = 6
_TOKEN_CHUNK = 48


class ChatRunService:
    def __init__(
        self,
        repo: OfficeRepository,
        journal: RunJournal,
        openai_compatible_base_url: str,
        okf: OkfStore,
        pack_token_budget: int = 8000,
        okf_extract_enabled: bool = True,
        okf_extract_llm: bool = True,
        okf_extract_remember_lines: bool = True,
        channel_history: ChannelHistoryStore | None = None,
        recent_history_days: int = 7,
        recent_history_char_budget: int = 6_000,
        office_model: str = "llama3.2",
        openai_compatible_timeout: float = 300.0,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        aws_session_token: str = "",
        aws_region: str = "us-east-1",
        aws_bearer_token_bedrock: str = "",
        database_url: str = "sqlite:///./data/office.db",
        opencode_default_context_limit: int | None = None,
        opencode_default_output_limit: int | None = None,
        approval_service: ApprovalService | None = None,
        approver_mode: str = "permissive",
        org_admins: str = "",
        capability_oauth_encryption_key: str = "",
    ) -> None:
        self.repo = repo
        self.capability_catalog = CapabilityCatalogService(repo.root)
        self.journal = journal
        self.adapter = OpenAICompatibleAdapter(
            openai_compatible_base_url,
            timeout=openai_compatible_timeout,
        )
        self._env_aws_access_key_id = aws_access_key_id
        self._env_aws_secret_access_key = aws_secret_access_key
        self._env_aws_session_token = aws_session_token
        self._env_aws_region = aws_region
        self._env_aws_bearer_token_bedrock = aws_bearer_token_bedrock
        self._openai_compatible_timeout = openai_compatible_timeout
        self._openai_compatible_base_url = openai_compatible_base_url
        self._opencode_default_context_limit = opencode_default_context_limit
        self._opencode_default_output_limit = opencode_default_output_limit
        self.database_url = database_url
        self.capability_calls = CapabilityCallStore(
            sqlite_path_from_database_url(database_url)
        )
        self.approvals = approval_service or ApprovalService(
            ApprovalStore(sqlite_path_from_database_url(database_url)),
            journal,
            repo,
            approver_mode=approver_mode,
            org_admins=org_admins,
        )
        self._bedrock_store = BedrockProviderStore(bedrock_data_dir(database_url))
        self._connections = connection_store_from_database_url(database_url)
        self.okf = okf
        self.pack_token_budget = pack_token_budget
        self.okf_extract_enabled = okf_extract_enabled
        self.okf_extract_llm = okf_extract_llm
        self.okf_extract_remember_lines = okf_extract_remember_lines
        self.channel_history = channel_history
        self.recent_history_days = recent_history_days
        self.recent_history_char_budget = recent_history_char_budget
        self.office_model = office_model
        self._capability_oauth = (
            CapabilityOAuthStore(
                sqlite_path_from_database_url(database_url),
                capability_oauth_encryption_key,
            )
            if capability_oauth_encryption_key
            else None
        )

    def _bedrock_adapter(self, connection_id: str | None = None) -> BedrockAdapter:
        if connection_id:
            conn = self._connections.get(connection_id)
            if conn and conn.meta:
                meta = conn.meta
                auth = meta.get("auth") or "api_key"
                region = meta.get("region") or self._env_aws_region
                api_key = meta.get("api_key") or self._env_aws_bearer_token_bedrock
                akid = meta.get("aws_access_key_id") or self._env_aws_access_key_id
                secret = meta.get("aws_secret_access_key") or self._env_aws_secret_access_key
                session_token = meta.get("aws_session_token") or self._env_aws_session_token
                return BedrockAdapter(
                    access_key_id=akid,
                    secret_access_key=secret,
                    session_token=session_token,
                    api_key=api_key,
                    auth_mode=auth,
                    region=region,
                    timeout=self._openai_compatible_timeout,
                )
        creds = resolve_creds(
            self._bedrock_store,
            env_access_key_id=self._env_aws_access_key_id,
            env_secret_access_key=self._env_aws_secret_access_key,
            env_session_token=self._env_aws_session_token,
            env_region=self._env_aws_region,
            env_api_key=self._env_aws_bearer_token_bedrock,
        )
        return BedrockAdapter(
            access_key_id=creds.access_key_id,
            secret_access_key=creds.secret_access_key,
            session_token=creds.session_token,
            api_key=creds.api_key,
            auth_mode=creds.auth_mode,
            region=creds.region,
            timeout=self._openai_compatible_timeout,
        )

    def _adapter_for(
        self, stack: str, connection_id: str | None = None
    ) -> OpenAICompatibleAdapter | BedrockAdapter:
        """Build chat adapter for inference stacks (caller already resolved)."""
        if stack == "bedrock":
            return self._bedrock_adapter(connection_id)
        if stack == "openai-compatible":
            if connection_id:
                conn = self._connections.get(connection_id)
                if conn and conn.meta:
                    base_url = (conn.meta.get("base_url") or "").strip() or self._openai_compatible_base_url
                    api_key = (conn.meta.get("api_key") or "").strip() or None
                    return OpenAICompatibleAdapter(
                        base_url=base_url,
                        api_key=api_key,
                        timeout=self._openai_compatible_timeout,
                    )
            return self.adapter
        raise StackError(
            f"unsupported stack '{stack}'",
            code="unsupported_stack",
        )

    async def stream_agent_chat(
        self,
        *,
        agent_id: str,
        user_id: str,
        message: str,
        channel: str = "office_ui",
    ) -> AsyncIterator[dict]:
        agent = self.repo.get_agent(agent_id)
        if agent is None:
            yield {"type": "error", "message": f"agent not found: {agent_id}"}
            return

        try:
            stack, connection_id = resolve_desk_stack(
                connection_id=agent.connection_id,
                stack=agent.stack,
                store=self._connections,
                require_enabled=True,
            )
            runtime = resolve_desk_runtime(stack, agent.model)
        except (ConnectionNotFound, ConnectionDisabled) as exc:
            yield {
                "type": "error",
                "message": str(exc),
                "code": "connection",
            }
            return
        except StackSelectionError as exc:
            yield {
                "type": "error",
                "message": str(exc),
                "code": exc.code,
            }
            return
        except ValueError as exc:
            yield {
                "type": "error",
                "message": str(exc),
                "code": "connection",
            }
            return

        org = self.repo.load_org()
        orc = self.repo.load_orchestrator()
        limits = resolve_run_limits(model=runtime.model, orc=orc, agent=agent)
        run_id = new_run_id()
        started = utc_now()
        eff = compute_effective(org, agent)

        yield {
            "type": "meta",
            "run_id": run_id,
            "agent_id": agent.id,
            "user_id": user_id,
            "stack": runtime.stack,
            "connection_id": connection_id,
            "model": runtime.model,
            "max_input_tokens": limits.max_input_tokens,
            "max_output_tokens": limits.max_output_tokens,
        }

        envelope = build_office_envelope(
            agent=agent,
            user_id=user_id,
            effective_autonomy=eff,
        )
        persona = self.repo.read_persona(agent)
        skill_prompt = render_registered_skill_prompt(self.capability_catalog, agent)
        gold_notes = self.repo.list_gold_notes(agent, user_id)
        team_facts = self.okf.list_team_facts(agent.team)
        recent_messages = []
        if self.channel_history is not None and self.recent_history_days > 0:
            try:
                recent_messages = self.channel_history.list_recent(
                    user_id,
                    days=self.recent_history_days,
                    exclude_text=message,
                )
            except ValueError:
                recent_messages = []
        pack_budget = min(self.pack_token_budget, limits.max_input_tokens)
        memory_sections = pack_memory_sections(
            user_id=user_id,
            gold=gold_notes,
            team_facts=team_facts,
            pack_token_budget=pack_budget,
            recent_messages=recent_messages,
            recent_history_days=self.recent_history_days,
            recent_history_char_budget=min(
                self.recent_history_char_budget,
                pack_budget * 2,
            ),
        )
        parts = [envelope, persona]
        if skill_prompt:
            parts.append(skill_prompt)
        parts.extend(memory_sections)
        system = "\n\n---\n\n".join(parts)
        messages: list[dict[str, Any]] = truncate_messages_to_input(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            max_input_tokens=limits.max_input_tokens,
        )

        status = "ok"
        error: str | None = None
        assistant_parts: list[str] = []
        accumulated_usage = TokenUsage()
        try:
            if runtime.stack == "opencode":
                async for event in self._run_opencode(
                    agent=agent,
                    model=runtime.model,
                    messages=messages,
                    run_id=run_id,
                    user_id=user_id,
                ):
                    if event.get("type") == "token":
                        assistant_parts.append(event.get("text") or "")
                    elif event.get("type") == "usage":
                        inp = int(event.get("input_tokens") or event.get("prompt_tokens") or 0)
                        out = int(event.get("output_tokens") or event.get("completion_tokens") or 0)
                        tot = int(event.get("total_tokens") or (inp + out))
                        u = TokenUsage(
                            input_tokens=inp,
                            output_tokens=out,
                            total_tokens=tot,
                            reasoning_tokens=int(event.get("reasoning_tokens") or 0),
                            cost=float(event["cost"]) if event.get("cost") is not None else None,
                            estimated=bool(event.get("estimated", False)),
                        )
                        accumulated_usage = accumulated_usage.add(u)
                    if event.get("type") == "error":
                        status = "error"
                        error = event.get("message") or "opencode error"
                    if event.get("type") == "meta_extra":
                        continue
                    yield event
            else:
                adapter = self._adapter_for(runtime.stack, connection_id=connection_id)
                async for event in self._run_with_gold_tools(
                    adapter=adapter,
                    model=runtime.model,
                    messages=messages,
                    agent=agent,
                    user_id=user_id,
                    run_id=run_id,
                    max_tokens=limits.max_output_tokens,
                    stack=runtime.stack,
                    connection_id=connection_id,
                ):
                    if event.get("type") == "token":
                        assistant_parts.append(event.get("text") or "")
                    elif event.get("type") == "usage":
                        inp = int(event.get("input_tokens") or event.get("prompt_tokens") or 0)
                        out = int(event.get("output_tokens") or event.get("completion_tokens") or 0)
                        tot = int(event.get("total_tokens") or (inp + out))
                        u = TokenUsage(
                            input_tokens=inp,
                            output_tokens=out,
                            total_tokens=tot,
                            reasoning_tokens=int(event.get("reasoning_tokens") or 0),
                            cost=float(event["cost"]) if event.get("cost") is not None else None,
                            estimated=bool(event.get("estimated", False)),
                        )
                        accumulated_usage = accumulated_usage.add(u)
                    if event.get("type") == "error":
                        status = (
                            "pending_approval"
                            if event.get("code") == "approval_pending"
                            else "error"
                        )
                        error = event.get("message") or "chat error"
                    yield event
        except StackError as exc:
            status = "error"
            error = str(exc)
            yield {"type": "error", "message": error, "code": exc.code}
        except Exception as exc:  # noqa: BLE001 — surface to client
            status = "error"
            error = f"unexpected: {exc}"
            yield {"type": "error", "message": error, "code": "internal"}

        if (
            runtime.stack == "opencode"
            and status == "ok"
            and not "".join(assistant_parts).strip()
        ):
            status = "error"
            error = "opencode session went idle with no assistant tokens"
            yield {
                "type": "error",
                "message": error,
                "code": "opencode_no_tokens",
            }

        # If no usage was emitted by adapter or events, calculate fallback estimate
        if accumulated_usage.total_tokens == 0 and ("".join(assistant_parts).strip() or message.strip()):
            p_tokens = sum(approx_tokens(str(m.get("content") or "")) for m in messages)
            c_tokens = approx_tokens("".join(assistant_parts))
            accumulated_usage = TokenUsage(
                input_tokens=p_tokens,
                output_tokens=c_tokens,
                total_tokens=p_tokens + c_tokens,
                estimated=True,
            )
            yield {"type": "usage", **accumulated_usage.as_dict()}

        self.journal.append(
            JournalEntry(
                run_id=run_id,
                agent_id=agent.id,
                user_id=user_id,
                team=agent.team,
                project_id=agent.workspace.project_id if agent.workspace else None,
                channel=channel,
                stack=runtime.stack,
                model=runtime.model,
                effective_autonomy=eff,
                status=status,
                started_at=started,
                ended_at=utc_now(),
                error=error,
                connection_id=connection_id,
                input_tokens=accumulated_usage.input_tokens,
                output_tokens=accumulated_usage.output_tokens,
                prompt_tokens=accumulated_usage.input_tokens,
                completion_tokens=accumulated_usage.output_tokens,
                total_tokens=accumulated_usage.total_tokens,
                reasoning_tokens=accumulated_usage.reasoning_tokens if accumulated_usage.reasoning_tokens else None,
                cost=accumulated_usage.cost,
                estimated=accumulated_usage.estimated,
            )
        )

        done: dict = {
            "type": "done",
            "run_id": run_id,
            "status": status,
            "usage": accumulated_usage.as_dict(),
        }
        if (
            self.okf_extract_enabled
            and (self.okf_extract_llm or self.okf_extract_remember_lines)
            and status == "ok"
            and ("".join(assistant_parts).strip() or message.strip())
        ):
            done["extract"] = ExtractJob(
                run_id=run_id,
                agent_id=agent.id,
                user_id=user_id,
                team=agent.team,
                model=orc.model,
                user_message=message,
                assistant_text="".join(assistant_parts),
                project_id=agent.workspace.project_id if agent.workspace else None,
            )
        yield done

    async def _run_opencode(
        self,
        *,
        agent: AgentConfig,
        model: str,
        messages: list[dict[str, Any]],
        run_id: str,
        user_id: str,
    ) -> AsyncIterator[dict]:
        if agent.workspace is None or not (agent.workspace.path or "").strip():
            raise StackError(
                "opencode desk requires workspace.path (bind a project)",
                code="opencode_no_workspace",
            )
        cwd = Path(agent.workspace.path)
        system = ""
        user_message = ""
        for msg in messages:
            role = msg.get("role")
            content = str(msg.get("content") or "")
            if role == "system":
                system = content
            elif role == "user":
                user_message = content
        cid = (agent.connection_id or "opencode").strip() or "opencode"
        conn = self._connections.get(cid)
        pid = mid = ""
        extra_env: dict[str, str] | None = None
        cfg_hash = ""
        if conn is not None and conn.product == "opencode":
            from agent_anystack.adapters.opencode.providers import prepare_inject

            registered = conn.find_registered(model)
            if registered is not None:
                pid, mid = registered.provider_id, registered.model_id
            _cfg, extra_env, cfg_hash = prepare_inject(
                database_url=self.database_url,
                connection=conn,
                ollama_base_url=self._openai_compatible_base_url,
                env_access_key_id=self._env_aws_access_key_id,
                env_secret_access_key=self._env_aws_secret_access_key,
                env_session_token=self._env_aws_session_token,
                env_region=self._env_aws_region,
                env_api_key=self._env_aws_bearer_token_bedrock,
                store=self._connections,
                default_context_limit=self._opencode_default_context_limit,
                default_output_limit=self._opencode_default_output_limit,
            )
        harness = OpenCodeAdapter(
            database_url=self.database_url,
            timeout=self._openai_compatible_timeout,
        )
        async for event in harness.run_chat(
            cwd=cwd,
            model=model,
            system=system,
            user_message=user_message,
            run_id=run_id,
            agent_id=agent.id,
            user_id=user_id,
            connection_id=agent.connection_id or "opencode",
            provider_id=pid,
            model_id=mid,
            extra_env=extra_env,
            config_hash=cfg_hash,
        ):
            yield event

    async def _resolve_capability_oauth_token(
        self,
        user_id: str,
        capability_id: str,
    ) -> str | None:
        if self._capability_oauth is None:
            return None
        return await self._capability_oauth.get_access_token(
            user_id,
            capability_id,
            secret_resolver=os.environ.get,
        )

    async def _run_with_gold_tools(
        self,
        *,
        adapter: OpenAICompatibleAdapter | BedrockAdapter,
        model: str,
        messages: list[dict[str, Any]],
        agent: AgentConfig,
        user_id: str,
        run_id: str,
        max_tokens: int | None = None,
        stack: str = "openai-compatible",
        connection_id: str = "",
    ) -> AsyncIterator[dict]:
        """Tool loop for gold CRUD; then emit assistant text as tokens."""
        bindings = build_bindings(self.capability_catalog, agent)
        bindings.update(
            await discover_mcp_bindings(
                self.capability_catalog,
                agent,
                secret_resolver=os.environ.get,
                user_id=user_id,
                oauth_token_resolver=self._resolve_capability_oauth_token,
            )
        )
        for _round in range(MAX_TOOL_ROUNDS):
            try:
                turn = await adapter.complete_chat_turn(
                    model=model,
                    messages=messages,
                    tools=[binding.schema for binding in bindings.values()],
                    max_tokens=max_tokens,
                )
            except StackError as exc:
                # Some hosts reject tools — fall back to plain stream once.
                if _round == 0 and _looks_like_tools_unsupported(exc):
                    async for ev in adapter.stream_chat_events(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                    ):
                        if ev.get("type") == "thinking":
                            append_thinking(
                                self.database_url,
                                run_id,
                                ev.get("text") or "",
                            )
                        yield ev
                    return
                raise

            if turn.usage:
                yield {"type": "usage", **turn.usage.as_dict()}
            else:
                p_tokens = sum(approx_tokens(str(m.get("content") or "")) for m in messages)
                c_tokens = approx_tokens(turn.content or "") + approx_tokens(turn.reasoning or "")
                est_usage = TokenUsage(
                    input_tokens=p_tokens,
                    output_tokens=c_tokens,
                    total_tokens=p_tokens + c_tokens,
                    estimated=True,
                )
                yield {"type": "usage", **est_usage.as_dict()}

            if turn.reasoning:
                append_thinking(self.database_url, run_id, turn.reasoning)
                for chunk in _chunk_text(turn.reasoning, _TOKEN_CHUNK):
                    yield {"type": "thinking", "text": chunk}

            if turn.tool_calls:
                for call_index, tool_call in enumerate(turn.tool_calls):
                    messages.append(
                        {
                            "role": "assistant",
                            "content": turn.content or "" if call_index == 0 else "",
                            "tool_calls": [
                                {
                                    "id": tool_call.provider_tool_call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_call.name,
                                        "arguments": tool_call.arguments,
                                    },
                                }
                            ],
                        }
                    )
                    binding = bindings.get(tool_call.name)
                    if binding is None:
                        result = "error: unknown tool"
                        blocked_event = None
                    else:
                        result, blocked_event = await self._dispatch_capability_call(
                            binding,
                            tool_call.arguments,
                            agent=agent,
                            user_id=user_id,
                            run_id=run_id,
                            provider_tool_call_id=tool_call.provider_tool_call_id,
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            stack=stack,
                            connection_id=connection_id or agent.connection_id or "",
                        )
                    yield {
                        "type": "tool",
                        "name": tool_call.name,
                        "ok": not result.startswith("error:"),
                        "detail": result[:200],
                    }
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.provider_tool_call_id,
                            "content": result,
                        }
                    )
                    if blocked_event is not None:
                        yield blocked_event
                        return
                continue

            text = turn.content or ""
            if text:
                for chunk in _chunk_text(text, _TOKEN_CHUNK):
                    yield {"type": "token", "text": chunk}
            return

        yield {
            "type": "error",
            "message": f"tool loop exceeded {MAX_TOOL_ROUNDS} rounds",
            "code": "tool_loop_limit",
        }

    async def _dispatch_capability_call(
        self,
        binding: Any,
        arguments: dict[str, Any] | str | None,
        *,
        agent: AgentConfig,
        user_id: str,
        run_id: str,
        provider_tool_call_id: str,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None,
        stack: str,
        connection_id: str,
    ) -> tuple[str, dict[str, Any] | None]:
        item = binding.item
        approval_id: str | None = None
        mode = item.approval_mode
        blocked_event: dict[str, Any] | None = None
        capability_call_id = new_capability_call_id()

        if mode != "never":
            self.capability_calls.create_pending(
                CapabilityCallRecord(
                    capability_call_id=capability_call_id or new_capability_call_id(),
                    approval_id=None,
                    run_id=run_id,
                    provider_tool_call_id=provider_tool_call_id,
                    agent_id=agent.id,
                    user_id=user_id,
                    team=agent.team,
                    project_id=agent.workspace.project_id if agent.workspace else None,
                    stack=stack,
                    connection_id=connection_id,
                    model=model,
                    max_tokens=max_tokens,
                    capability=item.model_dump(mode="json"),
                    binding_schema=binding.schema,
                    callable_name=binding.callable_name,
                    arguments=arguments if isinstance(arguments, str) else json.dumps(arguments or {}),
                    messages=messages,
                )
            )
            action_type = GATED_ACTION_TYPE if mode == "autonomy" else "capability_call"
            description = binding.schema["function"].get("description") or item.name
            try:
                proposal = self.approvals.propose(
                    requester=user_id,
                    agent_id=agent.id,
                    team=agent.team,
                    summary=f"Capability call: {description} ({binding.callable_name})",
                    action_type=action_type,
                    run_id=run_id,
                    project_id=agent.workspace.project_id if agent.workspace else None,
                    capability_call_id=capability_call_id,
                )
                approval_id = proposal.card.id
                if capability_call_id:
                    self.capability_calls.link_approval(
                        capability_call_id,
                        approval_id,
                    )
                if proposal.card.status == ApprovalStatus.pending_human:
                    result = f"error: capability call requires approval: {approval_id}"
                    call_status = "pending"
                    blocked_event = {
                        "type": "error",
                        "message": result.removeprefix("error: "),
                        "code": "approval_pending",
                        "approval_id": approval_id,
                    }
                elif proposal.card.status == ApprovalStatus.denied:
                    if capability_call_id:
                        self.capability_calls.fail_pending(
                            capability_call_id,
                            stage="approval",
                            error="Denied by autonomy gate",
                        )
                    result = f"error: capability call denied: {approval_id}"
                    call_status = "denied"
                    blocked_event = {
                        "type": "error",
                        "message": result.removeprefix("error: "),
                        "code": "capability_denied",
                        "approval_id": approval_id,
                    }
                else:
                    claimed = self.capability_calls.claim(capability_call_id or "")
                    if claimed is None:
                        result = "error: capability call could not be claimed"
                        call_status = "failed"
                        blocked_event = {
                            "type": "error",
                            "message": result.removeprefix("error: "),
                            "code": "capability_failed",
                            "capability_call_id": capability_call_id,
                        }
                    else:
                        try:
                            result = await self._execute_binding(
                                binding,
                                arguments,
                                agent=agent,
                                user_id=user_id,
                                run_id=run_id,
                                capability_call_id=capability_call_id,
                            )
                        except Exception as exc:  # noqa: BLE001
                            result = f"error: capability dispatch failed ({type(exc).__name__})"
                        failed = result.startswith("error:")
                        uncertain = failed and "timeout" in result.lower()
                        call_status = "uncertain" if uncertain else "failed" if failed else "succeeded"
                        self.capability_calls.finish(
                            claimed.capability_call_id,
                            status=call_status if call_status in {"failed", "uncertain"} else "succeeded",
                            result=result,
                            error_stage="api" if failed and binding.kind.value == "api" else "dispatch" if failed else None,
                            error=result if failed else None,
                        )
                        if failed:
                            blocked_event = {
                                "type": "error",
                                "message": result.removeprefix("error: "),
                                "code": "capability_uncertain" if uncertain else "capability_failed",
                                "capability_call_id": capability_call_id,
                            }
            except ApprovalGateDeniedError as exc:
                approval_id = exc.approval_id
                if capability_call_id:
                    self.capability_calls.fail_pending(
                        capability_call_id,
                        stage="approval",
                        error=str(exc),
                    )
                result = f"error: capability call denied: {approval_id or exc}"
                call_status = "denied"
                blocked_event = {
                    "type": "error",
                    "message": result.removeprefix("error: "),
                    "code": "capability_denied",
                    "approval_id": approval_id,
                }
            except Exception as exc:  # noqa: BLE001 — fail checkpoint; do not retry
                if capability_call_id:
                    self.capability_calls.fail_pending(
                        capability_call_id,
                        stage="approval",
                        error=f"Approval proposal failed: {type(exc).__name__}",
                    )
                raise
        else:
            result = await self._execute_binding(
                binding,
                arguments,
                agent=agent,
                user_id=user_id,
                run_id=run_id,
                capability_call_id=capability_call_id,
            )
            call_status = "failed" if result.startswith("error:") else "succeeded"

        now = utc_now()
        self.journal.append(
            JournalEntry(
                run_id=run_id,
                agent_id=agent.id,
                user_id=user_id,
                team=agent.team,
                project_id=agent.workspace.project_id if agent.workspace else None,
                channel="office_ui",
                stack="capability",
                model="",
                effective_autonomy=compute_effective(self.repo.load_org(), agent),
                status="capability_call",
                started_at=now,
                ended_at=now,
                approval_id=approval_id,
                entry_type="capability_call",
                capability_id=item.id,
                capability_kind=binding.kind.value,
                callable_name=binding.callable_name,
                operation=binding.operation,
                approval_mode=mode,
                call_status=call_status,
                capability_call_id=capability_call_id,
            )
        )
        return result, blocked_event

    async def _execute_binding(
        self,
        binding: Any,
        arguments: dict[str, Any] | str | None,
        *,
        agent: AgentConfig,
        user_id: str,
        run_id: str,
        capability_call_id: str | None = None,
    ) -> str:
        return await dispatch(
            binding,
            arguments,
            ToolContext(
                repo=self.repo,
                agent=agent,
                user_id=user_id,
                run_id=run_id,
                capability_call_id=capability_call_id,
                oauth_token_resolver=self._resolve_capability_oauth_token,
            ),
        )

    async def resume_approved_capability_call(
        self,
        capability_call_id: str,
    ) -> dict[str, str | None]:
        """Execute an approved checkpoint once, then continue its saved model turn."""
        record = self.capability_calls.claim(capability_call_id)
        if record is None:
            current = self.capability_calls.get(capability_call_id)
            return {
                "status": current.status if current else "not_found",
                "assistant_text": None,
                "error": "Capability call is not pending; automatic retry is disabled.",
            }

        agent = self.repo.get_agent(record.agent_id)
        if agent is None:
            error = f"Agent no longer exists: {record.agent_id}"
            self.capability_calls.finish(
                capability_call_id,
                status="failed",
                error_stage="restore",
                error=error,
            )
            return {"status": "failed", "assistant_text": None, "error": error}

        try:
            item = CapabilityCatalogItem.model_validate(record.capability)
            binding = CapabilityBinding(
                callable_name=record.callable_name,
                kind=item.kind,
                item=item,
                operation=record.callable_name,
                schema=record.binding_schema,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"Could not restore approved capability: {type(exc).__name__}"
            self.capability_calls.finish(
                capability_call_id,
                status="failed",
                error_stage="restore",
                error=error,
            )
            return {"status": "failed", "assistant_text": None, "error": error}

        try:
            result = await self._execute_binding(
                binding,
                record.arguments,
                agent=agent,
                user_id=record.user_id,
                run_id=record.run_id,
                capability_call_id=capability_call_id,
            )
        except Exception as exc:  # noqa: BLE001 — terminal; never auto-retry
            error = f"Capability execution failed: {type(exc).__name__}"
            self.capability_calls.finish(
                capability_call_id,
                status="failed",
                error_stage="dispatch",
                error=error,
            )
            self._journal_resumed_call(record, "failed", error)
            return {"status": "failed", "assistant_text": None, "error": error}

        if result.startswith("error:"):
            uncertain = "timeout" in result.lower()
            status = "uncertain" if uncertain else "failed"
            self.capability_calls.finish(
                capability_call_id,
                status=status,
                result=result,
                error_stage="api" if item.kind.value == "api" else "dispatch",
                error=result,
            )
            self._journal_resumed_call(record, status, result)
            return {"status": status, "assistant_text": None, "error": result}

        self.capability_calls.finish(
            capability_call_id,
            status="succeeded",
            result=result,
        )
        self._journal_resumed_call(record, "succeeded", None)

        messages = list(record.messages)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": record.provider_tool_call_id,
                "content": result,
            }
        )
        try:
            adapter = self._adapter_for(record.stack, connection_id=record.connection_id)
            assistant_parts: list[str] = []
            continuation_error: str | None = None
            pending_approval_id: str | None = None
            async for event in self._run_with_gold_tools(
                adapter=adapter,
                model=record.model,
                messages=messages,
                agent=agent,
                user_id=record.user_id,
                run_id=record.run_id,
                max_tokens=record.max_tokens,
                stack=record.stack,
                connection_id=record.connection_id,
            ):
                if event.get("type") == "token":
                    assistant_parts.append(str(event.get("text") or ""))
                elif event.get("type") == "error":
                    continuation_error = str(event.get("message") or "Model continuation failed")
                    pending_approval_id = event.get("approval_id")
            assistant_text = "".join(assistant_parts).strip()
        except Exception as exc:  # noqa: BLE001
            error = f"Model continuation failed: {type(exc).__name__}"
            self._journal_resume_failure(record, error)
            return {"status": "continuation_failed", "assistant_text": None, "error": error}

        if assistant_text and self.channel_history is not None:
            self.channel_history.append(
                record.user_id,
                ChannelMessage(
                    id=new_message_id(),
                    role="assistant",
                    text=assistant_text,
                    created_at=channel_utc_now(),
                    mode="agent",
                    agent_id=record.agent_id,
                    run_id=record.run_id,
                ),
            )
        if pending_approval_id:
            return {
                "status": "pending_approval",
                "assistant_text": assistant_text or None,
                "error": continuation_error,
                "approval_id": pending_approval_id,
            }
        if continuation_error:
            self._journal_resume_failure(record, continuation_error)
            return {
                "status": "continuation_failed",
                "assistant_text": assistant_text or None,
                "error": continuation_error,
            }
        return {"status": "completed", "assistant_text": assistant_text or None, "error": None}

    def _journal_resume_failure(
        self,
        record: CapabilityCallRecord,
        error: str,
    ) -> None:
        agent = self.repo.get_agent(record.agent_id)
        effective = compute_effective(self.repo.load_org(), agent) if agent else 0
        now = utc_now()
        self.journal.append(
            JournalEntry(
                run_id=record.run_id,
                agent_id=record.agent_id,
                user_id=record.user_id,
                team=record.team,
                project_id=record.project_id,
                channel="office_ui",
                stack=record.stack,
                model=record.model,
                effective_autonomy=effective,
                status="resume_failed",
                started_at=now,
                ended_at=now,
                error=error,
                approval_id=record.approval_id,
                entry_type="resume",
                capability_call_id=record.capability_call_id,
            )
        )

    def reject_pending_capability_call(self, capability_call_id: str) -> None:
        self.capability_calls.fail_pending(
            capability_call_id,
            stage="approval",
            error="Rejected by approver",
        )

    def _journal_resumed_call(
        self,
        record: CapabilityCallRecord,
        call_status: str,
        error: str | None,
    ) -> None:
        item = CapabilityCatalogItem.model_validate(record.capability)
        self.journal.append(
            JournalEntry(
                run_id=record.run_id,
                agent_id=record.agent_id,
                user_id=record.user_id,
                team=record.team,
                project_id=record.project_id,
                channel="office_ui",
                stack="capability",
                model="",
                effective_autonomy=compute_effective(self.repo.load_org(), self.repo.get_agent(record.agent_id)),
                status="capability_call",
                started_at=utc_now(),
                ended_at=utc_now(),
                approval_id=record.approval_id,
                entry_type="capability_call",
                capability_id=item.id,
                capability_kind=item.kind.value,
                callable_name=record.callable_name,
                operation=record.callable_name,
                approval_mode=item.approval_mode,
                call_status=call_status,
                capability_call_id=record.capability_call_id,
                error=error,
            )
        )


def _chunk_text(text: str, size: int) -> list[str]:
    if size <= 0 or len(text) <= size:
        return [text] if text else []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _looks_like_tools_unsupported(exc: StackError) -> bool:
    msg = str(exc).lower()
    return (
        ("tool" in msg and (
            "not support" in msg
            or "unsupported" in msg
            or "unknown field" in msg
            or "does not support" in msg
        ))
        or "toolconfig" in msg
        or "tool use" in msg
    )


def journal_path_from_database_url(database_url: str, data_fallback: Path) -> Path:
    """Prefer data/ next to sqlite file; else data_fallback/journal.jsonl."""
    if database_url.startswith("sqlite:///"):
        raw = database_url.removeprefix("sqlite:///")
        if raw.startswith("/") and not raw.startswith("///"):
            db = Path(raw)
        else:
            db = Path(raw)
        return db.parent / "journal.jsonl"
    return data_fallback / "journal.jsonl"
