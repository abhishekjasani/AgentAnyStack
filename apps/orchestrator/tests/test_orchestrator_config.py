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


class FailingAdapter:
    async def complete_chat(self, *args, **kwargs):
        raise RuntimeError("Simulated LLM network failure")


class SuccessfulAdapter:
    def __init__(self, response_text: str):
        self.response_text = response_text

    async def complete_chat(self, *args, **kwargs):
        return self.response_text


@pytest.mark.asyncio
async def test_okf_extract_safe_error_recovery(tmp_path: Path):
    from agent_anystack.memory.extract import ExtractJob, run_okf_extract
    from agent_anystack.memory.store import OkfStore

    store = OkfStore(tmp_path / "okf.db")
    job = ExtractJob(
        run_id="run-123",
        agent_id="test-agent",
        user_id="user-1",
        team="eng",
        model="test-model",
        user_message="Hello!\nremember: Deployment requires approval.\nremember: Database port is 5432.",
        assistant_text="I understand.",
    )

    written = await run_okf_extract(
        job,
        okf=store,
        adapter=FailingAdapter(),
        use_llm=True,
        use_remember_lines=False,
    )
    assert written == 2
    facts = store.list_team_facts("eng")
    bodies = {f.body for f in facts}
    assert "Deployment requires approval." in bodies
    assert "Database port is 5432." in bodies


@pytest.mark.asyncio
async def test_office_qa_llm_failure_fallback_to_raw_bullets(tmp_path: Path):
    from agent_anystack.memory.fact import FactType, OkfFact
    from agent_anystack.memory.store import OkfStore
    from agent_anystack.office_qa import OfficeQaService
    from agent_anystack.runs.journal import RunJournal

    okf = OkfStore(tmp_path / "okf.db")
    journal = RunJournal(tmp_path / "journal.jsonl")
    f1 = OkfFact(
        id="fact-101",
        type=FactType.constraint,
        scope="team:eng",
        body="All PRs must have 2 approvals.",
        created_by_user="u1",
        source_run="r1",
    )
    okf.upsert(f1)

    qa = OfficeQaService(
        journal,
        okf,
        adapter=FailingAdapter(),
        phrase_model="test-model",
        use_llm_phrase=True,
    )

    result = await qa.ask(message="What is the policy on PR approvals?", team="eng")
    assert result.kind.value == "knowledge"
    assert "From team OKF (team:eng):" in result.answer
    assert "[fact-101] All PRs must have 2 approvals." in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].fact_id == "fact-101"


@pytest.mark.asyncio
async def test_office_qa_llm_phrasing_success(tmp_path: Path):
    from agent_anystack.memory.fact import FactType, OkfFact
    from agent_anystack.memory.store import OkfStore
    from agent_anystack.office_qa import OfficeQaService
    from agent_anystack.runs.journal import RunJournal

    okf = OkfStore(tmp_path / "okf.db")
    journal = RunJournal(tmp_path / "journal.jsonl")
    f1 = OkfFact(
        id="fact-101",
        type=FactType.constraint,
        scope="team:eng",
        body="All PRs must have 2 approvals.",
        created_by_user="u1",
        source_run="r1",
    )
    okf.upsert(f1)

    phrased = "According to team policy, all pull requests require two approvals [fact-101]."
    qa = OfficeQaService(
        journal,
        okf,
        adapter=SuccessfulAdapter(phrased),
        phrase_model="test-model",
        use_llm_phrase=True,
    )

    result = await qa.ask(message="What is the policy on PR approvals?", team="eng")
    assert result.kind.value == "knowledge"
    assert result.answer == phrased
    assert len(result.citations) == 1
    assert result.citations[0].fact_id == "fact-101"


@pytest.mark.asyncio
async def test_get_office_qa_resolves_adapter(tmp_path: Path):
    from agent_anystack.api.office import get_office_qa
    from agent_anystack.adapters.connections import ConnectionStore

    office_dir = tmp_path / "office"
    office_dir.mkdir(parents=True, exist_ok=True)
    repo = OfficeRepository(office_dir)
    repo.update_orchestrator(
        OrchestratorConfigUpdate(
            connection_id="bedrock",
            office_qa_llm=True,
            model="us.amazon.nova-lite-v1:0",
        )
    )

    conn_store = ConnectionStore(tmp_path)
    bed = conn_store.get("bedrock")
    assert bed is not None
    bed.meta = {"auth": "api_key", "api_key": "bed-key", "region": "us-east-1"}
    conn_store.upsert(bed)

    settings = Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/office.db",
    )

    qa_service = get_office_qa(settings=settings, repo=repo)
    assert qa_service.use_llm_phrase is True
    assert isinstance(qa_service.adapter, BedrockAdapter)
    assert qa_service.phrase_model == "us.amazon.nova-lite-v1:0"


@pytest.mark.asyncio
async def test_background_okf_extract_resilience(tmp_path: Path):
    from agent_anystack.api.chat import _background_okf_extract
    from agent_anystack.memory.extract import ExtractJob
    from agent_anystack.memory.store import OkfStore

    office_dir = tmp_path / "office"
    office_dir.mkdir(parents=True, exist_ok=True)
    repo = OfficeRepository(office_dir)
    repo.update_orchestrator(
        OrchestratorConfigUpdate(
            connection_id="invalid-conn-id",
            okf_extract_enabled=True,
            okf_extract_llm=True,
            okf_extract_remember_lines=True,
        )
    )

    settings = Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/office.db",
    )

    job = ExtractJob(
        run_id="run-bg-1",
        agent_id="test-agent",
        user_id="user-1",
        team="eng",
        model="llama3.2",
        user_message="remember: API base URL is https://api.test.com",
        assistant_text="Noted.",
    )

    # Should not raise exception despite invalid connection id, falling back to deterministic extraction
    await _background_okf_extract(job, settings)

    store = OkfStore(tmp_path / "office.db")
    facts = store.list_team_facts("eng")
    assert len(facts) == 1
    assert facts[0].body == "API base URL is https://api.test.com"
