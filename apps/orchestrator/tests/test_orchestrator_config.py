from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from agent_anystack.adapters.bedrock import BedrockAdapter
from agent_anystack.adapters.connections import (
    ConnectionStore,
    StackConnection,
    resolve_inference_adapter,
)
from agent_anystack.adapters.llm import OpenAICompatibleAdapter
from agent_anystack.config import Settings
from agent_anystack.domain.orchestrator import (
    OrchestratorConfig,
    OrchestratorConfigUpdate,
)
from agent_anystack.office.repository import OfficeRepository


def test_orchestrator_config_defaults():
    cfg = OrchestratorConfig()
    assert cfg.model == "llama3.2"
    assert cfg.connection_id == "ollama-local"


def test_orchestrator_config_backwards_compatible_yaml(tmp_path: Path):
    legacy_yaml = """
id: office
name: Office
model: llama3.2:3b
office_qa_llm: true
okf_extract_enabled: true
pack_token_budget: 8000
"""
    repo = OfficeRepository(tmp_path)
    (tmp_path / "orchestrator.yaml").write_text(legacy_yaml, encoding="utf-8")

    cfg = repo.load_orchestrator()
    assert cfg.model == "llama3.2:3b"
    assert cfg.connection_id == "ollama-local"


def test_orchestrator_config_update_connection_id(tmp_path: Path):
    repo = OfficeRepository(tmp_path)
    # Start fresh
    cfg = repo.load_orchestrator()
    assert cfg.connection_id == "ollama-local"

    # Update connection_id and model to Bedrock
    updated = repo.update_orchestrator(
        OrchestratorConfigUpdate(
            model="us.amazon.nova-lite-v1:0",
            connection_id="bed-prod",
        )
    )
    assert updated.model == "us.amazon.nova-lite-v1:0"
    assert updated.connection_id == "bed-prod"

    # Reload from disk to verify persistence
    reloaded = repo.load_orchestrator()
    assert reloaded.model == "us.amazon.nova-lite-v1:0"
    assert reloaded.connection_id == "bed-prod"

    raw_yaml = (tmp_path / "orchestrator.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw_yaml)
    assert parsed["connection_id"] == "bed-prod"
    assert parsed["model"] == "us.amazon.nova-lite-v1:0"


def test_resolve_inference_adapter_ollama(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    settings = Settings(openai_compatible_base_url="http://127.0.0.1:11434/v1")

    adapter = resolve_inference_adapter(
        connection_id="ollama-local",
        store=store,
        settings=settings,
    )
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.base_url == "http://127.0.0.1:11434/v1"


def test_resolve_inference_adapter_bedrock(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    # Configure bedrock meta on connection
    bed = store.get("bedrock")
    assert bed is not None
    bed.meta = {
        "auth": "api_key",
        "api_key": "bedrock-secret-key",
        "region": "us-west-2",
    }
    store.upsert(bed)

    settings = Settings()
    adapter = resolve_inference_adapter(
        connection_id="bed-prod",
        store=store,
        settings=settings,
    )
    assert isinstance(adapter, BedrockAdapter)
    assert adapter.region == "us-west-2"
    assert adapter.api_key == "bedrock-secret-key"
    assert adapter.auth_mode == "api_key"


def test_resolve_inference_adapter_custom_openai_compatible(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="groq-custom",
            kind="inference",
            product="openai-compatible",
            label="Groq Cloud",
            meta={
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "gsk_12345",
            },
        )
    )

    settings = Settings()
    adapter = resolve_inference_adapter(
        connection_id="groq-custom",
        store=store,
        settings=settings,
    )
    assert isinstance(adapter, OpenAICompatibleAdapter)
    assert adapter.base_url == "https://api.groq.com/openai/v1"
    assert adapter.api_key == "gsk_12345"


@pytest.mark.asyncio
async def test_office_config_api_endpoints(tmp_path: Path):
    from httpx import ASGITransport, AsyncClient
    from agent_anystack.main import create_app
    from agent_anystack.config import get_settings

    # Prepare mock office directory with org.yaml
    office_dir = tmp_path / "office"
    office_dir.mkdir(parents=True, exist_ok=True)
    (office_dir / "org.yaml").write_text("id: my-org\nname: Test Org\n", encoding="utf-8")

    settings = Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/office.db",
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET /office/config
        res = await client.get("/office/config")
        assert res.status_code == 200
        data = res.json()
        assert data["orchestrator"]["connection_id"] == "ollama-local"
        assert data["orchestrator"]["model"] == "llama3.2"

        # PUT /office/config
        update_res = await client.put(
            "/office/config",
            json={
                "connection_id": "bed-prod",
                "model": "us.amazon.nova-lite-v1:0",
            },
        )
        assert update_res.status_code == 200
        updated_data = update_res.json()
        assert updated_data["orchestrator"]["connection_id"] == "bed-prod"
        assert updated_data["orchestrator"]["model"] == "us.amazon.nova-lite-v1:0"

        # Verify persistent GET
        recheck_res = await client.get("/office/config")
        assert recheck_res.status_code == 200
        assert recheck_res.json()["orchestrator"]["connection_id"] == "bed-prod"
        assert recheck_res.json()["orchestrator"]["model"] == "us.amazon.nova-lite-v1:0"
