import json
import shutil
from pathlib import Path

import pytest

from agent_anystack.capabilities.catalog import (
    CapabilityCatalogItem,
    CapabilityCatalogService,
    CapabilityKind,
    DEFAULT_GOLD_TOOLS,
)
from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.agent import (
    AgentAutonomy,
    AgentConfig,
    CreateAgentRequest,
    PersonaAxes,
    Registrations,
    ToolsConfig,
    Workspace,
)
from agent_anystack.office.repository import OfficeRepository


def _office_root() -> Path:
    return Path(__file__).resolve().parents[3] / "office"


def _agent(agent_id: str, team: str = "eng") -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        name=agent_id.replace("-", " ").title(),
        team=team,
        stack="openai-compatible",
        model="gpt-4o-mini",
        persona=PersonaAxes(domain="eng"),
        autonomy=AgentAutonomy(default=50),
        workspace=Workspace(project_id="proj-1", path="/workspace/proj-1"),
        registrations=Registrations(),
        tools=ToolsConfig(mode="none"),
    )


def test_default_gold_tools_are_available_for_agent_desks():
    service = CapabilityCatalogService(_office_root())
    agent = _agent("sales-assistant", team="sales")

    capabilities = service.resolve_for_agent(agent)

    assert set(DEFAULT_GOLD_TOOLS).issubset(set(capabilities))
    assert len(capabilities) >= len(DEFAULT_GOLD_TOOLS)


def test_gold_catalog_descriptors_persist_in_office_catalog(tmp_path):
    shutil.copytree(_office_root() / "catalog", tmp_path / "catalog")
    catalog_dir = tmp_path / "catalog" / "tools"

    first_service = CapabilityCatalogService(tmp_path)
    persisted_ids = {path.stem for path in catalog_dir.glob("*.yaml")}
    second_service = CapabilityCatalogService(tmp_path)

    assert set(DEFAULT_GOLD_TOOLS).issubset(persisted_ids)
    assert set(DEFAULT_GOLD_TOOLS).issubset({item.id for item in second_service.list()})
    assert {item.id for item in first_service.list()} == {item.id for item in second_service.list()}


def test_catalog_service_resolves_registered_capabilities():
    service = CapabilityCatalogService(_office_root())
    service.register(
        CapabilityCatalogItem(
            id="firecrawl-api",
            kind=CapabilityKind.external_tool,
            name="Firecrawl API",
            default_inherit=False,
            approval_mode="always",
            risk_class="external_send",
        )
    )

    agent = _agent("research-agent", team="ba")
    agent.registrations.apis = ["firecrawl-api"]

    capabilities = service.resolve_for_agent(agent)

    assert "firecrawl-api" in capabilities
    assert set(DEFAULT_GOLD_TOOLS).issubset(set(capabilities))


def test_zen_connection_team_of_four_gold_only(tmp_path):
    repo = OfficeRepository(tmp_path)
    (tmp_path / "org.yaml").write_text("id: demo\nname: Demo Org\nmax_autonomy: 100\n", encoding="utf-8")

    desk_ids = ["sales-agent", "support-agent", "ops-agent", "ba-agent"]
    for desk_id in desk_ids:
        repo.create_agent(
            CreateAgentRequest(
                id=desk_id,
                name=desk_id.replace("-", " ").title(),
                team="growth",
                stack="openai-compatible",
                connection_id="zen",
                model="gpt-4o-mini",
                workspace={"project_id": "proj-zen", "path": "/workspace/proj-zen"},
                tools_mode="none",
            ),
            user_id="demo-user",
        )

    agents = repo.list_agents()
    assert len(agents) == 4

    service = CapabilityCatalogService(_office_root())
    for agent in agents:
        assert agent.connection_id == "zen"
        effective = service.resolve_for_agent(agent)
        assert set(DEFAULT_GOLD_TOOLS).issubset(set(effective))
        assert len(effective) == len(DEFAULT_GOLD_TOOLS)


def test_gold_only_customer_handoff_workflow_for_four_zen_desks(tmp_path):
    repo = OfficeRepository(tmp_path)
    (tmp_path / "org.yaml").write_text("id: demo\nname: Demo Org\nmax_autonomy: 100\n", encoding="utf-8")

    desk_ids = ["sales-agent", "support-agent", "ops-agent", "ba-agent"]
    agents = {}
    for desk_id in desk_ids:
        agent = repo.create_agent(
            CreateAgentRequest(
                id=desk_id,
                name=desk_id.replace("-", " ").title(),
                team="growth",
                stack="openai-compatible",
                connection_id="zen",
                model="gpt-4o-mini",
                workspace={"project_id": "proj-zen", "path": "/workspace/proj-zen"},
                tools_mode="none",
            ),
            user_id="demo-user",
        )
        agents[desk_id] = agent

    sales = agents["sales-agent"]
    support = agents["support-agent"]
    ops = agents["ops-agent"]
    ba = agents["ba-agent"]

    repo.append_gold_note(
        sales,
        "demo-user",
        "Customer Acme requested a pricing proposal for the Pro plan and asked for a 48h response.",
        run_id="run-sales-1",
    )
    repo.append_gold_note(
        support,
        "demo-user",
        "Customer confirmed the proposal was received. Acknowledge and schedule onboarding follow-up.",
        run_id="run-support-1",
    )
    repo.append_gold_note(
        ops,
        "demo-user",
        "Provisioning is ready; onboarding checklist has been queued for next Monday.",
        run_id="run-ops-1",
    )

    summary = (
        "Acme pricing request closed: proposal sent, onboarding scheduled, and provisioning queued. "
        "Next step is customer confirmation on timeline."
    )
    repo.append_gold_note(ba, "demo-user", summary, run_id="run-ba-1")

    sales_notes = repo.read_gold(sales, "demo-user")
    ba_notes = repo.read_gold(ba, "demo-user")

    assert "pricing proposal" in sales_notes.lower()
    assert "onboarding scheduled" in ba_notes.lower()
    assert "Acme pricing request closed" in ba_notes
    assert set(DEFAULT_GOLD_TOOLS).issubset(
        set(CapabilityCatalogService(_office_root()).resolve_for_agent(ba))
    )


@pytest.mark.asyncio
async def test_capability_catalog_api_exposes_agent_effective_capabilities(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from agent_anystack.main import create_app

    office_dir = tmp_path / "office"
    office_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_office_root() / "catalog", office_dir / "catalog")
    (office_dir / "org.yaml").write_text("id: demo\nname: Demo Org\nmax_autonomy: 100\n", encoding="utf-8")

    settings = Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/office.db",
        projects_root=str(tmp_path / "projects"),
    )
    (tmp_path / "stacks_connections.json").write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "id": "zen-dev",
                        "kind": "inference",
                        "product": "openai-compatible",
                        "label": "zen-dev",
                        "enabled": True,
                        "status": "connected",
                        "meta": {
                            "preset": "zen",
                            "base_url": "https://opencode.ai/zen/v1",
                        },
                        "verified_models": [
                            {
                                "model_id": "big-pickle",
                                "display_name": "big-pickle",
                                "verified_at": "2026-09-02T17:13:41+00:00",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            project = await client.post(
                "/projects",
                json={"name": "Zen Capability Demo", "slug": "proj-zen"},
                headers={"X-User-Id": "demo-user"},
            )
            assert project.status_code == 201, project.text
            project_id = project.json()["id"]

            create = await client.post(
                "/agents",
                json={
                    "id": "sales-agent",
                    "name": "Sales Agent",
                    "team": "growth",
                    "stack": "openai-compatible",
                    "connection_id": "zen-dev",
                    "model": "big-pickle",
                    "workspace": {"project_id": project_id, "path": "/workspace/proj-zen"},
                    "tools_mode": "none",
                },
                headers={"X-User-Id": "demo-user"},
            )
            assert create.status_code == 201, create.text

            catalog = await client.get(
                "/capabilities",
                headers={"X-User-Id": "demo-user"},
            )
            assert catalog.status_code == 200, catalog.text
            catalog_ids = {item["id"] for item in catalog.json()["items"]}
            assert set(DEFAULT_GOLD_TOOLS).issubset(catalog_ids)

            capabilities = await client.get(
                "/agents/sales-agent/capabilities",
                headers={"X-User-Id": "demo-user"},
            )
            assert capabilities.status_code == 200, capabilities.text
            payload = capabilities.json()
            assert payload["agent_id"] == "sales-agent"
            assert set(DEFAULT_GOLD_TOOLS).issubset(set(payload["effective_capabilities"]))
            assert payload["catalog_count"] >= len(DEFAULT_GOLD_TOOLS)
    finally:
        app.dependency_overrides.clear()
