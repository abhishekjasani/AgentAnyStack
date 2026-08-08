"""Project registry HTTP — list / create (working trees under PROJECTS_ROOT)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from agent_anystack.api.deps import get_user_id
from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.project import CreateProjectRequest, ProjectSummary
from agent_anystack.office.project_registry import (
    ProjectExistsError,
    ProjectRegistry,
)

router = APIRouter(tags=["projects"])


def get_project_registry(
    settings: Settings = Depends(get_settings),
) -> ProjectRegistry:
    return ProjectRegistry(
        Path(settings.office_repo_path),
        Path(settings.projects_root),
    )


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(
    registry: ProjectRegistry = Depends(get_project_registry),
    _user_id: str = Depends(get_user_id),
) -> list[ProjectSummary]:
    return [
        ProjectSummary(
            id=p.id,
            name=p.name,
            slug=p.slug,
            path=p.path,
            status=p.status,
        )
        for p in registry.list_projects()
    ]


@router.post(
    "/projects",
    response_model=ProjectSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    body: CreateProjectRequest,
    registry: ProjectRegistry = Depends(get_project_registry),
    _user_id: str = Depends(get_user_id),
) -> ProjectSummary:
    try:
        p = registry.create(body)
    except ProjectExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"project folder already exists: {exc}",
        ) from exc
    return ProjectSummary(
        id=p.id,
        name=p.name,
        slug=p.slug,
        path=p.path,
        status=p.status,
    )
