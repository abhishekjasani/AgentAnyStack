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


class AgentExistsError(Exception):
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"agent already exists: {agent_id}")


class AutonomyCeilingError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class OfficeRepository:
    """Desks live at office/teams/<team>/agents/<id>/ (git data, not Python classes)."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def org_path(self) -> Path:
        return self.root / "org.yaml"

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

    def create_agent(self, req: CreateAgentRequest) -> AgentConfig:
        """Write agent.yaml + AGENT.md + gold/. Raises if id collision or autonomy over org ceiling."""
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

        return config


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
