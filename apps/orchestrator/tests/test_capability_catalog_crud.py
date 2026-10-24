from pathlib import Path

import yaml
import pytest
from httpx import ASGITransport, AsyncClient

from agent_anystack.config import Settings, get_settings
from agent_anystack.domain.agent import CapabilityRegistrations, CreateAgentRequest, UpdateAgentRequest
from agent_anystack.main import create_app
from agent_anystack.office.repository import OfficeRepository


def _settings(tmp_path):
    office = tmp_path / "office"
    (office / "org.yaml").parent.mkdir(parents=True)
    (office / "org.yaml").write_text(
        "id: demo\nname: Demo Org\nmax_autonomy: 100\n",
        encoding="utf-8",
    )
    return office, Settings(
        office_repo_path=str(office),
        database_url=f"sqlite:///{tmp_path}/office.db",
        projects_root=str(tmp_path / "projects"),
    )


@pytest.mark.asyncio
async def test_capability_catalog_create_update_delete_persists_yaml(tmp_path):
    office, settings = _settings(tmp_path)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    descriptor = {
        "id": "notes.lookup",
        "kind": "internal_tool",
        "name": "Lookup Notes",
        "description": "Find notes",
        "handler": "gold.read",
        "callable_name": "lookup_notes",
        "parameters": {"type": "object", "properties": {}},
    }
    headers = {"X-User-Id": "admin"}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/capabilities", headers=headers, json=descriptor
            )
            assert created.status_code == 201, created.text
            assert created.json()["callable_name"] == "lookup_notes"

            changed = {**descriptor, "name": "Find Notes"}
            updated = await client.put(
                "/capabilities/notes.lookup", headers=headers, json=changed
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["name"] == "Find Notes"

            listing = await client.get("/capabilities", headers=headers)
            assert any(item["id"] == "notes.lookup" for item in listing.json()["items"])
            persisted = yaml.safe_load(
                (office / "catalog" / "tools" / "notes.lookup.yaml").read_text(
                    encoding="utf-8"
                )
            )
            assert persisted["callable_name"] == "lookup_notes"
            assert persisted["name"] == "Find Notes"
            assert "tool_name" not in persisted

            deleted = await client.delete(
                "/capabilities/notes.lookup", headers=headers
            )
            assert deleted.status_code == 204
            assert not (office / "catalog" / "tools" / "notes.lookup.yaml").exists()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_capability_catalog_rejects_bad_descriptor_and_protects_gold(tmp_path):
    office, settings = _settings(tmp_path)
    source_catalog = Path(__file__).resolve().parents[3] / "office" / "catalog"
    import shutil

    shutil.copytree(source_catalog, office / "catalog")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {"X-User-Id": "admin"}
    bad_descriptor = {
        "id": "unknown.handler",
        "kind": "internal_tool",
        "name": "Unknown Handler",
        "handler": "not.registered",
        "callable_name": "unknown_handler",
        "parameters": {"type": "object", "properties": {}},
    }
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            bad = await client.post(
                "/capabilities", headers=headers, json=bad_descriptor
            )
            assert bad.status_code == 422
            protected = await client.delete(
                "/capabilities/gold.read", headers=headers
            )
            assert protected.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_catalog_rejects_kind_change_and_delete_of_assigned_item(tmp_path):
    office, settings = _settings(tmp_path)
    source_catalog = Path(__file__).resolve().parents[3] / "office" / "catalog"
    import shutil

    shutil.copytree(source_catalog, office / "catalog")
    descriptor = {
        "id": "notes.lookup",
        "kind": "internal_tool",
        "name": "Lookup Notes",
        "handler": "gold.read",
        "callable_name": "lookup_notes",
        "parameters": {"type": "object", "properties": {}},
    }
    catalog_dir = office / "catalog" / "tools"
    (catalog_dir / "notes.lookup.yaml").write_text(
        yaml.safe_dump(descriptor),
        encoding="utf-8",
    )
    repo = OfficeRepository(office)
    agent = repo.create_agent(
        CreateAgentRequest(
            id="catalog-user",
            name="Catalog User",
            team="eng",
            stack="openai-compatible",
            model="test-model",
            workspace={"project_id": "p1", "path": "/p1"},
        ),
        user_id="user",
    )
    repo.update_agent(
        agent.id,
        UpdateAgentRequest(
            capability_registrations=CapabilityRegistrations(tools=["notes.lookup"])
        ),
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {"X-User-Id": "admin"}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            changed_kind = await client.put(
                "/capabilities/notes.lookup",
                headers=headers,
                json={
                    "id": "notes.lookup",
                    "kind": "api",
                    "name": "Now API",
                    "base_url": "https://api.example.test",
                    "operations": [
                        {
                            "callable_name": "lookup",
                            "description": "lookup",
                            "method": "GET",
                            "path": "/lookup",
                            "parameters": {"type": "object", "properties": {}},
                        }
                    ],
                },
            )
            assert changed_kind.status_code == 400

            removed = await client.delete(
                "/capabilities/notes.lookup", headers=headers
            )
            assert removed.status_code == 409
            assert (catalog_dir / "notes.lookup.yaml").is_file()
    finally:
        app.dependency_overrides.clear()
