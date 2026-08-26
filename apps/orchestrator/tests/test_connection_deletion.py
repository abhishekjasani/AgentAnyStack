from __future__ import annotations

import json
from pathlib import Path
import pytest

from agent_anystack.adapters.connections import (
    ConnectionNotFound,
    ConnectionStore,
    RegisteredOpencodeModel,
    StackConnection,
    _DEFAULTS,
)
from agent_anystack.api.connections import delete_connection_card


def test_initial_seed_on_empty_store(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    conns = store.list()
    ids = {c.id for c in conns}
    assert "ollama" in ids
    assert "bedrock" in ids
    assert "opencode" in ids


def test_delete_connection_and_no_resurrection_on_reinit(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    assert store.get("ollama") is not None
    assert store.get("bedrock") is not None

    # Delete ollama
    deleted = store.delete_connection("ollama")
    assert deleted is True
    assert store.get("ollama") is None

    # Delete bedrock
    deleted_bed = store.delete_connection("bedrock")
    assert deleted_bed is True
    assert store.get("bedrock") is None

    # Re-instantiate ConnectionStore (simulating subsequent API calls / server restarts)
    new_store_instance = ConnectionStore(tmp_path)
    assert new_store_instance.get("ollama") is None
    assert new_store_instance.get("bedrock") is None
    remaining_ids = {c.id for c in new_store_instance.list()}
    assert "ollama" not in remaining_ids
    assert "bedrock" not in remaining_ids
    assert "opencode" in remaining_ids


def test_delete_inference_cleans_up_opencode_registered_models(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    
    # Register models on opencode for bedrock and zen-dev
    store.upsert_registered_model(
        "opencode",
        RegisteredOpencodeModel(
            inference_connection_id="bedrock",
            inference_model_id="mistral-3b",
            display_name="mistral-3b",
            provider_id="amazon-bedrock",
            model_id="mistral-3b",
            ref="amazon-bedrock/mistral-3b",
            tested_at="2026-08-26T10:00:00+00:00",
            inference_product="bedrock",
        ),
    )
    store.upsert_registered_model(
        "opencode",
        RegisteredOpencodeModel(
            inference_connection_id="zen-dev",
            inference_model_id="hy3-free",
            display_name="hy3-free",
            provider_id="opencode",
            model_id="hy3-free",
            ref="opencode/hy3-free",
            tested_at="2026-08-26T10:00:00+00:00",
            inference_product="openai-compatible",
        ),
    )

    oc = store.get_required("opencode")
    assert len(oc.registered_models) == 2

    # Delete bedrock connection
    store.delete_connection("bedrock")

    # OpenCode should now only have zen-dev model registered
    oc_after = store.get_required("opencode")
    refs = [m.ref for m in oc_after.registered_models]
    assert refs == ["opencode/hy3-free"]
    assert "amazon-bedrock/mistral-3b" not in refs


@pytest.mark.asyncio
async def test_api_delete_connection_endpoint(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    
    # Delete ollama via API handler
    res = await delete_connection_card(
        connection_id="ollama",
        store=store,
        _user_id="admin",
    )
    assert res == {"ok": True, "connection_id": "ollama"}
    assert store.get("ollama") is None

    # Delete non-existent raises 404
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await delete_connection_card(
            connection_id="non-existent",
            store=store,
            _user_id="admin",
        )
    assert exc.value.status_code == 404


def test_re_adding_connection_after_deletion(tmp_path: Path):
    store = ConnectionStore(tmp_path)
    store.delete_connection("ollama")
    assert store.get("ollama") is None

    # Add ollama back
    new_ollama = StackConnection(
        id="ollama",
        kind="inference",
        product="ollama",
        label="ollama",
        meta={"base_url": "http://127.0.0.1:11434/v1"},
        aliases=["ollama-local"],
    )
    store.upsert(new_ollama)

    fetched = store.get("ollama")
    assert fetched is not None
    assert fetched.id == "ollama"
    assert fetched.meta.get("base_url") == "http://127.0.0.1:11434/v1"


def test_create_connection_without_label_defaults_to_id(tmp_path: Path):
    from agent_anystack.api.connections import CreateConnectionBody

    body = CreateConnectionBody(
        id="zen-test",
        preset="zen",
        base_url="https://api.zen.ai/v1",
    )
    assert body.id == "zen-test"
    assert body.label is None

    conn = StackConnection(
        id=body.id,
        kind="inference",
        product=body.product,
        label=body.label or body.id,
    )
    store = ConnectionStore(tmp_path)
    store.upsert(conn)

    saved = store.get("zen-test")
    assert saved is not None
    assert saved.id == "zen-test"
    assert saved.label == "zen-test"
