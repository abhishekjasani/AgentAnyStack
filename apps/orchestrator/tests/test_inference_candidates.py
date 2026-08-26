from __future__ import annotations

from pathlib import Path
import pytest

from agent_anystack.adapters.bedrock_store import (
    BedrockModelEntry,
    BedrockProviderStore,
)
from agent_anystack.adapters.connections import (
    ConnectionStore,
    StackConnection,
    VerifiedInferenceModel,
)
from agent_anystack.adapters.opencode.providers import list_inference_candidates


@pytest.mark.asyncio
async def test_inference_candidates_bedrock_verified_models_isolation(tmp_path: Path):
    conn_store = ConnectionStore(tmp_path)
    bedrock_store = BedrockProviderStore(tmp_path)

    # Put extra models into global bedrock_models.json
    bedrock_store.upsert_model(
        BedrockModelEntry(
            id="mistral.ministral-3-3b-instruct",
            display_name="mistral.ministral-3-3b-instruct",
            verified_at="2026-08-25T16:06:51+00:00",
            region="ap-south-1",
        )
    )
    bedrock_store.upsert_model(
        BedrockModelEntry(
            id="moonshot.kimi-k2-thinking",
            display_name="moonshot.kimi-k2-thinking",
            verified_at="2026-08-26T08:51:25+00:00",
            region="ap-south-1",
        )
    )

    # Delete default bedrock connection to isolate test
    conn_store.delete_connection("bedrock")
    conn_store.delete_connection("ollama")

    # Create a custom Bedrock connection with only one verified model
    conn = StackConnection(
        id="bedrock-test",
        kind="inference",
        product="bedrock",
        label="bedrock-test",
        enabled=True,
        verified_models=[
            VerifiedInferenceModel(
                model_id="mistral.mistral-7b-instruct-v0:2",
                display_name="mistral.mistral-7b-instruct-v0:2",
                verified_at="2026-08-26T12:20:10+00:00",
                region="ap-south-1",
            )
        ],
    )
    conn_store.upsert(conn)

    candidates = await list_inference_candidates(
        conn_store,
        bedrock=bedrock_store,
        ollama=None,
    )

    test_models = [
        c["model_id"]
        for c in candidates
        if c["inference_connection_id"] == "bedrock-test"
    ]

    assert test_models == ["mistral.mistral-7b-instruct-v0:2"]
    assert "mistral.ministral-3-3b-instruct" not in test_models
    assert "moonshot.kimi-k2-thinking" not in test_models


@pytest.mark.asyncio
async def test_inference_candidates_legacy_fallback_when_unmigrated(tmp_path: Path):
    conn_store = ConnectionStore(tmp_path)
    bedrock_store = BedrockProviderStore(tmp_path)

    # Global catalog has models
    bedrock_store.upsert_model(
        BedrockModelEntry(
            id="amazon.nova-lite-v1:0",
            display_name="amazon.nova-lite-v1:0",
            verified_at="2026-08-26T10:00:00+00:00",
            region="us-east-1",
        )
    )

    # Default 'bedrock' connection with empty verified_models
    bedrock_conn = conn_store.get("bedrock")
    assert bedrock_conn is not None
    assert len(bedrock_conn.verified_models) == 0

    candidates = await list_inference_candidates(
        conn_store,
        bedrock=bedrock_store,
        ollama=None,
    )

    bedrock_candidates = [
        c["model_id"]
        for c in candidates
        if c["inference_connection_id"] == "bedrock"
    ]

    assert "amazon.nova-lite-v1:0" in bedrock_candidates


@pytest.mark.asyncio
async def test_inference_candidates_remove_verified_model(tmp_path: Path):
    conn_store = ConnectionStore(tmp_path)
    bedrock_store = BedrockProviderStore(tmp_path)

    conn_store.delete_connection("bedrock")
    conn_store.delete_connection("ollama")

    conn = StackConnection(
        id="bedrock-custom",
        kind="inference",
        product="bedrock",
        label="bedrock-custom",
        enabled=True,
        verified_models=[
            VerifiedInferenceModel(
                model_id="model-a",
                display_name="model-a",
                verified_at="2026-08-26T12:00:00+00:00",
                region="us-east-1",
            ),
            VerifiedInferenceModel(
                model_id="model-b",
                display_name="model-b",
                verified_at="2026-08-26T12:00:00+00:00",
                region="us-east-1",
            ),
        ],
    )
    conn_store.upsert(conn)

    candidates = await list_inference_candidates(
        conn_store,
        bedrock=bedrock_store,
        ollama=None,
    )
    model_ids = [c["model_id"] for c in candidates if c["inference_connection_id"] == "bedrock-custom"]
    assert set(model_ids) == {"model-a", "model-b"}

    # Remove model-b
    conn_store.remove_verified_model("bedrock-custom", "model-b")

    candidates_after = await list_inference_candidates(
        conn_store,
        bedrock=bedrock_store,
        ollama=None,
    )
    model_ids_after = [c["model_id"] for c in candidates_after if c["inference_connection_id"] == "bedrock-custom"]
    assert model_ids_after == ["model-a"]
