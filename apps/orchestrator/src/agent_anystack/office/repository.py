"""Load office git tree (org + agent desks). No seed agents — empty until UI create."""

from pathlib import Path

import yaml

from agent_anystack.domain.agent import AgentConfig, AgentSummary
from agent_anystack.domain.org import OrgConfig


class OfficeRepository:
    """Read desks from office/teams/<team>/agents/<id>/agent.yaml."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def org_path(self) -> Path:
        return self.root / "org.yaml"

    @property
    def teams_dir(self) -> Path:
        return self.root / "teams"

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
            for agent_dir in sorted(agents_dir.iterdir()):
                yaml_path = agent_dir / "agent.yaml"
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
