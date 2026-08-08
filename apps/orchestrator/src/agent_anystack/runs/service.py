"""Chat run orchestration — pack, envelope, gold tools, adapter, journal, extract."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from agent_anystack.adapters import StackError
from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.channel_history import ChannelHistoryStore
from agent_anystack.domain.agent import AgentConfig
from agent_anystack.envelope import build_office_envelope
from agent_anystack.hitl.autonomy import compute_effective
from agent_anystack.limits import resolve_run_limits, truncate_messages_to_input
from agent_anystack.memory import ExtractJob, OkfStore, pack_memory_sections
from agent_anystack.office import OfficeRepository
from agent_anystack.runs.journal import JournalEntry, RunJournal, new_run_id, utc_now
from agent_anystack.tools.gold import GOLD_TOOL_SCHEMAS, execute_gold_tool

SUPPORTED_STACKS = frozenset({"openai-compatible"})
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
        channel_history: ChannelHistoryStore | None = None,
        recent_history_days: int = 7,
        recent_history_char_budget: int = 6_000,
        office_model: str = "llama3.2",
        openai_compatible_timeout: float = 300.0,
    ) -> None:
        self.repo = repo
        self.journal = journal
        self.adapter = OpenAICompatibleAdapter(
            openai_compatible_base_url,
            timeout=openai_compatible_timeout,
        )
        self.okf = okf
        self.pack_token_budget = pack_token_budget
        self.okf_extract_enabled = okf_extract_enabled
        self.channel_history = channel_history
        self.recent_history_days = recent_history_days
        self.recent_history_char_budget = recent_history_char_budget
        self.office_model = office_model

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

        if agent.stack not in SUPPORTED_STACKS:
            yield {
                "type": "error",
                "message": (
                    f"unsupported stack '{agent.stack}' — "
                    f"v0 supports: {', '.join(sorted(SUPPORTED_STACKS))}"
                ),
                "code": "unsupported_stack",
            }
            return

        org = self.repo.load_org()
        orc = self.repo.load_orchestrator()
        limits = resolve_run_limits(model=agent.model, orc=orc, agent=agent)
        run_id = new_run_id()
        started = utc_now()
        eff = compute_effective(org, agent)

        yield {
            "type": "meta",
            "run_id": run_id,
            "agent_id": agent.id,
            "user_id": user_id,
            "model": agent.model,
            "num_ctx": limits.num_ctx,
            "max_input_tokens": limits.max_input_tokens,
            "max_output_tokens": limits.max_output_tokens,
        }

        envelope = build_office_envelope(
            agent=agent,
            user_id=user_id,
            effective_autonomy=eff,
        )
        persona = self.repo.read_persona(agent)
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
        parts = [envelope, persona, *memory_sections]
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
        try:
            async for event in self._run_with_gold_tools(
                model=agent.model,
                messages=messages,
                agent=agent,
                user_id=user_id,
                run_id=run_id,
                num_ctx=limits.num_ctx,
                max_tokens=limits.max_output_tokens,
            ):
                if event.get("type") == "token":
                    assistant_parts.append(event.get("text") or "")
                yield event
        except StackError as exc:
            status = "error"
            error = str(exc)
            yield {"type": "error", "message": error, "code": exc.code}
        except Exception as exc:  # noqa: BLE001 — surface to client
            status = "error"
            error = f"unexpected: {exc}"
            yield {"type": "error", "message": error, "code": "internal"}

        self.journal.append(
            JournalEntry(
                run_id=run_id,
                agent_id=agent.id,
                user_id=user_id,
                team=agent.team,
                project_id=agent.workspace.project_id if agent.workspace else None,
                channel=channel,
                stack=agent.stack,
                model=agent.model,
                effective_autonomy=eff,
                status=status,
                started_at=started,
                ended_at=utc_now(),
                error=error,
            )
        )

        done: dict = {"type": "done", "run_id": run_id, "status": status}
        if (
            self.okf_extract_enabled
            and status == "ok"
            and ("".join(assistant_parts).strip() or message.strip())
        ):
            done["extract"] = ExtractJob(
                run_id=run_id,
                agent_id=agent.id,
                user_id=user_id,
                team=agent.team,
                model=self.office_model,
                user_message=message,
                assistant_text="".join(assistant_parts),
                project_id=agent.workspace.project_id if agent.workspace else None,
            )
        yield done

    async def _run_with_gold_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        agent: AgentConfig,
        user_id: str,
        run_id: str,
        num_ctx: int | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict]:
        """Tool loop for gold CRUD; then emit assistant text as tokens."""
        for _round in range(MAX_TOOL_ROUNDS):
            try:
                turn = await self.adapter.complete_chat_turn(
                    model=model,
                    messages=messages,
                    tools=GOLD_TOOL_SCHEMAS,
                    num_ctx=num_ctx,
                    max_tokens=max_tokens,
                )
            except StackError as exc:
                # Some hosts reject tools — fall back to plain stream once.
                if _round == 0 and _looks_like_tools_unsupported(exc):
                    async for token in self.adapter.stream_chat(
                        model=model,
                        messages=messages,
                        num_ctx=num_ctx,
                        max_tokens=max_tokens,
                    ):
                        yield {"type": "token", "text": token}
                    return
                raise
            if turn.tool_calls:
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": turn.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        }
                        for tc in turn.tool_calls
                    ],
                }
                messages.append(assistant_msg)
                for tc in turn.tool_calls:
                    result = execute_gold_tool(
                        tc.name,
                        tc.arguments,
                        repo=self.repo,
                        agent=agent,
                        user_id=user_id,
                        run_id=run_id,
                    )
                    yield {
                        "type": "tool",
                        "name": tc.name,
                        "ok": not result.startswith("error:"),
                        "detail": result[:200],
                    }
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
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


def _chunk_text(text: str, size: int) -> list[str]:
    if size <= 0 or len(text) <= size:
        return [text] if text else []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _looks_like_tools_unsupported(exc: StackError) -> bool:
    msg = str(exc).lower()
    return "tool" in msg and (
        "not support" in msg
        or "unsupported" in msg
        or "unknown field" in msg
        or "does not support" in msg
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
