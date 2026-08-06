"""Chat run orchestration — pack stub, envelope, adapter, journal."""

from collections.abc import AsyncIterator
from pathlib import Path

from agent_anystack.adapters import StackError
from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.domain.agent import AgentConfig
from agent_anystack.domain.org import OrgConfig
from agent_anystack.envelope import build_office_envelope
from agent_anystack.office import OfficeRepository
from agent_anystack.runs.journal import JournalEntry, RunJournal, new_run_id, utc_now

SUPPORTED_STACKS = frozenset({"openai-compatible"})


def effective_autonomy(org: OrgConfig, agent: AgentConfig) -> int:
    agent_max = agent.autonomy.max if agent.autonomy.max is not None else 100
    effective_max = min(org.max_autonomy, agent_max)
    return max(0, min(agent.autonomy.default, effective_max))


class ChatRunService:
    def __init__(
        self,
        repo: OfficeRepository,
        journal: RunJournal,
        openai_compatible_base_url: str,
    ) -> None:
        self.repo = repo
        self.journal = journal
        self.adapter = OpenAICompatibleAdapter(openai_compatible_base_url)

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
        run_id = new_run_id()
        started = utc_now()
        eff = effective_autonomy(org, agent)

        yield {
            "type": "meta",
            "run_id": run_id,
            "agent_id": agent.id,
            "user_id": user_id,
            "model": agent.model,
        }

        envelope = build_office_envelope(
            agent=agent,
            user_id=user_id,
            effective_autonomy=eff,
        )
        persona = self.repo.read_persona(agent)
        # Memory pack C(a,p,u) later — empty stub for P8
        system = envelope + "\n\n---\n\n" + persona
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ]

        status = "ok"
        error: str | None = None
        try:
            async for token in self.adapter.stream_chat(
                model=agent.model,
                messages=messages,
            ):
                yield {"type": "token", "text": token}
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
        yield {"type": "done", "run_id": run_id, "status": status}


def journal_path_from_database_url(database_url: str, data_fallback: Path) -> Path:
    """Prefer data/ next to sqlite file; else data_fallback/journal.jsonl."""
    if database_url.startswith("sqlite:///"):
        raw = database_url.removeprefix("sqlite:///")
        # sqlite:////data/office.db → /data/office.db
        if raw.startswith("/") and not raw.startswith("///"):
            db = Path(raw)
        else:
            db = Path(raw)
        return db.parent / "journal.jsonl"
    return data_fallback / "journal.jsonl"
