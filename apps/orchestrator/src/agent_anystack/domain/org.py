"""Org config from office/org.yaml."""

from pydantic import BaseModel, Field


class OrgAutonomy(BaseModel):
    default: int = Field(default=50, ge=0, le=100)


class OrgConfig(BaseModel):
    id: str = "default"
    name: str = "AgentAnyStack"
    max_autonomy: int = Field(default=100, ge=0, le=100)
    autonomy: OrgAutonomy = Field(default_factory=OrgAutonomy)
