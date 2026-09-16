"""Provider contract: settings validation, error type, and reply extraction.

All three backends (local GGUF, Ollama, OpenAI-compatible) share this shape so
``assembly`` can treat them identically. Keeping validation here means an invalid
settings payload is rejected before any model work starts.
"""

from __future__ import annotations

from typing import Any


PROVIDER_KINDS = ("local", "ollama", "openai")

# Fields each provider needs. ``local`` deliberately needs no host: the model is
# loaded in this process.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "local": ("model",),
    "ollama": ("model",),
    "openai": ("model", "host"),
}

DEFAULTS: dict[str, Any] = {
    "kind": "local",
    # local GGUF
    "model": "",
    "n_ctx": 8192,
    "n_gpu_layers": -1,
    "n_batch": 512,
    "kv_cache_type": "q8_0",
    "flash_attention": False,
    "offload_kqv": True,
    "reasoning_budget": 0,
    "keep_loaded": False,
    "free_comfy_vram": True,
    "max_tokens": 2048,
    "temperature": 0.6,
    # remote
    "host": "",
    "api_key": "",
    "remember_key": False,
}

# Bounds exist so a typo in the UI cannot hand llama.cpp a nonsensical value.
_BOUNDS: dict[str, tuple[int, int]] = {
    "n_ctx": (512, 131072),
    "n_gpu_layers": (-1, 999),
    "n_batch": (32, 4096),
    "reasoning_budget": (0, 32768),
    "max_tokens": (64, 32768),
    "temperature": (0.0, 2.0),
}

KV_CACHE_TYPES = ("f16", "q8_0", "q4_0")


class ModelError(Exception):
    """A provider failure carrying a machine-readable code for the UI."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class SettingsError(ModelError):
    def __init__(self, message: str, details: Any = None):
        super().__init__("INVALID_SETTINGS", message, details)


def validate_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return a complete, validated settings dict.

    Unknown keys are dropped rather than forwarded, so a stale UI cannot smuggle
    an unexpected argument into a backend call.
    """
    raw = dict(payload or {})
    kind = str(raw.get("kind") or DEFAULTS["kind"]).strip().lower()
    if kind not in PROVIDER_KINDS:
        raise SettingsError(
            f"Unknown provider kind: {kind!r}.",
            {"allowed": list(PROVIDER_KINDS)},
        )

    settings = {**DEFAULTS, "kind": kind}
    for key in DEFAULTS:
        if key in raw and raw[key] is not None:
            settings[key] = raw[key]

    missing = [key for key in _REQUIRED[kind] if not str(settings.get(key) or "").strip()]
    if missing:
        raise SettingsError(
            f"Provider {kind!r} requires: {', '.join(missing)}.",
            {"missing": missing},
        )

    for key, (low, high) in _BOUNDS.items():
        value = settings.get(key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{key} must be a number, got {value!r}.") from None
        if numeric < low or numeric > high:
            raise SettingsError(f"{key} must be between {low} and {high}, got {numeric}.")
        settings[key] = int(numeric) if key != "temperature" else numeric

    if settings["kv_cache_type"] not in KV_CACHE_TYPES:
        raise SettingsError(
            f"kv_cache_type must be one of {', '.join(KV_CACHE_TYPES)}.",
            {"allowed": list(KV_CACHE_TYPES)},
        )

    for flag in ("flash_attention", "offload_kqv", "keep_loaded", "free_comfy_vram", "remember_key"):
        settings[flag] = bool(settings.get(flag))

    settings["model"] = str(settings["model"]).strip()
    settings["host"] = str(settings.get("host") or "").strip()
    settings["api_key"] = str(settings.get("api_key") or "")

    if kind == "ollama" and not settings["host"]:
        settings["host"] = "http://127.0.0.1:11434"
    if kind == "openai" and settings["host"]:
        settings["host"] = _normalize_openai_host(settings["host"])
    return settings


def _normalize_openai_host(host: str) -> str:
    """Accept ``host`` or ``host/v1`` and always end up with a ``/v1`` base."""
    cleaned = host.strip().rstrip("/")
    if not cleaned:
        return cleaned
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"http://{cleaned}"
    if not cleaned.endswith("/v1"):
        cleaned = f"{cleaned}/v1"
    return cleaned


def public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Strip secrets before settings ever leave the process.

    The key is used for requests and never returned, which is why the privacy
    note in the README can promise the backend does not hand it back.
    """
    redacted = dict(settings)
    if redacted.get("api_key"):
        redacted["api_key"] = ""
        redacted["has_api_key"] = True
    else:
        redacted["has_api_key"] = False
    return redacted


# --------------------------------------------------------------------------- #
# Reply extraction
# --------------------------------------------------------------------------- #
# Thinking models occasionally emit a reasoning channel before the answer. These
# markers are the ones llama.cpp and Ollama templates actually use.
_REASONING_FIELDS = ("thinking", "reasoning", "reasoning_content", "analysis", "scratchpad")
_CHANNEL_MARKER = "<channel|>"


def final_text(response: str) -> str:
    """Drop the reasoning channel and trailing turn markers from a reply."""
    text = str(response or "")
    if "<|channel>thought" in text and _CHANNEL_MARKER not in text:
        raise ModelError(
            "THINKING_TRUNCATED",
            "模型把全部输出预算用在了思考上，没有给出答案。请重试、提高 max_tokens，或把 reasoning_budget 设为 0。",
        )
    if _CHANNEL_MARKER in text:
        text = text.rsplit(_CHANNEL_MARKER, 1)[-1]
    for marker in ("<|end_of_turn|>", "<eos>", "<|im_end|>"):
        text = text.replace(marker, "")
    return text.strip()


def strip_json_fence(text: str) -> str:
    """Remove a markdown code fence around a JSON payload."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.split("\n")
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def drop_reasoning_fields(payload: Any) -> Any:
    """Recursively remove reasoning keys from a decoded reply.

    Version 0.2.0 added this as the second of three defences against thinking
    models burning the output budget on a ``thinking`` key.
    """
    if isinstance(payload, dict):
        return {
            key: drop_reasoning_fields(value)
            for key, value in payload.items()
            if key.lower() not in _REASONING_FIELDS
        }
    if isinstance(payload, list):
        return [drop_reasoning_fields(item) for item in payload]
    return payload


def reasoning_only(payload: Any) -> bool:
    """True when a reply carried nothing but reasoning fields."""
    if not isinstance(payload, dict) or not payload:
        return False
    return all(key.lower() in _REASONING_FIELDS for key in payload)


__all__ = [
    "DEFAULTS",
    "KV_CACHE_TYPES",
    "ModelError",
    "PROVIDER_KINDS",
    "SettingsError",
    "drop_reasoning_fields",
    "final_text",
    "public_settings",
    "reasoning_only",
    "strip_json_fence",
    "validate_settings",
]
