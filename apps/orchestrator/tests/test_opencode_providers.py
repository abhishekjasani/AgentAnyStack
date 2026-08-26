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
            id="groq-test",
            kind="inference",
            product="openai-compatible",
            label="Groq Test",
            meta={
                "base_url": "https://api.groq.com/openai/v1",
                "api_key": "gsk_secret123",
                "preset": "groq",
            },
            verified_models=[
                VerifiedInferenceModel(
                    model_id="allam-2-7b",
                    display_name="Allam 2 7B",
                    verified_at="2026-08-26T12:00:00+00:00",
                )
            ],
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

    assert "groq-test" in config["provider"]
    groq_provider = config["provider"]["groq-test"]
    assert groq_provider["npm"] == "@ai-sdk/openai-compatible"
    assert groq_provider["name"] == "Groq Test"
    assert groq_provider["options"]["baseURL"] == "https://api.groq.com/openai/v1"
    assert groq_provider["options"]["apiKey"] == "gsk_secret123"
    assert "allam-2-7b" in groq_provider["models"]
    assert groq_provider["models"]["allam-2-7b"]["name"] == "Allam 2 7B"


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
