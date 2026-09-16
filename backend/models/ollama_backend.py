"""Ollama backend: ``POST /api/chat``.

Ollama is the least fussy way to get a writing model running locally, so it is
kept as a first-class alternative to the in-process GGUF path.
"""

from __future__ import annotations

from typing import Any

from ._http import get_json, post_json
from .contract import ModelError, final_text


DEFAULT_HOST = "http://127.0.0.1:11434"


def normalize_ollama_url(host: str | None) -> str:
    """Accept a bare host or a full URL and return a usable base URL."""
    cleaned = str(host or "").strip().rstrip("/")
    if not cleaned:
        cleaned = DEFAULT_HOST
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"http://{cleaned}"
    return cleaned


async def probe(settings: dict[str, Any]) -> dict[str, Any]:
    """Check the server is reachable and list the models it has pulled."""
    host = normalize_ollama_url(settings.get("host"))
    payload = await get_json(f"{host}/api/tags", provider="Ollama")
    models = [
        str(entry.get("name") or "")
        for entry in payload.get("models") or []
        if isinstance(entry, dict) and entry.get("name")
    ]
    return {"ok": True, "host": host, "models": models, "model_count": len(models)}


async def generate(
    settings: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Run one chat completion and return the answer text."""
    host = normalize_ollama_url(settings.get("host"))
    model = str(settings.get("model") or "").strip()
    if not model:
        raise ModelError("MODEL_MISSING", "没有选择 Ollama 模型。")

    body: dict[str, Any] = {
        "model": model,
        "stream": False,
        # Both guides demand a JSON object, and Ollama enforces that for us.
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": float(settings.get("temperature", 0.6)),
            "num_predict": int(settings.get("max_tokens", 2048)),
            "num_ctx": int(settings.get("n_ctx", 8192)),
        },
    }
    # reasoning_budget 0 means "do not think" for models that honour think.
    if int(settings.get("reasoning_budget", 0)) == 0:
        body["think"] = False

    payload = await post_json(f"{host}/api/chat", body, provider="Ollama")

    message = payload.get("message")
    if not isinstance(message, dict):
        raise ModelError(
            "PROVIDER_BAD_RESPONSE",
            "Ollama 回复缺少 message 字段。",
            {"keys": sorted(payload.keys())},
        )
    # Newer Ollama separates reasoning into its own field; prefer content.
    content = message.get("content") or message.get("thinking") or ""
    text = final_text(str(content))
    if not text:
        raise ModelError(
            "EMPTY_REPLY",
            "Ollama 返回了空回复。可能是模型只输出了思考内容，或 max_tokens 太小。",
        )
    return text


__all__ = ["DEFAULT_HOST", "generate", "normalize_ollama_url", "probe"]
