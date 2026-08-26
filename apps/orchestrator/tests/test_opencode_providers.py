from __future__ import annotations

import json
from pathlib import Path
import pytest

from agent_anystack.adapters.connections import (
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


def test_candidate_pairs():
    # OpenAI-compatible with custom connection id
    pairs = candidate_pairs("openai-compatible", "allam-2-7b", inference_connection_id="groq-test")
    assert pairs == [
        ("groq-test", "allam-2-7b"),
        ("openai-compatible", "allam-2-7b"),
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
