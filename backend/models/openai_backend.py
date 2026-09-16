"""OpenAI-compatible backend: ``POST {base}/chat/completions``.

Works with OpenAI, OpenRouter, LM Studio, vLLM, llama.cpp server and anything
else implementing the same route. A documented quirk is handled here: some
servers reject ``response_format``, so the request is retried once without it
rather than failing the whole generation.
"""

from __future__ import annotations

from typing import Any

from ._http import get_json, post_json
from .contract import ModelError, final_text


def _headers(settings: dict[str, Any]) -> dict[str, str]:
    key = str(settings.get("api_key") or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _chat_body(
    settings: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    *,
    json_mode: bool,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": str(settings.get("model") or "").strip(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": float(settings.get("temperature", 0.6)),
        "max_tokens": int(settings.get("max_tokens", 2048)),
        "stream": False,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def _extract(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelError(
            "PROVIDER_BAD_RESPONSE",
            "端点回复缺少 choices 数组。",
            {"keys": sorted(payload.keys())},
        )
    first = choices[0]
    if not isinstance(first, dict):
        raise ModelError("PROVIDER_BAD_RESPONSE", "choices[0] 不是对象。")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ModelError("PROVIDER_BAD_RESPONSE", "choices[0].message 缺失。")
    # reasoning_content is a separate field on some providers; take content first.
    content = message.get("content") or message.get("reasoning_content") or ""
    text = final_text(str(content))
    if not text:
        raise ModelError(
            "EMPTY_REPLY",
            "端点返回了空回复。可能是模型只输出了思考内容，或 max_tokens 太小。",
        )
    return text


async def probe(settings: dict[str, Any]) -> dict[str, Any]:
    """Verify credentials by listing models, degrading to a friendly error."""
    host = str(settings.get("host") or "").strip().rstrip("/")
    if not host:
        raise ModelError("INVALID_SETTINGS", "没有填写 OpenAI 兼容端点的服务地址。")
    try:
        payload = await get_json(f"{host}/models", headers=_headers(settings), provider="OpenAI 兼容端点")
    except ModelError as error:
        if error.code == "PROVIDER_HTTP_ERROR":
            # Some gateways do not expose /models; reachability is still proven.
            return {
                "ok": True,
                "host": host,
                "models": [],
                "model_count": 0,
                "note": "该端点未提供 /models 列表，但连接成功。",
            }
        raise
    entries = payload.get("data")
    models = [
        str(entry.get("id") or "")
        for entry in entries or []
        if isinstance(entry, dict) and entry.get("id")
    ]
    return {"ok": True, "host": host, "models": models, "model_count": len(models)}


async def generate(
    settings: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
) -> str:
    host = str(settings.get("host") or "").strip().rstrip("/")
    if not host:
        raise ModelError("INVALID_SETTINGS", "没有填写 OpenAI 兼容端点的服务地址。")
    if not str(settings.get("model") or "").strip():
        raise ModelError("MODEL_MISSING", "没有填写模型名称。")

    url = f"{host}/chat/completions"
    headers = _headers(settings)
    try:
        payload = await post_json(
            url,
            _chat_body(settings, system_prompt, user_prompt, json_mode=True),
            headers=headers,
            provider="OpenAI 兼容端点",
        )
    except ModelError as error:
        details = error.details if isinstance(error.details, dict) else {}
        body = str(details.get("body") or "").lower()
        # Documented fallback: retry once without response_format.
        if error.code == "PROVIDER_HTTP_ERROR" and ("response_format" in body or "json_object" in body):
            payload = await post_json(
                url,
                _chat_body(settings, system_prompt, user_prompt, json_mode=False),
                headers=headers,
                provider="OpenAI 兼容端点",
            )
        else:
            raise
    return _extract(payload)


__all__ = ["generate", "probe"]
