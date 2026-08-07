"""Load/write office git tree (org + agent desks). No seed agents — create via API/UI."""

from pathlib import Path
from shutil import rmtree

import yaml

from agent_anystack.domain.agent import (
    AgentAutonomy,
    AgentConfig,
    AgentSummary,
    CreateAgentRequest,
    PersonaAxes,
    ToolsConfig,
)
from agent_anystack.domain.org import OrgConfig
from agent_anystack.domain.orchestrator import (
    OrchestratorConfig,
    OrchestratorConfigUpdate,
)
from agent_anystack.office.gold_notes import (
    SYSTEM_GOLD_ID,
    GoldNote,
    GoldNotesTooLargeError,
    ensure_gold_primer,
    make_system_note,
    new_gold_id,
    render_gold_notes,
    save_gold_notes,
    utc_now_iso,
)


class AgentExistsError(Exception):
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"agent already exists: {agent_id}")


class AutonomyCeilingError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class GoldTooLargeError(Exception):
    """Gold notepad over size cap."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class OfficeRepository:
    """Desks live at office/teams/<team>/agents/<id>/ (git data, not Python classes)."""

    _ORCHESTRATOR_HEADER = """# Office front desk / soft orchestrator jobs — NOT a desk persona.
# Team shows a pinned "Office" card; Configure edits this file.
# Desk agents: office/teams/<team>/agents/<id>/agent.yaml
#
# Soft jobs using `model`:
#   - OKF post-run extract (when okf_extract_enabled)
#   - Office Q&A phrasing (when office_qa_llm)
#
# TODO: extract_temperature / soft-job sampling policy (ORCHESTRATOR.md §5)
# TODO: office_qa_phrase_style (short | formal)
# TODO: soft_job_max_tokens
# TODO: default_project_id for memory pack when projects ship
# TODO: extract_schema_version
# TODO: Stacks helper restart_ollama_on_flush (container recreate)

"""

    def __init__(self, root: Path, *, gold_max_chars: int = 64_000) -> None:
        self.root = root.resolve()
        self.gold_max_chars = gold_max_chars

    @property
    def org_path(self) -> Path:
        return self.root / "org.yaml"

    @property
    def orchestrator_path(self) -> Path:
        return self.root / "orchestrator.yaml"

    @property
    def teams_dir(self) -> Path:
        return self.root / "teams"

    def agent_dir(self, team: str, agent_id: str) -> Path:
        return self.teams_dir / team / "agents" / agent_id

    def load_org(self) -> OrgConfig:
        if not self.org_path.is_file():
            raise FileNotFoundError(f"missing org.yaml at {self.org_path}")
        data = yaml.safe_load(self.org_path.read_text(encoding="utf-8")) or {}
        return OrgConfig.model_validate(data)

    def load_orchestrator(
        self,
        *,
        seed: OrchestratorConfig | None = None,
    ) -> OrchestratorConfig:
        """Load office/orchestrator.yaml; create from seed/defaults if missing."""
        if self.orchestrator_path.is_file():
            data = yaml.safe_load(self.orchestrator_path.read_text(encoding="utf-8")) or {}
            cfg = OrchestratorConfig.model_validate(data)
        else:
            cfg = seed or OrchestratorConfig()
            self.save_orchestrator(cfg)
        self.gold_max_chars = cfg.gold_max_chars
        return cfg

    def save_orchestrator(self, config: OrchestratorConfig) -> OrchestratorConfig:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = config.model_dump(mode="json")
        body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        self.orchestrator_path.write_text(
            self._ORCHESTRATOR_HEADER + body,
            encoding="utf-8",
        )
        self.gold_max_chars = config.gold_max_chars
        return config

    def update_orchestrator(self, patch: OrchestratorConfigUpdate) -> OrchestratorConfig:
        current = self.load_orchestrator()
        data = current.model_dump(mode="json")
        updates = patch.model_dump(mode="json", exclude_none=True)
        data.update(updates)
        return self.save_orchestrator(OrchestratorConfig.model_validate(data))

    def list_agents(self) -> list[AgentConfig]:
        """Scan teams/*/agents/*/agent.yaml. Empty office → []."""
        if not self.teams_dir.is_dir():
            return []

        agents: list[AgentConfig] = []
        for team_dir in sorted(self.teams_dir.iterdir()):
            if not team_dir.is_dir():
                continue
            agents_dir = team_dir / "agents"
            if not agents_dir.is_dir():
                continue
            for desk in sorted(agents_dir.iterdir()):
                yaml_path = desk / "agent.yaml"
                if not yaml_path.is_file():
                    continue
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
                agents.append(AgentConfig.model_validate(data))
        return agents

    def list_agent_summaries(self) -> list[AgentSummary]:
        return [
            AgentSummary(
                id=a.id,
                name=a.name,
                team=a.team,
                stack=a.stack,
                model=a.model,
            )
            for a in self.list_agents()
        ]

    def get_agent(self, agent_id: str) -> AgentConfig | None:
        for agent in self.list_agents():
            if agent.id == agent_id:
                return agent
        return None

    def delete_agent(self, agent_id: str) -> None:
        """Remove desk folder (yaml + AGENT.md + gold/). Raises FileNotFoundError if missing."""
        agent = self.get_agent(agent_id)
        if agent is None:
            raise FileNotFoundError(f"agent not found: {agent_id}")
        desk = self.agent_dir(agent.team, agent.id)
        if desk.is_dir():
            rmtree(desk)

    def read_persona(self, agent: AgentConfig) -> str:
        path = self.agent_dir(agent.team, agent.id) / "AGENT.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
        if agent.system_prompt:
            return agent.system_prompt
        return ""

    def create_agent(self, req: CreateAgentRequest, *, user_id: str) -> AgentConfig:
        """Write agent.yaml + AGENT.md + gold/. Seeds usage primer for creating user."""
        if self.get_agent(req.id) is not None:
            raise AgentExistsError(req.id)

        org = self.load_org()
        autonomy = req.autonomy or AgentAutonomy()
        if autonomy.max is not None and autonomy.max > org.max_autonomy:
            raise AutonomyCeilingError(
                f"agent.autonomy.max ({autonomy.max}) exceeds org.max_autonomy ({org.max_autonomy})"
            )
        if autonomy.default > org.max_autonomy:
            raise AutonomyCeilingError(
                f"agent.autonomy.default ({autonomy.default}) exceeds org.max_autonomy ({org.max_autonomy})"
            )

        config = AgentConfig(
            id=req.id,
            name=req.name,
            team=req.team,
            stack=req.stack,
            model=req.model,
            persona=req.persona or PersonaAxes(),
            autonomy=autonomy,
            workspace=req.workspace,
            system_prompt_file="./AGENT.md",
            tools=ToolsConfig(mode=req.tools_mode),
        )

        desk = self.agent_dir(req.team, req.id)
        # Orphan dirs (no agent.yaml) are reused; real desks already blocked by get_agent.
        desk.mkdir(parents=True, exist_ok=True)
        (desk / "gold").mkdir(exist_ok=True)
        gitkeep = desk / "gold" / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

        yaml_path = desk / "agent.yaml"
        payload = config.model_dump(mode="json", exclude_none=True)
        yaml_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

        persona_md = req.persona_markdown or _default_persona_markdown(config.name)
        (desk / "AGENT.md").write_text(persona_md, encoding="utf-8")

        # Primer for the creating user only; other users get lazy seed on first gold touch.
        self.ensure_gold_primer(config, user_id)

        return config

    def gold_dir(self, agent: AgentConfig) -> Path:
        return self.agent_dir(agent.team, agent.id) / "gold"

    def gold_path(self, agent: AgentConfig, user_id: str) -> Path:
        """Legacy .md path (migration source). Canonical store is .jsonl."""
        return self.gold_dir(agent) / f"{user_id}.md"

    def ensure_gold_primer(self, agent: AgentConfig, user_id: str) -> list[GoldNote]:
        """Ensure gold/<user>.jsonl exists with pinned g_system usage note."""
        return ensure_gold_primer(
            self.gold_dir(agent),
            user_id,
            max_chars=self.gold_max_chars,
        )

    def list_gold_notes(self, agent: AgentConfig, user_id: str) -> list[GoldNote]:
        """List notes; lazily seeds usage primer for this user if missing."""
        return self.ensure_gold_primer(agent, user_id)

    def read_gold(self, agent: AgentConfig, user_id: str) -> str:
        """Rendered notes for UI/pack body (ids + text)."""
        notes = self.list_gold_notes(agent, user_id)
        return render_gold_notes(notes)

    def append_gold_note(
        self,
        agent: AgentConfig,
        user_id: str,
        text: str,
        *,
        run_id: str | None = None,
    ) -> GoldNote:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("gold note text is empty")
        notes = self.list_gold_notes(agent, user_id)
        note = GoldNote(
            id=new_gold_id(),
            text=cleaned,
            run_id=run_id,
            created_at=utc_now_iso(),
        )
        notes.append(note)
        try:
            save_gold_notes(
                self.gold_dir(agent),
                user_id,
                notes,
                max_chars=self.gold_max_chars,
            )
        except GoldNotesTooLargeError as exc:
            raise GoldTooLargeError(str(exc)) from exc
        return note

    def delete_gold_notes(
        self,
        agent: AgentConfig,
        user_id: str,
        ids: list[str],
    ) -> list[str]:
        """Remove notes by id. g_system is protected. Returns ids that were deleted."""
        want = {i.strip() for i in ids if isinstance(i, str) and i.strip()}
        want.discard(SYSTEM_GOLD_ID)
        if not want:
            return []
        notes = self.list_gold_notes(agent, user_id)
        kept: list[GoldNote] = []
        deleted: list[str] = []
        for n in notes:
            if n.id in want:
                deleted.append(n.id)
            else:
                kept.append(n)
        try:
            save_gold_notes(
                self.gold_dir(agent),
                user_id,
                kept,
                max_chars=self.gold_max_chars,
            )
        except GoldNotesTooLargeError as exc:
            raise GoldTooLargeError(str(exc)) from exc
        return deleted

    def clear_gold(self, agent: AgentConfig, user_id: str) -> None:
        """Wipe working notes; re-seed pinned usage primer."""
        try:
            save_gold_notes(
                self.gold_dir(agent),
                user_id,
                [make_system_note()],
                max_chars=self.gold_max_chars,
            )
        except GoldNotesTooLargeError as exc:
            raise GoldTooLargeError(str(exc)) from exc

    def write_gold(self, agent: AgentConfig, user_id: str, content: str) -> None:
        """Ops replace: each non-empty line → a note. Always keeps g_system primer."""
        notes = [make_system_note()]
        if content.strip():
            for line in content.splitlines():
                if line.strip():
                    notes.append(
                        GoldNote(
                            id=new_gold_id(),
                            text=line.strip(),
                            run_id=None,
                            created_at=utc_now_iso(),
                        )
                    )
        try:
            save_gold_notes(
                self.gold_dir(agent),
                user_id,
                notes,
                max_chars=self.gold_max_chars,
            )
        except GoldNotesTooLargeError as exc:
            raise GoldTooLargeError(str(exc)) from exc


def _default_persona_markdown(name: str) -> str:
    return (
        f"# {name}\n\n"
        "## Mission\n"
        "Describe this desk's job.\n\n"
        "## Must\n"
        "- Follow the Office Envelope\n\n"
        "## Must not\n"
        "- Invent company facts without packed memory\n"
    )
