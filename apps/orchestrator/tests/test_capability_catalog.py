import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_anystack.capabilities.catalog import (
    CapabilityCatalogItem,
    CapabilityCatalogService,
    CapabilityKind,
)
from agent_anystack.capabilities.binding import build_bindings
from agent_anystack.capabilities.skills import render_registered_skill_prompt
from agent_anystack.config import Settings, get_settings
from agent_anystack.adapters.llm import ChatTurnResult, ToolCallRequest
from agent_anystack.domain.agent import (
    AgentAutonomy,
    AgentConfig,
    CreateAgentRequest,
    PersonaAxes,
    Registrations,
    ToolsConfig,
    UpdateAgentRequest,
    Workspace,
)
from agent_anystack.office.repository import OfficeRepository
from agent_anystack.runs.service import ChatRunService


def _office_root() -> Path:
    return Path(__file__).resolve().parents[3] / "office"


def _gold_capability_ids(service: CapabilityCatalogService) -> set[str]:
    return {
        item.id
        for item in service.list()
        if item.kind == CapabilityKind.internal_tool
        and item.default_inherit
        and "gold" in item.tags
    }


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

    defaults = _gold_capability_ids(service)
    assert defaults.issubset(set(capabilities))
    assert len(capabilities) >= len(defaults)


def test_any_default_inherit_descriptor_is_resolved_without_id_registry():
    service = CapabilityCatalogService(_office_root())
    service.register(
        CapabilityCatalogItem(
            id="team.helper",
            kind=CapabilityKind.internal_tool,
            name="Team Helper",
            handler="gold.read",
            callable_name="team_helper",
            parameters={"type": "object", "properties": {}},
            default_inherit=True,
        )
    )

    resolved = service.resolve_for_agent(_agent("support-agent"))

    assert "team.helper" in resolved


def test_gold_catalog_descriptors_persist_in_office_catalog(tmp_path):
    shutil.copytree(_office_root() / "catalog", tmp_path / "catalog")
    catalog_dir = tmp_path / "catalog" / "tools"

    first_service = CapabilityCatalogService(tmp_path)
    persisted_ids = {path.stem for path in catalog_dir.glob("*.yaml")}
    second_service = CapabilityCatalogService(tmp_path)

    expected_gold = _gold_capability_ids(second_service)
    assert expected_gold.issubset(persisted_ids)
    assert expected_gold.issubset({item.id for item in second_service.list()})
    assert {item.id for item in first_service.list()} == {item.id for item in second_service.list()}


def test_bindings_only_offer_tools_with_catalog_descriptors(tmp_path):
    shutil.copytree(_office_root() / "catalog", tmp_path / "catalog")
    (tmp_path / "catalog" / "tools" / "gold.append.yaml").unlink()
    service = CapabilityCatalogService(tmp_path)

    bindings = build_bindings(service, _agent("sales-assistant", team="sales"))

    assert set(bindings) == {"read_gold", "delete_gold", "clear_gold"}
    assert all(binding.item.id != "gold.append" for binding in bindings.values())


def test_duplicate_model_tool_names_are_rejected():
    service = CapabilityCatalogService(_office_root())
    service.register(
        CapabilityCatalogItem(
            id="duplicate.read",
            kind=CapabilityKind.internal_tool,
            name="Duplicate read",
            handler="gold.append",
            callable_name="read_gold",
            parameters={"type": "object", "properties": {}},
            default_inherit=True,
        )
    )

    with pytest.raises(ValueError, match="duplicate capability callable_name: read_gold"):
        build_bindings(service, _agent("sales-assistant", team="sales"))


def test_unknown_internal_tool_handler_fails_catalog_load(tmp_path):
    shutil.copytree(_office_root() / "catalog", tmp_path / "catalog")
    descriptor = tmp_path / "catalog" / "tools" / "gold.read.yaml"
    descriptor.write_text(
        descriptor.read_text(encoding="utf-8").replace(
            "handler: gold.read", "handler: gold.unknown"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown capability handler: gold.unknown"):
        CapabilityCatalogService(tmp_path)


@pytest.mark.asyncio
async def test_unoffered_model_tool_call_is_rejected(tmp_path):
    shutil.copytree(_office_root() / "catalog", tmp_path / "catalog")
    (tmp_path / "catalog" / "tools" / "gold.append.yaml").unlink()
    repo = OfficeRepository(tmp_path)
    service = ChatRunService(
        repo=repo,
        journal=MagicMock(),
        openai_compatible_base_url="http://mock:11434",
        okf=MagicMock(),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )
    adapter = MagicMock()
    adapter.complete_chat_turn = AsyncMock(
        side_effect=[
            ChatTurnResult(
                tool_calls=[
                    ToolCallRequest(
                        id="call-1",
                        name="append_gold",
                        arguments='{"text":"should not be written"}',
                    )
                ]
            ),
            ChatTurnResult(content="Done"),
        ]
    )
    messages = [{"role": "user", "content": "save this"}]

    events = [
        event
        async for event in service._run_with_gold_tools(
            adapter=adapter,
            model="test-model",
            messages=messages,
            agent=_agent("sales-assistant", team="sales"),
            user_id="user-1",
            run_id="run-1",
        )
    ]

    offered_names = {
        tool["function"]["name"]
        for tool in adapter.complete_chat_turn.call_args_list[0].kwargs["tools"]
    }
    assert "append_gold" not in offered_names
    assert messages[2]["content"] == "error: unknown tool"
    assert next(event for event in events if event.get("type") == "tool")["ok"] is False


@pytest.mark.asyncio
async def test_catalog_bound_append_gold_dispatches_to_repository(tmp_path):
    shutil.copytree(_office_root() / "catalog", tmp_path / "catalog")
    (tmp_path / "org.yaml").write_text(
        "id: demo\nname: Demo Org\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    repo = OfficeRepository(tmp_path)
    agent = repo.create_agent(
        CreateAgentRequest(
            id="sales-assistant",
            name="Sales Assistant",
            team="sales",
            stack="openai-compatible",
            model="test-model",
            workspace={"project_id": "proj-1", "path": str(tmp_path)},
            tools_mode="none",
        ),
        user_id="user-1",
    )
    service = ChatRunService(
        repo=repo,
        journal=MagicMock(),
        openai_compatible_base_url="http://mock:11434",
        okf=MagicMock(),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )
    adapter = MagicMock()
    adapter.complete_chat_turn = AsyncMock(
        side_effect=[
            ChatTurnResult(
                tool_calls=[
                    ToolCallRequest(
                        id="call-1",
                        name="append_gold",
                        arguments='{"text":"Keep the release note concise."}',
                    )
                ]
            ),
            ChatTurnResult(content="Saved"),
        ]
    )

    async for _event in service._run_with_gold_tools(
        adapter=adapter,
        model="test-model",
        messages=[{"role": "user", "content": "remember this"}],
        agent=agent,
        user_id="user-1",
        run_id="run-1",
    ):
        pass

    offered_names = {
        tool["function"]["name"]
        for tool in adapter.complete_chat_turn.call_args_list[0].kwargs["tools"]
    }
    assert "append_gold" in offered_names
    assert "Keep the release note concise." in repo.read_gold(agent, "user-1")


def test_catalog_service_resolves_registered_capabilities():
    service = CapabilityCatalogService(_office_root())
    service.register(
        CapabilityCatalogItem(
            id="firecrawl-api",
            kind=CapabilityKind.api,
            name="Firecrawl API",
            base_url="https://api.firecrawl.dev",
            auth={"type": "none"},
            operations=[
                {
                    "callable_name": "firecrawl_search",
                    "description": "Search the web",
                    "method": "GET",
                    "path": "/search",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            default_inherit=False,
            approval_mode="always",
            risk_class="external_send",
        )
    )

    agent = _agent("research-agent", team="ba")
    agent.registrations.apis = ["firecrawl-api"]

    capabilities = service.resolve_for_agent(agent)

    assert "firecrawl-api" in capabilities
    assert _gold_capability_ids(service).issubset(set(capabilities))


def test_agent_config_reads_legacy_registrations_and_writes_new_key():
    agent = AgentConfig.model_validate(
        {
            "id": "legacy-agent",
            "name": "Legacy Agent",
            "team": "eng",
            "stack": "openai-compatible",
            "model": "test-model",
            "registrations": {"apis": ["firecrawl-api"]},
        }
    )

    assert agent.capability_registrations.apis == ["firecrawl-api"]
    assert agent.model_dump()["capability_registrations"]["apis"] == ["firecrawl-api"]
    assert "registrations" not in agent.model_dump()


def test_repository_migrates_legacy_registration_key_on_next_write(tmp_path):
    agent_dir = tmp_path / "teams" / "eng" / "agents" / "legacy-agent"
    agent_dir.mkdir(parents=True)
    agent_yaml = agent_dir / "agent.yaml"
    agent_yaml.write_text(
        "id: legacy-agent\nname: Legacy Agent\nteam: eng\n"
        "stack: openai-compatible\nmodel: test-model\n"
        "registrations:\n  apis:\n    - firecrawl-api\n",
        encoding="utf-8",
    )
    repo = OfficeRepository(tmp_path)

    agent = repo.get_agent("legacy-agent")
    assert agent is not None
    assert agent.capability_registrations.apis == ["firecrawl-api"]
    repo.update_agent("legacy-agent", UpdateAgentRequest(name="Migrated Agent"))

    import yaml

    persisted = yaml.safe_load(agent_yaml.read_text(encoding="utf-8"))
    assert persisted["capability_registrations"]["apis"] == ["firecrawl-api"]
    assert "registrations" not in persisted


def test_capabilities_are_isolated_and_registration_kind_is_enforced():
    service = CapabilityCatalogService(_office_root())
    service.register(
        CapabilityCatalogItem(
            id="browser-mcp",
            kind=CapabilityKind.mcp,
            name="Browser MCP",
            server_url="https://browser.example.test/mcp",
        )
    )
    service.register(
        CapabilityCatalogItem(
            id="private-tool",
            kind=CapabilityKind.internal_tool,
            name="Private Tool",
            handler="gold.read",
            callable_name="private_tool",
            parameters={"type": "object", "properties": {}},
        )
    )
    desk_a = _agent("desk-a")
    desk_b = _agent("desk-b")
    desk_a.capability_registrations.mcp = ["browser-mcp"]
    desk_a.capability_registrations.apis = ["private-tool"]

    caps_a = set(service.resolve_for_agent(desk_a))
    caps_b = set(service.resolve_for_agent(desk_b))

    assert "browser-mcp" in caps_a
    assert "browser-mcp" not in caps_b
    assert "private-tool" not in caps_a


def test_skill_prompt_includes_only_registered_skills_and_available_dependencies():
    service = CapabilityCatalogService(_office_root())
    service.register(
        CapabilityCatalogItem(
            id="skill.support",
            kind=CapabilityKind.skill,
            name="Support workflow",
            content="Use concise customer-safe language.",
            requires=["gold.read"],
        )
    )
    service.register(
        CapabilityCatalogItem(
            id="skill.legal",
            kind=CapabilityKind.skill,
            name="Legal review",
            content="Escalate legal commitments.",
            requires=["missing-api"],
        )
    )
    registered = _agent("support-desk")
    registered.capability_registrations.skills = ["skill.support", "skill.legal"]
    not_registered = _agent("other-desk")

    prompt = render_registered_skill_prompt(service, registered)
    other_prompt = render_registered_skill_prompt(service, not_registered)

    assert "Use concise customer-safe language." in prompt
    assert "Escalate legal commitments." not in prompt
    assert other_prompt == ""


@pytest.mark.asyncio
async def test_registration_api_is_desk_scoped_and_rejects_unknown_ids(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from agent_anystack.main import create_app

    office_dir = tmp_path / "office"
    shutil.copytree(_office_root() / "catalog", office_dir / "catalog")
    mcp_dir = office_dir / "catalog" / "mcp"
    mcp_dir.mkdir()
    (mcp_dir / "browser.yaml").write_text(
        "id: browser-mcp\nkind: mcp\nname: Browser MCP\n"
        "server_url: https://browser.example.test/mcp\n",
        encoding="utf-8",
    )
    (office_dir / "org.yaml").write_text(
        "id: demo\nname: Demo Org\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    repo = OfficeRepository(office_dir)
    for agent_id in ("desk-a", "desk-b"):
        repo.create_agent(
            CreateAgentRequest(
                id=agent_id,
                name=agent_id,
                team="eng",
                stack="openai-compatible",
                model="test-model",
                workspace={"project_id": "proj-1", "path": "/projects/proj-1"},
            ),
            user_id="test-user",
        )

    settings = Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/office.db",
        projects_root=str(tmp_path / "projects"),
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"X-User-Id": "test-user"}
            update = await client.put(
                "/agents/desk-a/registrations",
                headers=headers,
                json={"tools": [], "mcp": ["browser-mcp"], "skills": [], "apis": []},
            )
            assert update.status_code == 200, update.text
            assert update.json()["mcp"] == ["browser-mcp"]

            import yaml

            persisted = yaml.safe_load(
                (office_dir / "teams" / "eng" / "agents" / "desk-a" / "agent.yaml")
                .read_text(encoding="utf-8")
            )
            assert persisted["capability_registrations"]["mcp"] == ["browser-mcp"]
            assert "registrations" not in persisted

            desk_a = await client.get("/agents/desk-a/capabilities", headers=headers)
            desk_b = await client.get("/agents/desk-b/capabilities", headers=headers)
            assert "browser-mcp" in desk_a.json()["effective_capabilities"]
            assert "browser-mcp" not in desk_b.json()["effective_capabilities"]

            unknown = await client.put(
                "/agents/desk-a/registrations",
                headers=headers,
                json={"tools": [], "mcp": ["not-in-catalog"], "skills": [], "apis": []},
            )
            assert unknown.status_code == 400

            wrong_kind = await client.put(
                "/agents/desk-a/registrations",
                headers=headers,
                json={"tools": [], "mcp": [], "skills": [], "apis": ["browser-mcp"]},
            )
            assert wrong_kind.status_code == 400
    finally:
        app.dependency_overrides.clear()


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
        assert _gold_capability_ids(service).issubset(set(effective))
        assert len(effective) == len(_gold_capability_ids(service))


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
    catalog = CapabilityCatalogService(_office_root())
    assert _gold_capability_ids(catalog).issubset(set(catalog.resolve_for_agent(ba)))


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
            assert _gold_capability_ids(CapabilityCatalogService(office_dir)).issubset(catalog_ids)

            capabilities = await client.get(
                "/agents/sales-agent/capabilities",
                headers={"X-User-Id": "demo-user"},
            )
            assert capabilities.status_code == 200, capabilities.text
            payload = capabilities.json()
            assert payload["agent_id"] == "sales-agent"
            assert _gold_capability_ids(CapabilityCatalogService(office_dir)).issubset(
                set(payload["effective_capabilities"])
            )
            assert payload["catalog_count"] >= len(_gold_capability_ids(CapabilityCatalogService(office_dir)))
    finally:
        app.dependency_overrides.clear()
