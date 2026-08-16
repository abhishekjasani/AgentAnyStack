"""Agent desk HTTP routes — list / get / create (UI path; no seed desks)."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from agent_anystack.adapters.bedrock_store import BedrockProviderStore, bedrock_data_dir
from agent_anystack.adapters.ollama_models import OllamaModelManager
from agent_anystack.adapters.stack_models import (
    StackSelectionError,
    validate_desk_selection,
)
from agent_anystack.api.deps import get_user_id
from agent_anystack.api.projects import get_project_registry
from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.agent import (
    AgentConfig,
    AgentDetail,
    AgentSummary,
    CreateAgentRequest,
    UpdateAgentRequest,
    Workspace,
)
from agent_anystack.domain.org import OrgConfig
from agent_anystack.office import (
    AgentExistsError,
    AutonomyCeilingError,
    OfficeRepository,
)
from agent_anystack.office.project_registry import ProjectNotFoundError, ProjectRegistry

router = APIRouter(tags=["agents"])


def get_office_repo(settings: Settings = Depends(get_settings)) -> OfficeRepository:
    """Office git root; soft knobs from orchestrator.yaml (seeded from Settings if missing)."""
    from agent_anystack.domain.orchestrator import OrchestratorConfig

    repo = OfficeRepository(
        Path(settings.office_repo_path),
        gold_max_chars=settings.gold_max_chars,
    )
    repo.load_orchestrator(
        seed=OrchestratorConfig(
            model=settings.office_model,
            office_qa_llm=settings.office_qa_llm,
            okf_extract_enabled=settings.okf_extract_enabled,
            okf_extract_llm=settings.okf_extract_llm,
            okf_extract_remember_lines=settings.okf_extract_remember_lines,
            pack_token_budget=settings.pack_token_budget,
            gold_max_chars=settings.gold_max_chars,
            recent_history_days=settings.recent_history_days,
            recent_history_char_budget=settings.recent_history_char_budget,
            approver_mode=settings.approver_mode,
        )
    )
    return repo


def get_ollama_manager(settings: Settings = Depends(get_settings)) -> OllamaModelManager:
    return OllamaModelManager(
        settings.openai_compatible_base_url,
        timeout=settings.ollama_pull_timeout,
    )


def get_bedrock_store(settings: Settings = Depends(get_settings)) -> BedrockProviderStore:
    return BedrockProviderStore(bedrock_data_dir(settings.database_url))


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> list[AgentSummary]:
    """Desks from office git. Empty until UI/API creates agents."""
    return repo.list_agent_summaries()


@router.get("/agents/{agent_id}", response_model=AgentDetail)
async def get_agent(
    agent_id: str,
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> AgentDetail:
    agent = repo.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return AgentDetail(
        **agent.model_dump(),
        persona_markdown=repo.read_persona(agent),
    )


@router.post(
    "/agents",
    response_model=AgentConfig,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    body: CreateAgentRequest,
    repo: OfficeRepository = Depends(get_office_repo),
    registry: ProjectRegistry = Depends(get_project_registry),
    ollama: OllamaModelManager = Depends(get_ollama_manager),
    bedrock: BedrockProviderStore = Depends(get_bedrock_store),
    user_id: str = Depends(get_user_id),
) -> AgentConfig:
    """Write office/teams/<team>/agents/<id>/; workspace must reference an active project."""
    try:
        resolved = await validate_desk_selection(
            body.stack,
            body.model,
            ollama=ollama,
            bedrock_store=bedrock,
        )
    except StackSelectionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    tools_mode = body.tools_mode
    if resolved.stack == "opencode":
        tools_mode = "worker"

    try:
        project = registry.require_active(body.workspace.project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{exc}. Create a project first (POST /projects), then bind "
                "workspace.project_id on the agent."
            ),
        ) from exc

    # Path always comes from the registry (capability is the truth).
    bound = body.model_copy(
        update={
            "stack": resolved.stack,
            "model": resolved.model,
            "tools_mode": tools_mode,
            "workspace": Workspace(project_id=project.id, path=project.path),
        }
    )
    try:
        return repo.create_agent(bound, user_id=user_id)
    except AgentExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AutonomyCeilingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/agents/{agent_id}", response_model=AgentDetail)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    repo: OfficeRepository = Depends(get_office_repo),
    registry: ProjectRegistry = Depends(get_project_registry),
    ollama: OllamaModelManager = Depends(get_ollama_manager),
    bedrock: BedrockProviderStore = Depends(get_bedrock_store),
    _user_id: str = Depends(get_user_id),
) -> AgentDetail:
    """Patch desk agent.yaml (+ AGENT.md if persona_markdown set)."""
    existing = repo.get_agent(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")

    next_stack = body.stack if body.stack is not None else existing.stack
    next_model = body.model if body.model is not None else existing.model
    try:
        resolved = await validate_desk_selection(
            next_stack,
            next_model,
            ollama=ollama,
            bedrock_store=bedrock,
        )
    except StackSelectionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    patch = body.model_copy(
        update={"stack": resolved.stack, "model": resolved.model},
    )
    if resolved.stack == "opencode":
        patch = patch.model_copy(update={"tools_mode": "worker"})
    if body.workspace is not None:
        try:
            project = registry.require_active(body.workspace.project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{exc}. Create a project first (POST /projects), then bind "
                    "workspace.project_id on the agent."
                ),
            ) from exc
        patch = patch.model_copy(
            update={
                "workspace": Workspace(project_id=project.id, path=project.path),
            }
        )
    try:
        agent = repo.update_agent(agent_id, patch)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AutonomyCeilingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AgentDetail(
        **agent.model_dump(),
        persona_markdown=repo.read_persona(agent),
    )


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    repo: OfficeRepository = Depends(get_office_repo),
    _user_id: str = Depends(get_user_id),
) -> None:
    """Remove desk folder from office git tree."""
    try:
        repo.delete_agent(agent_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/org", response_model=OrgConfig)
async def get_org(repo: OfficeRepository = Depends(get_office_repo)) -> OrgConfig:
    try:
        return repo.load_org()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
