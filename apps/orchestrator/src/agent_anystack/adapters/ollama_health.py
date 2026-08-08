"""On-demand Ollama / GPU health — Stacks only; never polled by chat/channel."""

from __future__ import annotations

import asyncio
import re
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from agent_anystack.adapters.ollama_models import (
    CURATED_CATALOG,
    OllamaModelManager,
    OllamaModelsError,
    assert_curated,
    catalog_num_ctx,
)

# Rough VRAM need (MiB) for curated tags — advisory for UI tags.
_CURATED_VRAM_MIB: dict[str, int] = {
    "llama3.2:3b": 2200,
    "llama3.2": 2200,
    "qwen2.5:7b": 5000,
    "qwen2.5-coder:7b": 5000,
    "gemma4:e4b": 9600,
    "qwen3.5:4b": 3600,
}


@dataclass
class HealthStep:
    id: str
    status: str  # pass | fail | warn | skip
    detail: str
    fix: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "detail": self.detail,
        }
        if self.fix:
            out["fix"] = self.fix
        return out


@dataclass
class GpuHealthReport:
    verdict: str
    summary: str
    steps: list[HealthStep] = field(default_factory=list)
    gpus: list[dict[str, Any]] = field(default_factory=list)
    loaded: list[dict[str, Any]] = field(default_factory=list)
    catalog_hints: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "steps": [s.as_dict() for s in self.steps],
            "gpus": self.gpus,
            "loaded": self.loaded,
            "catalog_hints": self.catalog_hints,
        }


def _parse_nvidia_smi_csv(text: str) -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            total = int(re.sub(r"[^\d]", "", parts[1]) or "0")
            free = int(re.sub(r"[^\d]", "", parts[2]) or "0")
        except ValueError:
            total, free = 0, 0
        gpus.append(
            {
                "name": parts[0],
                "memory_total_mib": total,
                "memory_free_mib": free,
                "driver_version": parts[3],
            }
        )
    return gpus


async def _run_cmd(argv: list[str], *, timeout: float = 8.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, "", f"command not found: {argv[0]}"
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return 124, "", "timed out"
    return (
        int(proc.returncode or 0),
        (out_b or b"").decode("utf-8", errors="replace"),
        (err_b or b"").decode("utf-8", errors="replace"),
    )


async def _nvidia_smi_gpus() -> tuple[list[dict[str, Any]], str | None]:
    code, out, err = await _run_cmd(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if code == 0 and out.strip():
        return _parse_nvidia_smi_csv(out), None
    return [], (err or out or f"nvidia-smi exit {code}").strip()[:400]


async def _nvidia_smi_via_docker(container: str) -> tuple[list[dict[str, Any]], str | None]:
    if not shutil.which("docker"):
        return [], "docker CLI not available"
    code, out, err = await _run_cmd(
        [
            "docker",
            "exec",
            container,
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.free,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if code == 0 and out.strip():
        return _parse_nvidia_smi_csv(out), None
    return [], (err or out or f"docker exec exit {code}").strip()[:400]


async def _list_loaded(native_base: str) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{native_base}/api/ps")
    except (httpx.ConnectError, httpx.TimeoutException):
        return []
    if resp.status_code >= 400:
        return []
    data = resp.json()
    out: list[dict[str, Any]] = []
    for row in data.get("models") or []:
        name = str(row.get("name") or row.get("model") or "")
        if not name:
            continue
        size_vram = row.get("size_vram")
        size = row.get("size")
        processor = "unknown"
        if isinstance(size_vram, (int, float)) and isinstance(size, (int, float)) and size > 0:
            pct = 100.0 * float(size_vram) / float(size)
            if pct >= 95:
                processor = "100% GPU"
            elif pct <= 5:
                processor = "100% CPU"
            else:
                processor = f"{100 - pct:.0f}%/{pct:.0f}% CPU/GPU"
        # Ollama may also expose details
        details = row.get("details") or {}
        if isinstance(details, dict) and details.get("parent_model") is not None:
            pass
        out.append(
            {
                "name": name,
                "size": size,
                "size_vram": size_vram,
                "processor": processor,
                "expires_at": row.get("expires_at"),
            }
        )
    return out


def _catalog_hints(
    free_mib: int | None,
    gpu_visible: bool,
    loaded: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    loaded_by = {m["name"]: m for m in loaded}
    hints: list[dict[str, Any]] = []
    for entry in CURATED_CATALOG:
        eid = entry["id"]
        need = _CURATED_VRAM_MIB.get(eid)
        live = loaded_by.get(eid) or next(
            (m for n, m in loaded_by.items() if n == eid or n.startswith(eid + ":")),
            None,
        )
        if live:
            proc = live.get("processor") or "unknown"
            if "GPU" in proc and "CPU" not in proc.split("%")[0]:
                tag, reason = "running_gpu", f"Loaded: {proc}"
            elif "CPU" in proc and "GPU" not in proc:
                tag, reason = "running_cpu", f"Loaded: {proc}"
            elif "/" in proc:
                tag, reason = "running_split", f"Loaded: {proc}"
            else:
                tag, reason = "running_unknown", f"Loaded: {proc}"
        elif not gpu_visible:
            tag, reason = "cpu_only_host", "No GPU visible — inference will use CPU"
        elif free_mib is None:
            tag, reason = "unknown", "GPU present but free VRAM unknown"
        elif need is not None and free_mib >= need:
            tag, reason = "likely_gpu", f"Needs ~{need} MiB; ~{free_mib} MiB free"
        elif need is not None:
            tag, reason = "likely_cpu", f"Needs ~{need} MiB; only ~{free_mib} MiB free — may CPU-offload"
        else:
            tag, reason = "unknown", "No size hint"
        hints.append({"id": eid, "run_tag": tag, "reason": reason})
    return hints


async def diagnose_gpu_health(
    *,
    openai_compatible_base_url: str,
    ollama_container_name: str = "agentanystack-ollama-1",
) -> GpuHealthReport:
    """One-shot ladder: Ollama up → GPU visible → VRAM → loaded processor."""
    mgr = OllamaModelManager(openai_compatible_base_url)
    native = mgr.native_base
    steps: list[HealthStep] = []

    # 1. Ollama reachable
    reachable = await mgr.ping()
    if reachable:
        steps.append(
            HealthStep(
                id="ollama_reachable",
                status="pass",
                detail=f"Ollama reachable at {native}",
            )
        )
    else:
        steps.append(
            HealthStep(
                id="ollama_reachable",
                status="fail",
                detail=f"Cannot reach Ollama at {native}",
                fix="Start: docker compose --profile ollama up -d",
            )
        )
        return GpuHealthReport(
            verdict="ollama_down",
            summary="Ollama is not reachable — start the ollama profile first.",
            steps=steps,
        )

    # 2. GPU via nvidia-smi (orchestrator) or docker exec into ollama
    gpus, err_local = await _nvidia_smi_gpus()
    probe_via = "orchestrator"
    if not gpus:
        gpus, err_docker = await _nvidia_smi_via_docker(ollama_container_name)
        probe_via = "docker_exec"
        if not gpus:
            steps.append(
                HealthStep(
                    id="gpu_visible",
                    status="fail",
                    detail=(
                        "No NVIDIA GPU visible "
                        f"(local: {err_local or 'n/a'}; "
                        f"docker exec {ollama_container_name}: {err_docker or 'n/a'})"
                    ),
                    fix=(
                        "Use NVIDIA GPU compose: docker compose --profile ollama "
                        "-f docker-compose.yml -f docker-compose.gpu.yml up -d "
                        "(needs driver + Docker GPU / WSL2). "
                        "Or run Stacks health from a host with nvidia-smi / docker CLI."
                    ),
                )
            )
            loaded = await _list_loaded(native)
            hints = _catalog_hints(None, False, loaded)
            return GpuHealthReport(
                verdict="cpu_only",
                summary="Ollama is up but no GPU was detected — models will run on CPU (slow).",
                steps=steps,
                loaded=loaded,
                catalog_hints=hints,
            )

    free = max((g.get("memory_free_mib") or 0) for g in gpus) if gpus else 0
    total = max((g.get("memory_total_mib") or 0) for g in gpus) if gpus else 0
    names = ", ".join(g.get("name") or "?" for g in gpus)
    steps.append(
        HealthStep(
            id="gpu_visible",
            status="pass",
            detail=f"GPU visible via {probe_via}: {names} ({free}/{total} MiB free/total)",
        )
    )

    # 3. VRAM headroom
    if free < 1500:
        steps.append(
            HealthStep(
                id="vram_free",
                status="warn",
                detail=f"Low free VRAM (~{free} MiB) — even small models may CPU-offload",
                fix="Close other GPU apps; use llama3.2:3b; wait for Ollama idle unload (~5m)",
            )
        )
    else:
        steps.append(
            HealthStep(
                id="vram_free",
                status="pass",
                detail=f"Free VRAM ~{free} MiB (enough for curated 3B-class tags)",
            )
        )

    # 4. Loaded runners
    loaded = await _list_loaded(native)
    if not loaded:
        steps.append(
            HealthStep(
                id="model_loaded",
                status="skip",
                detail="No model currently loaded (normal after idle ~5m or before first chat)",
                fix=(
                    "Chat once, then Refresh health. If chat is slow while VRAM stays free, "
                    "check ollama logs for 'GPU discovery' timeout and recreate with "
                    "docker-compose.gpu.yml"
                ),
            )
        )
    else:
        cpu_heavy = [
            m for m in loaded if (m.get("processor") or "") == "100% CPU"
        ]
        gpu_ok = [m for m in loaded if (m.get("processor") or "") == "100% GPU"]
        split = [m for m in loaded if "/" in (m.get("processor") or "")]
        detail_parts = [f"{m['name']} → {m.get('processor')}" for m in loaded]
        if gpu_ok and not cpu_heavy and not split:
            steps.append(
                HealthStep(
                    id="model_loaded",
                    status="pass",
                    detail="; ".join(detail_parts),
                )
            )
        elif cpu_heavy and free > 1500:
            steps.append(
                HealthStep(
                    id="model_loaded",
                    status="fail",
                    detail=(
                        "; ".join(detail_parts)
                        + " — on CPU while VRAM is free (Ollama likely failed CUDA discovery)"
                    ),
                    fix=(
                        "Recreate Ollama with GPU: docker compose --profile ollama "
                        "-f docker-compose.yml -f docker-compose.gpu.yml up -d --force-recreate ollama. "
                        "Then: docker logs <ollama> 2>&1 | findstr /i \"GPU discovery\". "
                        "Warm with: docker exec <ollama> ollama run llama3.2:3b hi"
                    ),
                )
            )
        else:
            steps.append(
                HealthStep(
                    id="model_loaded",
                    status="warn",
                    detail="; ".join(detail_parts),
                    fix="Prefer smaller models if split/CPU; free VRAM or reduce context",
                )
            )

    hints = _catalog_hints(free, True, loaded)
    fails = [s for s in steps if s.status == "fail"]
    warns = [s for s in steps if s.status == "warn"]
    if any(s.id == "model_loaded" and s.status == "fail" for s in steps):
        verdict = "gpu_visible_cpu_inference"
        summary = (
            "GPU is visible and has free memory, but the loaded model is on CPU. "
            "Usually Ollama CUDA discovery failed — recreate with docker-compose.gpu.yml and check logs."
        )
    elif fails:
        verdict = "degraded"
        summary = fails[0].detail
    elif any(m.get("processor") == "100% GPU" for m in loaded):
        verdict = "gpu_ready"
        summary = "GPU visible and at least one model is running 100% on GPU."
    elif loaded:
        verdict = "gpu_visible_partial"
        summary = "GPU visible; loaded model is split or not fully on GPU."
    elif warns:
        verdict = "gpu_visible_idle"
        summary = (
            "GPU visible and Ollama is up. No model loaded yet — chat to load, "
            "then refresh to confirm 100% GPU."
        )
    else:
        verdict = "gpu_visible_idle"
        summary = "GPU visible and Ollama is up. Ready to pull/chat; confirm processor after first load."

    return GpuHealthReport(
        verdict=verdict,
        summary=summary,
        steps=steps,
        gpus=gpus,
        loaded=loaded,
        catalog_hints=hints,
    )


def _match_loaded(tag: str, loaded: list[dict[str, Any]]) -> dict[str, Any] | None:
    for m in loaded:
        n = str(m.get("name") or "")
        if n == tag or n == f"{tag}:latest":
            return m
    for m in loaded:
        n = str(m.get("name") or "")
        if n.startswith(tag + ":"):
            return m
    if ":" not in tag:
        for m in loaded:
            n = str(m.get("name") or "")
            if n.split(":")[0] == tag:
                return m
    return None


def _run_tag_from_processor(processor: str) -> tuple[str, str]:
    proc = processor or "unknown"
    if proc == "100% GPU":
        return "running_gpu", f"Verified: {proc}"
    if proc == "100% CPU":
        return "running_cpu", f"Verified: {proc}"
    if "/" in proc:
        return "running_split", f"Verified: {proc}"
    return "running_unknown", f"Verified: {proc}"


async def verify_model_gpu(
    *,
    openai_compatible_base_url: str,
    name: str,
) -> AsyncIterator[dict[str, Any]]:
    """Warm-load a curated model, then report processor from /api/ps (Stacks only)."""
    tag = assert_curated(name)
    mgr = OllamaModelManager(openai_compatible_base_url, timeout=900.0)
    native = mgr.native_base
    yield {"type": "meta", "name": tag, "phase": "start"}

    installed = {m.name for m in await mgr.list_installed()}
    pulled = (
        tag in installed
        or f"{tag}:latest" in installed
        or any(
            n.startswith(tag + ":")
            or (":" not in tag and n.split(":")[0] == tag)
            for n in installed
        )
    )
    if not pulled:
        raise OllamaModelsError(
            f"model '{tag}' is not pulled — Pull it on Stacks first",
            code="not_pulled",
        )

    yield {
        "type": "progress",
        "name": tag,
        "phase": "loading",
        "message": "Loading model into memory (first time can take several minutes)…",
    }

    try:
        async with httpx.AsyncClient(timeout=900.0) as client:
            resp = await client.post(
                f"{native}/api/generate",
                json={
                    "model": tag,
                    "prompt": "hi",
                    "stream": False,
                    "keep_alive": "5m",
                    "options": {
                        "num_predict": 1,
                        "num_ctx": catalog_num_ctx(tag) or 2048,
                    },
                },
            )
    except httpx.ConnectError as exc:
        raise OllamaModelsError(
            f"Cannot reach Ollama at {native}",
            code="unreachable",
        ) from exc
    except httpx.TimeoutException as exc:
        raise OllamaModelsError(
            f"Verify timed out loading '{tag}' (often CPU path or CUDA discovery failure)",
            code="timeout",
        ) from exc

    if resp.status_code >= 400:
        raise OllamaModelsError(
            f"Ollama generate failed ({resp.status_code}): {resp.text[:400]}",
            code="verify_http",
        )

    yield {
        "type": "progress",
        "name": tag,
        "phase": "checking",
        "message": "Model responded — reading GPU/CPU processor…",
    }

    loaded = await _list_loaded(native)
    match = _match_loaded(tag, loaded)
    if not match:
        yield {
            "type": "result",
            "name": tag,
            "run_tag": "running_unknown",
            "processor": "unknown",
            "reason": "Model generated but /api/ps did not list it (unloaded very fast?)",
            "fix": "Retry Verify; or docker exec … ollama ps while chatting",
            "loaded": loaded,
        }
        yield {"type": "done", "name": tag}
        return

    processor = str(match.get("processor") or "unknown")
    run_tag, reason = _run_tag_from_processor(processor)
    fix = None
    if run_tag == "running_cpu":
        fix = (
            "GPU free but model on CPU — recreate Ollama with docker-compose.gpu.yml "
            "and check logs for 'GPU discovery' timeout"
        )
    elif run_tag == "running_split":
        fix = "Partial GPU offload — use a smaller tag or free more VRAM"

    yield {
        "type": "result",
        "name": tag,
        "run_tag": run_tag,
        "processor": processor,
        "size": match.get("size"),
        "size_vram": match.get("size_vram"),
        "reason": reason,
        "fix": fix,
        "loaded": loaded,
    }
    yield {"type": "done", "name": tag}


# re-export for tests / callers
__all__ = [
    "GpuHealthReport",
    "diagnose_gpu_health",
    "verify_model_gpu",
]
