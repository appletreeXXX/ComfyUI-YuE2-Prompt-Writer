"""Shared aiohttp request helper and error mapping for remote providers.

Uses only ``aiohttp`` (bundled with ComfyUI) and the standard library, which is
what lets ``requirements.txt`` stay empty.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp

from .contract import ModelError


# A lyric-writing call on a slow local server can legitimately take minutes, so
# the connect phase is bounded aggressively but the read phase generously.
CONNECT_TIMEOUT_SECONDS = 10.0
READ_TIMEOUT_SECONDS = 600.0


def _timeout() -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(
        total=None,
        connect=CONNECT_TIMEOUT_SECONDS,
        sock_read=READ_TIMEOUT_SECONDS,
    )


async def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    provider: str = "provider",
) -> dict[str, Any]:
    """POST JSON and return the decoded body, mapping failures to ModelError."""
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    try:
        async with aiohttp.ClientSession(timeout=_timeout()) as session:
            async with session.post(url, json=payload, headers=request_headers) as response:
                body = await response.text()
                if response.status >= 400:
                    raise ModelError(
                        "PROVIDER_HTTP_ERROR",
                        f"{provider} 返回 HTTP {response.status}。",
                        {"status": response.status, "body": body[:800], "url": url},
                    )
    except ModelError:
        raise
    except aiohttp.ClientConnectorError as error:
        raise ModelError(
            "PROVIDER_UNREACHABLE",
            f"无法连接到 {provider}（{url}）。请确认服务已启动、地址正确。",
            {"url": url, "reason": str(error)},
        ) from error
    except asyncio.TimeoutError as error:
        raise ModelError(
            "PROVIDER_TIMEOUT",
            f"{provider} 在规定时间内没有响应。",
            {"url": url},
        ) from error
    except aiohttp.ClientError as error:
        raise ModelError(
            "PROVIDER_TRANSPORT_ERROR",
            f"与 {provider} 通信失败：{error}",
            {"url": url},
        ) from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise ModelError(
            "PROVIDER_BAD_RESPONSE",
            f"{provider} 返回的不是合法 JSON。",
            {"url": url, "body": body[:800]},
        ) from error
    if not isinstance(decoded, dict):
        raise ModelError(
            "PROVIDER_BAD_RESPONSE",
            f"{provider} 返回了非预期的 JSON 类型。",
            {"url": url},
        )
    return decoded


async def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    provider: str = "provider",
) -> dict[str, Any]:
    """GET JSON and return the decoded body, mapping failures to ModelError."""
    try:
        async with aiohttp.ClientSession(timeout=_timeout()) as session:
            async with session.get(url, headers=headers or {}) as response:
                body = await response.text()
                if response.status >= 400:
                    raise ModelError(
                        "PROVIDER_HTTP_ERROR",
                        f"{provider} 返回 HTTP {response.status}。",
                        {"status": response.status, "body": body[:800], "url": url},
                    )
    except ModelError:
        raise
    except aiohttp.ClientConnectorError as error:
        raise ModelError(
            "PROVIDER_UNREACHABLE",
            f"无法连接到 {provider}（{url}）。",
            {"url": url, "reason": str(error)},
        ) from error
    except asyncio.TimeoutError as error:
        raise ModelError(
            "PROVIDER_TIMEOUT",
            f"{provider} 在规定时间内没有响应。",
            {"url": url},
        ) from error
    except aiohttp.ClientError as error:
        raise ModelError(
            "PROVIDER_TRANSPORT_ERROR",
            f"与 {provider} 通信失败：{error}",
            {"url": url},
        ) from error

    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as error:
        raise ModelError(
            "PROVIDER_BAD_RESPONSE",
            f"{provider} 返回的不是合法 JSON。",
            {"url": url, "body": body[:800]},
        ) from error
    if not isinstance(decoded, dict):
        raise ModelError(
            "PROVIDER_BAD_RESPONSE",
            f"{provider} 返回了非预期的 JSON 类型。",
            {"url": url},
        )
    return decoded


__all__ = ["get_json", "post_json"]
