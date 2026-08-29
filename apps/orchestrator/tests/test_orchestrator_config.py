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
    assert cfg.extract_temperature == 0.0
    assert cfg.office_qa_temperature == 0.2


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


class RecordingAdapter:
    def __init__(self, response_text: str = ""):
        self.response_text = response_text
        self.calls: list[dict] = []

    async def complete_chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.response_text


@pytest.mark.asyncio
async def test_sampling_policy_extract_and_office_qa(tmp_path: Path):
    from agent_anystack.memory.extract import ExtractJob, run_okf_extract
    from agent_anystack.memory.fact import FactType, OkfFact
    from agent_anystack.memory.store import OkfStore
    from agent_anystack.office_qa import OfficeQaService
    from agent_anystack.runs.journal import RunJournal

    # 1. OKF Extract respects orchestrator extract_temperature
    extract_adapter = RecordingAdapter(
        '[{"body": "Fact 1", "type": "constraint", "scope": "team:eng", "confidence": 0.9}]'
    )
    store = OkfStore(tmp_path / "test_sampling.db")
    job = ExtractJob(
        run_id="run-sample-1",
        agent_id="test-agent",
        user_id="user-1",
        team="eng",
        model="llama3.2",
        user_message="User message",
        assistant_text="Assistant reply",
    )
    await run_okf_extract(
        job,
        okf=store,
        adapter=extract_adapter,
        temperature=0.05,
    )
    assert len(extract_adapter.calls) == 1
    assert extract_adapter.calls[0]["temperature"] == 0.05

    # 2. Office Q&A soft phrasing respects office_qa_temperature
    f1 = OkfFact(
        id="fact-201",
        type=FactType.constraint,
        scope="team:eng",
        body="Secret port is 9090.",
        created_by_user="u1",
        source_run="r1",
    )
    store.upsert(f1)
    journal = RunJournal(tmp_path / "sample_journal.jsonl")
    qa_adapter = RecordingAdapter("The secret port is 9090 [fact-201].")
    qa_service = OfficeQaService(
        journal,
        store,
        adapter=qa_adapter,
        phrase_model="test-model",
        use_llm_phrase=True,
        temperature=0.35,
    )
    result = await qa_service.ask(message="What is the secret port?", team="eng")
    assert result.kind.value == "knowledge"
    assert len(qa_adapter.calls) == 1
    assert qa_adapter.calls[0]["temperature"] == 0.35


@pytest.mark.asyncio
async def test_office_config_api_temperature_update(tmp_path: Path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from agent_anystack.api.office import router as office_router
    from agent_anystack.api.agents import get_office_repo
    from agent_anystack.config import get_settings

    office_dir = tmp_path / "office"
    office_dir.mkdir(parents=True, exist_ok=True)
    (office_dir / "org.yaml").write_text("id: my-org\nname: Test Org\n", encoding="utf-8")
    repo = OfficeRepository(office_dir)
    repo.load_orchestrator()

    app = FastAPI()
    app.include_router(office_router)
    app.dependency_overrides[get_office_repo] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # GET config
        res = await client.get("/office/config")
        assert res.status_code == 200
        orc = res.json()["orchestrator"]
        assert orc["extract_temperature"] == 0.0
        assert orc["office_qa_temperature"] == 0.2

        # PUT config updating temperatures
        put_res = await client.put(
            "/office/config",
            json={
                "extract_temperature": 0.1,
                "office_qa_temperature": 0.4,
            },
        )
        assert put_res.status_code == 200
        updated_orc = put_res.json()["orchestrator"]
        assert updated_orc["extract_temperature"] == 0.1
        assert updated_orc["office_qa_temperature"] == 0.4

        # Verify persisted in yaml
        reloaded = repo.load_orchestrator()
        assert reloaded.extract_temperature == 0.1
        assert reloaded.office_qa_temperature == 0.4


def test_orchestrator_config_serialization_and_deserialization():
    # 1. Default serialization
    cfg = OrchestratorConfig()
    dumped = cfg.model_dump()
    assert dumped["connection_id"] == "ollama-local"
    assert dumped["model"] == "llama3.2"
    assert dumped["extract_temperature"] == 0.0
    assert dumped["office_qa_temperature"] == 0.2

    # 2. JSON roundtrip with custom connection_id
    custom_cfg = OrchestratorConfig(
        id="custom-office",
        name="Custom Office",
        model="claude-3-5-sonnet",
        connection_id="openrouter-cloud",
        extract_temperature=0.05,
        office_qa_temperature=0.3,
    )
    json_str = custom_cfg.model_dump_json()
    reloaded = OrchestratorConfig.model_validate_json(json_str)
    assert reloaded.connection_id == "openrouter-cloud"
    assert reloaded.model == "claude-3-5-sonnet"
    assert reloaded.extract_temperature == 0.05
    assert reloaded.office_qa_temperature == 0.3

    # 3. Update model serialization
    update = OrchestratorConfigUpdate(
        connection_id="bedrock-prod",
        model="amazon.titan-text-v1",
    )
    update_dump = update.model_dump(exclude_unset=True)
    assert update_dump == {
        "connection_id": "bedrock-prod",
        "model": "amazon.titan-text-v1",
    }


def test_resolve_inference_adapter_bedrock_iam(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    bed = store.get("bedrock")
    assert bed is not None
    bed.meta = {
        "auth": "iam",
        "region": "eu-central-1",
        "aws_access_key_id": "AKIA_TEST_KEY",
        "aws_secret_access_key": "SECRET_TEST_KEY",
    }
    store.upsert(bed)

    settings = Settings()
    adapter = resolve_inference_adapter(
        connection_id="bedrock",
        store=store,
        settings=settings,
    )
    assert isinstance(adapter, BedrockAdapter)
    assert adapter.region == "eu-central-1"
    assert adapter.auth_mode == "iam"
    assert adapter.access_key_id == "AKIA_TEST_KEY"
    assert adapter.secret_access_key == "SECRET_TEST_KEY"


@pytest.mark.asyncio
async def test_run_okf_extract_with_bedrock_and_openai_adapters(tmp_path: Path):
    from agent_anystack.memory.extract import ExtractJob, run_okf_extract
    from agent_anystack.memory.store import OkfStore

    store = OkfStore(tmp_path / "okf_adapters.db")

    # 1. Bedrock adapter response
    bedrock_payload = '{"facts":[{"type":"decision","body":"AWS S3 bucket named assets-prod is used."}]}'
    bedrock_adapter = SuccessfulAdapter(bedrock_payload)
    job_bedrock = ExtractJob(
        run_id="run-bed-1",
        agent_id="infra-agent",
        user_id="alice",
        team="devops",
        model="us.amazon.nova-lite-v1:0",
        user_message="Which S3 bucket do we use for assets?",
        assistant_text="We use assets-prod.",
    )
    count_bed = await run_okf_extract(
        job_bedrock,
        okf=store,
        adapter=bedrock_adapter,
        use_llm=True,
        use_remember_lines=False,
    )
    assert count_bed == 1
    facts = store.list_team_facts("devops")
    assert len(facts) == 1
    assert facts[0].body == "AWS S3 bucket named assets-prod is used."
    assert facts[0].type.value == "decision"

    # 2. OpenAI-compatible adapter response (with markdown fence)
    openai_payload = '```json\n{"facts":[{"type":"constraint","body":"Max upload size is 50MB."}]}\n```'
    openai_adapter = SuccessfulAdapter(openai_payload)
    job_openai = ExtractJob(
        run_id="run-oai-1",
        agent_id="api-agent",
        user_id="bob",
        team="devops",
        model="gpt-4o",
        user_message="What is the max upload size?",
        assistant_text="It is 50MB.",
    )
    count_openai = await run_okf_extract(
        job_openai,
        okf=store,
        adapter=openai_adapter,
        use_llm=True,
        use_remember_lines=False,
    )
    assert count_openai == 1
    all_facts = store.list_team_facts("devops")
    assert len(all_facts) == 2
    assert any(f.body == "Max upload size is 50MB." and f.type.value == "constraint" for f in all_facts)


@pytest.mark.asyncio
async def test_office_qa_service_with_bedrock_and_openai_adapters(tmp_path: Path):
    from agent_anystack.memory.fact import FactType, OkfFact
    from agent_anystack.memory.store import OkfStore
    from agent_anystack.office_qa import OfficeQaService
    from agent_anystack.runs.journal import RunJournal

    okf = OkfStore(tmp_path / "okf_qa.db")
    journal = RunJournal(tmp_path / "journal_qa.jsonl")
    f1 = OkfFact(
        id="fact-arch-1",
        type=FactType.decision,
        scope="team:platform",
        body="Kubernetes clusters use Cilium CNI.",
        created_by_user="u1",
        source_run="r1",
    )
    okf.upsert(f1)

    # Bedrock adapter soft phrasing
    bedrock_phrased = "Our Kubernetes clusters use Cilium CNI for networking [fact-arch-1]."
    qa_bedrock = OfficeQaService(
        journal,
        okf,
        adapter=SuccessfulAdapter(bedrock_phrased),
        phrase_model="us.amazon.nova-pro-v1:0",
        use_llm_phrase=True,
    )
    res_bed = await qa_bedrock.ask(message="What CNI do we use in Kubernetes?", team="platform")
    assert res_bed.kind.value == "knowledge"
    assert res_bed.answer == bedrock_phrased
    assert len(res_bed.citations) == 1
    assert res_bed.citations[0].fact_id == "fact-arch-1"

    # OpenAI compatible adapter soft phrasing
    openai_phrased = "Cilium CNI is configured across Kubernetes clusters [fact-arch-1]."
    qa_openai = OfficeQaService(
        journal,
        okf,
        adapter=SuccessfulAdapter(openai_phrased),
        phrase_model="llama3.2",
        use_llm_phrase=True,
    )
    res_openai = await qa_openai.ask(message="What CNI do we use in Kubernetes?", team="platform")
    assert res_openai.kind.value == "knowledge"
    assert res_openai.answer == openai_phrased
    assert len(res_openai.citations) == 1
    assert res_openai.citations[0].fact_id == "fact-arch-1"


@pytest.mark.asyncio
async def test_okf_extract_fallback_on_malformed_json(tmp_path: Path):
    from agent_anystack.memory.extract import ExtractJob, run_okf_extract
    from agent_anystack.memory.store import OkfStore

    store = OkfStore(tmp_path / "okf_malformed.db")
    malformed_adapter = SuccessfulAdapter("Here are the facts: {not valid json... at all")
    job = ExtractJob(
        run_id="run-malformed-1",
        agent_id="test-agent",
        user_id="user-1",
        team="backend",
        model="test-model",
        user_message="Here is some info.\nremember: Database cache TTL is 300 seconds.",
        assistant_text="Understood.",
    )

    # Malformed JSON should not raise, should fall back to remember: line
    written = await run_okf_extract(
        job,
        okf=store,
        adapter=malformed_adapter,
        use_llm=True,
        use_remember_lines=False,  # Initially false, but fallback should pick up remember line on error
    )
    assert written == 1
    facts = store.list_team_facts("backend")
    assert len(facts) == 1
    assert facts[0].body == "Database cache TTL is 300 seconds."


@pytest.mark.asyncio
async def test_okf_extract_fallback_on_exception_without_remember_lines(tmp_path: Path):
    from agent_anystack.memory.extract import ExtractJob, run_okf_extract
    from agent_anystack.memory.store import OkfStore

    store = OkfStore(tmp_path / "okf_no_rem.db")
    job = ExtractJob(
        run_id="run-fail-1",
        agent_id="test-agent",
        user_id="user-1",
        team="backend",
        model="test-model",
        user_message="Regular conversation without remember directives.",
        assistant_text="I can help with that.",
    )

    # Should handle failure gracefully and return 0
    written = await run_okf_extract(
        job,
        okf=store,
        adapter=FailingAdapter(),
        use_llm=True,
        use_remember_lines=False,
    )
    assert written == 0
    assert len(store.list_team_facts("backend")) == 0


@pytest.mark.asyncio
async def test_okf_extract_fallback_on_none_adapter(tmp_path: Path):
    from agent_anystack.memory.extract import ExtractJob, run_okf_extract
    from agent_anystack.memory.store import OkfStore

    store = OkfStore(tmp_path / "okf_none_adapter.db")
    job = ExtractJob(
        run_id="run-none-1",
        agent_id="test-agent",
        user_id="user-1",
        team="security",
        model="test-model",
        user_message="Setup guide.\nremember: Auth uses OAuth2 with PKCE.",
        assistant_text="Security rules noted.",
    )

    # Passing adapter=None when use_llm=True should trigger safe fallback
    written = await run_okf_extract(
        job,
        okf=store,
        adapter=None,
        use_llm=True,
        use_remember_lines=False,
    )
    assert written == 1
    facts = store.list_team_facts("security")
    assert len(facts) == 1
    assert facts[0].body == "Auth uses OAuth2 with PKCE."


@pytest.mark.asyncio
async def test_office_qa_fallback_on_unverified_citations(tmp_path: Path):
    from agent_anystack.memory.fact import FactType, OkfFact
    from agent_anystack.memory.store import OkfStore
    from agent_anystack.office_qa import OfficeQaService
    from agent_anystack.runs.journal import RunJournal

    okf = OkfStore(tmp_path / "okf_qa_unverified.db")
    journal = RunJournal(tmp_path / "journal_qa_unverified.jsonl")
    f1 = OkfFact(
        id="fact-real-1",
        type=FactType.constraint,
        scope="team:finance",
        body="Expenses over $500 require VP signoff.",
        created_by_user="u1",
        source_run="r1",
    )
    okf.upsert(f1)

    # LLM returns text citing an imaginary fact [fact-fake-999] not in retrieved facts
    hallucinated_adapter = SuccessfulAdapter(
        "Expenses over $500 require CFO signoff [fact-fake-999]."
    )
    qa_service = OfficeQaService(
        journal,
        okf,
        adapter=hallucinated_adapter,
        phrase_model="test-model",
        use_llm_phrase=True,
    )

    result = await qa_service.ask(message="What is the expense signoff threshold?", team="finance")
    assert result.kind.value == "knowledge"
    # When citation check fails, it falls back to raw bullet formatting of verified facts
    assert "From team OKF (team:finance):" in result.answer
    assert "[fact-real-1] Expenses over $500 require VP signoff." in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].fact_id == "fact-real-1"


