"""Agent desk contracts from agent.yaml (AGENT_DEFINITION.md)."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskClass(str, Enum):
    read_draft = "read_draft"
    system_write = "system_write"
    external_send = "external_send"
    money_legal_pii = "money_legal_pii"


class PersonaAxes(BaseModel):
    domain: str = "general"
    channels: list[str] = Field(default_factory=list)
    risk_class: RiskClass = RiskClass.read_draft


class AgentAutonomy(BaseModel):
    default: int = Field(default=50, ge=0, le=100)
    max: int | None = Field(default=None, ge=0, le=100)


class Workspace(BaseModel):
    project_id: str
    path: str


class Registrations(BaseModel):
    mcp: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    apis: list[str] = Field(default_factory=list)


class ToolsConfig(BaseModel):
    mode: Literal["none", "mediated", "worker"] = "none"


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    team: str
    stack: str
    model: str
    persona: PersonaAxes = Field(default_factory=PersonaAxes)
    autonomy: AgentAutonomy = Field(default_factory=AgentAutonomy)
    # Required for new desks; older yaml without workspace still loads (None).
    workspace: Workspace | None = None
    system_prompt_file: str = "./AGENT.md"
    system_prompt: str | None = None
    registrations: Registrations = Field(default_factory=Registrations)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    # Advanced: -1 = inherit stack envelope (tighten-only when > 0).
    max_input_tokens: int = Field(default=-1, ge=-1, le=200_000)
    max_output_tokens: int = Field(default=-1, ge=-1, le=100_000)


class AgentSummary(BaseModel):
    """List DTO — desks visible in JSON without full yaml dump."""

    id: str
    name: str
    team: str
    stack: str
    model: str
    project_id: str | None = None
    max_input_tokens: int = -1
    max_output_tokens: int = -1


class CreateAgentRequest(BaseModel):
    """UI create payload → desk files under office/teams/<team>/agents/<id>/."""

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]*$", min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    team: str = Field(..., pattern=r"^[a-z][a-z0-9_-]*$", min_length=1, max_length=64)
    stack: str = "openai-compatible"
    model: str = Field(..., min_length=1)
    persona_markdown: str | None = None
    persona: PersonaAxes | None = None
    autonomy: AgentAutonomy | None = None
    # Compulsory: bind to an active project (create project first if needed).
    workspace: Workspace
    tools_mode: Literal["none", "mediated", "worker"] = "none"
    max_input_tokens: int = Field(default=-1, ge=-1, le=200_000)
    max_output_tokens: int = Field(default=-1, ge=-1, le=100_000)
