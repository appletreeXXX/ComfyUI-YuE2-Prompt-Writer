"""ComfyUI aiohttp endpoints for the YuE2 Prompt Writer.

Importing this module registers every route with ComfyUI's ``PromptServer``.
The extension is a UI workspace with no nodes, so ``NODE_CLASS_MAPPINGS`` stays
empty and nothing here ever queues a graph.

Route prefix: ``/yue2_prompt_writer``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from aiohttp import web
from server import PromptServer

from . import assembly, catalog
from .guides import GuideError, guide_catalog, guide_content
from .lyrics import analyze_payload
from .models import local_backend
from .models import ollama_backend, openai_backend
from .models.contract import ModelError, public_settings, validate_settings
from .version import VERSION


ROUTE_PREFIX = "/yue2_prompt_writer"

STATE: dict[str, Any] = {"phase": "idle", "cancel_requested": False}
STATE_LOCK = threading.RLock()


def _dumps(value: Any) -> str:
    """Chinese must survive the round trip, so never escape non-ASCII."""
    return json.dumps(value, ensure_ascii=False)


def _json(payload: Any, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=_dumps)


def _error(code: str, message: str, *, status: int = 400, details: Any = None) -> web.Response:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return _json(body, status=status)


def _error_from(exception: ModelError, *, status: int = 400) -> web.Response:
    return _error(exception.code, exception.message, status=status, details=exception.details)


async def _read_json(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _settings_from(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a provider settings block from a request body."""
    raw = payload.get("provider") or payload.get("settings") or {}
    if not isinstance(raw, dict):
        raise ModelError("INVALID_SETTINGS", "provider 字段必须是对象。")
    return validate_settings(raw)


# --------------------------------------------------------------------------- #
# Health and catalogs
# --------------------------------------------------------------------------- #
@PromptServer.instance.routes.get(f"{ROUTE_PREFIX}/health")
async def yue2_health(_request: web.Request) -> web.Response:
    directory = local_backend.models_directory()
    return _json({
        "ok": True,
        "version": VERSION,
        "llama_cpp_available": local_backend.llama_cpp_available(),
        "llm_models_directory": str(directory) if directory else None,
        "free_vram_bytes": local_backend.free_vram_bytes(),
        "resident_model": local_backend.resident_model(),
        "resident": local_backend.resident_model(),
        "phase": STATE["phase"],
        "guides": [entry["id"] for entry in guide_catalog()],
    })


@PromptServer.instance.routes.get(f"{ROUTE_PREFIX}/catalog")
async def yue2_catalog(_request: web.Request) -> web.Response:
    return _json(catalog.catalog())


@PromptServer.instance.routes.get(f"{ROUTE_PREFIX}/guides")
async def yue2_guides(_request: web.Request) -> web.Response:
    return _json({"guides": guide_catalog()})


@PromptServer.instance.routes.get(f"{ROUTE_PREFIX}/guide/{{guide_id}}")
async def yue2_guide(request: web.Request) -> web.Response:
    guide_id = request.match_info["guide_id"]
    try:
        guide = guide_content(guide_id)
    except GuideError as error:
        return _error("GUIDE_NOT_FOUND", str(error), status=404)
    return _json({"id": guide_id, "content": guide})


# --------------------------------------------------------------------------- #
# Deterministic analysis
# --------------------------------------------------------------------------- #
@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/plan")
async def yue2_plan(request: web.Request) -> web.Response:
    """Deterministic analysis only: no model call, always succeeds."""
    payload = await _read_json(request)
    try:
        brief = assembly.normalize_brief(payload)
    except ModelError as error:
        return _error_from(error)
    analysis = assembly.analyze_for(brief)
    return _json({"analysis": analysis, "brief": _public_brief(brief)})


def _public_brief(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in brief.items()
        if key not in {"genre_preset", "vocal_setting"}
    }


@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/lyrics/analyze")
async def yue2_lyrics_analyze(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    text = str(payload.get("lyrics") or "")
    brief = payload.get("brief") if isinstance(payload.get("brief"), dict) else {}
    return _json({"analysis": analyze_payload(text, brief)})


# --------------------------------------------------------------------------- #
# Model management
# --------------------------------------------------------------------------- #
@PromptServer.instance.routes.get(f"{ROUTE_PREFIX}/models")
async def yue2_models(request: web.Request) -> web.Response:
    settings: dict[str, Any] = {}
    if request.query.get("n_ctx"):
        try:
            settings = validate_settings({
                "kind": "local",
                "model": request.query.get("model") or "placeholder",
                "n_ctx": request.query["n_ctx"],
                "kv_cache_type": request.query.get("kv_cache_type") or "q8_0",
                "n_gpu_layers": request.query.get("n_gpu_layers") or -1,
            })
        except ModelError:
            settings = {}
    return _json(local_backend.model_listing(settings))


@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/model/unload")
async def yue2_model_unload(_request: web.Request) -> web.Response:
    return _json(local_backend.unload_model())


@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/runtime/gguf/diagnostics")
async def yue2_gguf_diagnostics(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    return _json(local_backend.diagnostics(refresh=bool(payload.get("refresh"))))


# --------------------------------------------------------------------------- #
# Provider probing
# --------------------------------------------------------------------------- #
@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/provider/test")
async def yue2_provider_test(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    try:
        settings = _settings_from(payload)
    except ModelError as error:
        return _error_from(error)

    kind = settings["kind"]
    try:
        if kind == "ollama":
            result = await ollama_backend.probe(settings)
        elif kind == "openai":
            result = await openai_backend.probe(settings)
        else:
            listing = local_backend.model_listing(settings)
            result = {
                "ok": True,
                "host": None,
                "directory": listing["directory"],
                "model_count": listing["count"],
                "free_vram_gb": listing["free_vram_gb"],
                "llama_cpp_available": listing["llama_cpp_available"],
                "models": [
                    {
                        "id": entry["id"],
                        "size_gb": entry["size_gb"],
                        "fits": entry["fits"],
                        "estimate_gb": (entry.get("estimate") or {}).get("total_gb"),
                    }
                    for entry in listing["models"]
                ],
            }
    except ModelError as error:
        return _json({
            "ok": False,
            "error": error.as_dict(),
            "provider": public_settings(settings),
        }, status=200)

    return _json({"ok": True, "provider": public_settings(settings), **result})


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/preview")
async def yue2_preview(request: web.Request) -> web.Response:
    """Deterministic style prompt with no model call. Never fails."""
    payload = await _read_json(request)
    try:
        return _json(assembly.local_preview(payload))
    except ModelError as error:
        return _error_from(error)


@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/generate")
async def yue2_generate(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    try:
        settings = _settings_from(payload)
        brief = assembly.normalize_brief(payload)
    except ModelError as error:
        return _error_from(error)

    with STATE_LOCK:
        if STATE["phase"] == "running":
            return _error("GENERATION_BUSY", "已有一次生成在进行中。", status=409)
        STATE["phase"] = "running"
        STATE["cancel_requested"] = False

    try:
        # Run the blocking provider call off the event loop. The local GGUF path
        # is CPU/GPU-bound and would otherwise freeze the ComfyUI UI.
        result = await asyncio.to_thread(assembly.run_generate, brief_payload(payload), settings)
    except ModelError as error:
        return _error_from(error)
    finally:
        with STATE_LOCK:
            STATE["phase"] = "idle"
    return _json(result)


def brief_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The subset of a request body that describes the song, not the provider."""
    return {key: value for key, value in payload.items() if key not in {"provider", "settings"}}


@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/lyrics")
async def yue2_lyrics(request: web.Request) -> web.Response:
    payload = await _read_json(request)
    try:
        settings = _settings_from(payload)
        assembly.normalize_brief(payload)
    except ModelError as error:
        return _error_from(error)

    with STATE_LOCK:
        if STATE["phase"] == "running":
            return _error("GENERATION_BUSY", "已有一次生成在进行中。", status=409)
        STATE["phase"] = "running"
    try:
        result = await asyncio.to_thread(assembly.run_lyrics_generate, brief_payload(payload), settings)
    except ModelError as error:
        return _error_from(error)
    finally:
        with STATE_LOCK:
            STATE["phase"] = "idle"
    return _json(result)


@PromptServer.instance.routes.post(f"{ROUTE_PREFIX}/cancel")
async def yue2_cancel(_request: web.Request) -> web.Response:
    with STATE_LOCK:
        STATE["cancel_requested"] = True
    return _json({"cancelled": True})


__all__ = ["ROUTE_PREFIX", "STATE", "STATE_LOCK"]
