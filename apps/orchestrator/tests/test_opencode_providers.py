from __future__ import annotations

import json
from pathlib import Path
import pytest

from agent_anystack.adapters.connections import (
    INFERENCE_PRESETS,
    ConnectionStore,
    RegisteredOpencodeModel,
    StackConnection,
    VerifiedInferenceModel,
)
from agent_anystack.adapters.opencode.providers import (
    build_opencode_config,
    candidate_pairs,
    prepare_inject,
)


def test_inference_presets_definitions():
    assert "groq" in INFERENCE_PRESETS
    assert "openrouter" in INFERENCE_PRESETS
    assert "mistral" in INFERENCE_PRESETS
    assert "together" in INFERENCE_PRESETS
    assert "deepseek" in INFERENCE_PRESETS
    assert "openai" in INFERENCE_PRESETS
    assert "zen" in INFERENCE_PRESETS
    assert "ollama" in INFERENCE_PRESETS
    assert "custom" in INFERENCE_PRESETS

    assert INFERENCE_PRESETS["zen"]["base_url"] == "https://opencode.ai/zen/v1"
    assert INFERENCE_PRESETS["zen"].base_url == "https://opencode.ai/zen/v1"
    assert INFERENCE_PRESETS["openrouter"]["base_url"] == "https://openrouter.ai/api/v1"
    assert INFERENCE_PRESETS["openrouter"].base_url == "https://openrouter.ai/api/v1"
    assert INFERENCE_PRESETS["mistral"]["base_url"] == "https://api.mistral.ai/v1"
    assert INFERENCE_PRESETS["mistral"].default_context_limit == 32768
    assert INFERENCE_PRESETS["groq"]["base_url"] == "https://api.groq.com/openai/v1"
    assert INFERENCE_PRESETS["groq"].default_output_limit == 4096


def test_candidate_pairs():
    # OpenAI-compatible with custom connection id
    pairs = candidate_pairs("openai-compatible", "allam-2-7b", inference_connection_id="groq-test")
    assert pairs == [
        ("groq-test", "allam-2-7b"),
        ("openai-compatible", "allam-2-7b"),
    ]

    # OpenAI-compatible with slash-separated model ID (OpenRouter)
    pairs_or = candidate_pairs(
        "openai-compatible",
        "anthropic/claude-3.5-sonnet",
        inference_connection_id="openrouter-prod",
    )
    assert pairs_or == [
        ("openrouter-prod", "anthropic/claude-3.5-sonnet"),
        ("openai-compatible", "anthropic/claude-3.5-sonnet"),
        ("anthropic", "claude-3.5-sonnet"),
    ]

    # Ollama
    pairs_ollama = candidate_pairs("ollama", "qwen2.5:7b", inference_connection_id="ollama-local")
    assert pairs_ollama == [
        ("ollama-local", "qwen2.5:7b"),
        ("ollama", "qwen2.5:7b"),
        ("openai-compatible", "qwen2.5:7b"),
    ]

    # Bedrock
    pairs_bedrock = candidate_pairs("bedrock", "amazon.nova-lite-v1:0", inference_connection_id="bed-prod")
    assert pairs_bedrock == [
        ("amazon-bedrock", "amazon.nova-lite-v1:0"),
        ("bedrock", "amazon.nova-lite-v1:0"),
    ]


def test_build_opencode_config_openai_compatible(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="custom-test",
            kind="inference",
            product="openai-compatible",
            label="Custom Test",
            meta={
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-secret123",
                "preset": "custom",
            },
            verified_models=[
                VerifiedInferenceModel(
                    model_id="custom-model",
                    display_name="Custom Model",
                    verified_at="2026-08-26T12:00:00+00:00",
                )
            ],
        )
    )

    candidate_model = {
        "inference_connection_id": "custom-test",
        "inference_product": "openai-compatible",
        "model_id": "custom-model",
        "display_name": "Custom Model",
    }

    config = build_opencode_config(
        models=[candidate_model],
        ollama_base_url="http://127.0.0.1:11434/v1",
        bedrock_region="us-east-1",
        store=store,
    )

    assert "custom-test" in config["provider"]
    custom_provider = config["provider"]["custom-test"]
    assert custom_provider["npm"] == "@ai-sdk/openai-compatible"
    assert custom_provider["name"] == "Custom Test"
    assert custom_provider["options"]["baseURL"] == "https://api.example.com/v1"
    assert custom_provider["options"]["apiKey"] == "sk-secret123"
    assert "custom-model" in custom_provider["models"]
    assert custom_provider["models"]["custom-model"]["name"] == "Custom Model"
    # Unconstrained when no limit configured for generic openai-compatible
    assert "limit" not in custom_provider["models"]["custom-model"]


def test_build_opencode_config_with_preset_limits(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="mistral-conn",
            kind="inference",
            product="openai-compatible",
            label="Mistral Cloud",
            meta={
                "preset": "mistral",
                "api_key": "mistral-secret-key",
            },
        )
    )

    candidate_model = {
        "inference_connection_id": "mistral-conn",
        "inference_product": "openai-compatible",
        "model_id": "mistral-large-latest",
        "display_name": "Mistral Large",
    }

    config = build_opencode_config(
        models=[candidate_model],
        ollama_base_url="http://127.0.0.1:11434/v1",
        bedrock_region="us-east-1",
        store=store,
    )

    mistral_provider = config["provider"]["mistral-conn"]
    assert mistral_provider["options"]["baseURL"] == "https://api.mistral.ai/v1"
    assert mistral_provider["options"]["apiKey"] == "mistral-secret-key"
    assert mistral_provider["models"]["mistral-large-latest"]["limit"] == {
        "context": 32768,
        "output": 4096,
    }


def test_build_opencode_config_with_openrouter_slashed_models(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="openrouter-conn",
            kind="inference",
            product="openai-compatible",
            label="OpenRouter",
            meta={
                "preset": "openrouter",
                "api_key": "sk-or-test",
            },
        )
    )

    candidate_model = {
        "inference_connection_id": "openrouter-conn",
        "inference_product": "openai-compatible",
        "model_id": "meta-llama/llama-3.3-70b-instruct",
        "display_name": "Llama 3.3 70B",
    }

    config = build_opencode_config(
        models=[candidate_model],
        ollama_base_url="http://127.0.0.1:11434/v1",
        bedrock_region="us-east-1",
        store=store,
    )

    or_provider = config["provider"]["openrouter-conn"]
    assert or_provider["options"]["baseURL"] == "https://openrouter.ai/api/v1"
    assert or_provider["options"]["apiKey"] == "sk-or-test"
    assert "meta-llama/llama-3.3-70b-instruct" in or_provider["models"]
    assert or_provider["models"]["meta-llama/llama-3.3-70b-instruct"]["limit"] == {
        "output": 4096,
        "context": 4096,
    }


def test_build_opencode_config_with_custom_limits(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="groq-test",
            kind="inference",
            product="openai-compatible",
            label="Groq Test",
            meta={
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "gsk_secret123",
                "context_limit": 32768,
                "output_limit": 4096,
            },
        )
    )

    candidate_model = {
        "inference_connection_id": "groq-test",
        "inference_product": "openai-compatible",
        "model_id": "allam-2-7b",
        "display_name": "Allam 2 7B",
    }

    config = build_opencode_config(
        models=[candidate_model],
        ollama_base_url="http://127.0.0.1:11434/v1",
        bedrock_region="us-east-1",
        store=store,
    )

    groq_provider = config["provider"]["groq-test"]
    assert groq_provider["models"]["allam-2-7b"]["limit"] == {
        "context": 32768,
        "output": 4096,
    }


def test_prepare_inject_writes_custom_provider_config(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="groq-test",
            kind="inference",
            product="openai-compatible",
            label="Groq Test",
            meta={
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "gsk_secret456",
            },
        )
    )
    oc_conn = store.get_required("opencode")

    candidate_model = {
        "inference_connection_id": "groq-test",
        "inference_product": "openai-compatible",
        "model_id": "allam-2-7b",
        "display_name": "Allam 2 7B",
    }

    cfg_path, extra_env, cfg_hash = prepare_inject(
        database_url=f"sqlite:///{tmp_path}/aas.db",
        connection=oc_conn,
        extra_models=[candidate_model],
        ollama_base_url="http://127.0.0.1:11434/v1",
        store=store,
    )

    assert cfg_path.is_file()
    assert extra_env["OPENCODE_CONFIG"] == str(cfg_path)
    assert len(cfg_hash) == 16

    saved_data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "groq-test" in saved_data["provider"]
    assert saved_data["provider"]["groq-test"]["options"]["apiKey"] == "gsk_secret456"
    assert saved_data["provider"]["groq-test"]["options"]["baseURL"] == "https://api.groq.com/openai/v1"
    assert "allam-2-7b" in saved_data["provider"]["groq-test"]["models"]


@pytest.mark.asyncio
async def test_presets_api_endpoint(tmp_path: Path):
    from httpx import ASGITransport, AsyncClient
    from agent_anystack.config import Settings, get_settings
    from agent_anystack.main import create_app

    office_dir = tmp_path / "office"
    office_dir.mkdir(parents=True, exist_ok=True)
    (office_dir / "org.yaml").write_text("id: my-org\nname: Test Org\n", encoding="utf-8")

    settings = Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/stacks/connections/presets", headers={"X-User-Id": "admin"})
            assert resp.status_code == 200
            data = resp.json()
            assert "presets" in data
            presets_by_id = {p["id"]: p for p in data["presets"]}
            assert "groq" in presets_by_id
            assert presets_by_id["groq"]["base_url"] == "https://api.groq.com/openai/v1"
            assert presets_by_id["groq"]["default_context_limit"] == 32768
            assert presets_by_id["groq"]["default_output_limit"] == 4096
            assert presets_by_id["groq"]["requires_api_key"] is True

            assert "zen" in presets_by_id
            assert presets_by_id["zen"]["base_url"] == "https://opencode.ai/zen/v1"

            assert "ollama" in presets_by_id
            assert presets_by_id["ollama"]["requires_api_key"] is False
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_resolve_inference_adapter_uses_preset_base_url(tmp_path: Path):
    from agent_anystack.adapters.connections import resolve_inference_adapter
    from agent_anystack.config import Settings

    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="mistral-test",
            kind="inference",
            product="openai-compatible",
            meta={"preset": "mistral"},
        )
    )

    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db")
    adapter = resolve_inference_adapter(
        connection_id="mistral-test",
        store=store,
        settings=settings,
    )
    assert adapter.base_url == "https://api.mistral.ai/v1"


def test_build_opencode_config_zen_preset(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="zen-conn",
            kind="inference",
            product="openai-compatible",
            label="Zen",
            meta={
                "preset": "zen",
                "api_key": "zen-api-key",
            },
        )
    )

    candidate_model = {
        "inference_connection_id": "zen-conn",
        "inference_product": "openai-compatible",
        "model_id": "zen-1",
        "display_name": "Zen 1",
    }

    config = build_opencode_config(
        models=[candidate_model],
        ollama_base_url="http://127.0.0.1:11434/v1",
        bedrock_region="us-east-1",
        store=store,
    )

    zen_provider = config["provider"]["zen-conn"]
    assert zen_provider["options"]["baseURL"] == "https://opencode.ai/zen/v1"
    assert zen_provider["options"]["apiKey"] == "zen-api-key"
    assert "zen-1" in zen_provider["models"]


def test_build_opencode_config_deepseek_and_together_presets(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.upsert(
        StackConnection(
            id="deepseek-conn",
            kind="inference",
            product="openai-compatible",
            label="DeepSeek",
            meta={
                "preset": "deepseek",
                "api_key": "ds-key",
            },
        )
    )
    store.upsert(
        StackConnection(
            id="together-conn",
            kind="inference",
            product="openai-compatible",
            label="Together AI",
            meta={
                "preset": "together",
                "api_key": "tog-key",
            },
        )
    )

    models = [
        {
            "inference_connection_id": "deepseek-conn",
            "inference_product": "openai-compatible",
            "model_id": "deepseek-chat",
            "display_name": "DeepSeek Chat",
        },
        {
            "inference_connection_id": "together-conn",
            "inference_product": "openai-compatible",
            "model_id": "meta-llama/Llama-3-70b-chat-hf",
            "display_name": "Llama 3 70B",
        },
    ]

    config = build_opencode_config(
        models=models,
        ollama_base_url="http://127.0.0.1:11434/v1",
        bedrock_region="us-east-1",
        store=store,
    )

    ds_provider = config["provider"]["deepseek-conn"]
    assert ds_provider["options"]["baseURL"] == "https://api.deepseek.com/v1"
    assert ds_provider["options"]["apiKey"] == "ds-key"
    assert ds_provider["models"]["deepseek-chat"]["limit"] == {"output": 4096, "context": 4096}

    tog_provider = config["provider"]["together-conn"]
    assert tog_provider["options"]["baseURL"] == "https://api.together.xyz/v1"
    assert tog_provider["options"]["apiKey"] == "tog-key"
    assert tog_provider["models"]["meta-llama/Llama-3-70b-chat-hf"]["limit"] == {"output": 4096, "context": 4096}


@pytest.mark.asyncio
async def test_create_connection_with_preset_defaults_base_url(tmp_path: Path, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from agent_anystack.config import Settings, get_settings
    from agent_anystack.main import create_app

    office_dir = tmp_path / "office"
    office_dir.mkdir(parents=True, exist_ok=True)
    (office_dir / "org.yaml").write_text("id: my-org\nname: Test Org\n", encoding="utf-8")

    settings = Settings(
        office_repo_path=str(office_dir),
        database_url=f"sqlite:///{tmp_path}/test.db",
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    # Mock complete_chat or list_models so connection verification succeeds without real network
    async def mock_list_models(self):
        return ["mistral-large-latest"]

    from agent_anystack.adapters.llm import OpenAICompatibleAdapter
    monkeypatch.setattr(OpenAICompatibleAdapter, "list_models", mock_list_models)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/stacks/connections",
                headers={"X-User-Id": "admin"},
                json={
                    "id": "my-mistral",
                    "preset": "mistral",
                    "api_key": "test-key",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == "my-mistral"
            assert data["meta"]["preset"] == "mistral"
            assert data["meta"]["base_url"] == "https://api.mistral.ai/v1"
            assert data["status"] == "ok"
    finally:
        app.dependency_overrides.pop(get_settings, None)
