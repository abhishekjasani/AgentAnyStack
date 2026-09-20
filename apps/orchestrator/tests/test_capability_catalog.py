from agent_anystack.capabilities.catalog import (
    CapabilityCatalogItem,
    CapabilityCatalogService,
    CapabilityKind,
    DEFAULT_GOLD_TOOLS,
)
from agent_anystack.domain.agent import AgentAutonomy, AgentConfig, PersonaAxes, Registrations, ToolsConfig, Workspace


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
    service = CapabilityCatalogService()
    agent = _agent("sales-assistant", team="sales")

    capabilities = service.resolve_for_agent(agent)

    assert set(DEFAULT_GOLD_TOOLS).issubset(set(capabilities))
    assert len(capabilities) >= len(DEFAULT_GOLD_TOOLS)


def test_catalog_service_resolves_registered_capabilities():
    service = CapabilityCatalogService()
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
