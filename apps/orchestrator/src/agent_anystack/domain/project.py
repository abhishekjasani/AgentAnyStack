"""Project registry contracts — one project = one git working tree under PROJECTS_ROOT."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    slug: str
    path: str
    status: Literal["active", "deleted"] = "active"


class CreateProjectRequest(BaseModel):
    """Create registry row + working tree (git init; LFS later)."""

    name: str = Field(..., min_length=1, max_length=128)
    # Optional slug; derived from name when omitted.
    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_-]*$",
        min_length=1,
        max_length=64,
    )


class ProjectSummary(BaseModel):
    id: str
    name: str
    slug: str
    path: str
    status: str
