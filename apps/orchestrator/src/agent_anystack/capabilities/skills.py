from __future__ import annotations

from agent_anystack.capabilities.catalog import CapabilityCatalogService, CapabilityKind
from agent_anystack.domain.agent import AgentConfig

MAX_SKILL_PROMPT_CHARS = 12_000


def render_registered_skill_prompt(
    catalog: CapabilityCatalogService,
    agent: AgentConfig,
) -> str:
    effective = set(catalog.resolve_for_agent(agent))
    sections: list[str] = []
    for skill_id in sorted(agent.capability_registrations.skills):
        item = catalog.get(skill_id)
        if item is None or item.kind != CapabilityKind.skill or not item.content:
            continue
        if not set(item.requires).issubset(effective):
            continue
        remaining = MAX_SKILL_PROMPT_CHARS - sum(len(section) for section in sections)
        if remaining <= 0:
            break
        content = item.content.strip()
        section = f"## Skill: {item.name} ({item.id})\n{content}"
        if len(section) > remaining:
            section = section[:remaining]
        sections.append(section)
    return "\n\n".join(sections)