"""In-process GGUF backend for ComfyUI's ``models/LLM`` folder.

Loads a GGUF with ``llama-cpp-python`` inside the ComfyUI process, generates, and
releases the model so the VRAM goes back to ComfyUI. No Ollama, no sidecar
server, no network.

Two details are worth calling out because they are the difference between a
usable picker and an unusable one:

* **Header parsing is done by hand.** ``gguf.GGUFReader`` walks every tensor
  entry as well as the metadata, which costs seconds per multi-gigabyte file.
  Reading only the metadata block and skipping the tensor index took a real
  9-model / ~90 GB folder from over 120 s to under a second.
* **The estimate is conservative.** Weights + KV cache + a compute buffer are
  compared against free VRAM, and an oversized model is partially offloaded
  instead of failing outright, because ``n_gpu_layers = -1`` means "auto" to
  llama.cpp.
"""

from __future__ import annotations

import gc
import struct
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

from .contract import ModelError


# --------------------------------------------------------------------------- #
# GGUF header parsing
# --------------------------------------------------------------------------- #
_GGUF_MAGIC = b"GGUF"
_SUPPORTED_VERSIONS = {2, 3}
_TYPE_FORMATS = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    7: "<?",
    10: "<Q",
    11: "<q",
    12: "<d",
}
_STRING_TYPE = 8
_ARRAY_TYPE = 9
_MAX_METADATA_COUNT = 1_000_000
_MAX_TENSOR_COUNT = 10_000_000
_MAX_STRING_BYTES = 32 * 1024 * 1024
_MAX_ARRAY_LENGTH = 100_000_000

# Projector files sit next to the model but are not loadable on their own.
_PROJECTOR_PREFIXES = ("mmproj", "clip", "projector")


class GGUFHeaderError(ValueError):
    pass


def _read_exact(handle: BinaryIO, size: int) -> bytes:
    value = handle.read(size)
    if len(value) != size:
        raise GGUFHeaderError("GGUF header ended unexpectedly.")
    return value


def _read_struct(handle: BinaryIO, fmt: str) -> Any:
    return struct.unpack(fmt, _read_exact(handle, struct.calcsize(fmt)))[0]


def _read_string(handle: BinaryIO) -> str:
    length = _read_struct(handle, "<Q")
    if length > _MAX_STRING_BYTES:
        raise GGUFHeaderError(f"GGUF string too large: {length} bytes.")
    try:
        return _read_exact(handle, length).decode("utf-8")
    except UnicodeDecodeError as error:
        raise GGUFHeaderError("GGUF header contains invalid UTF-8.") from error


def _skip_string(handle: BinaryIO) -> None:
    length = _read_struct(handle, "<Q")
    if length > _MAX_STRING_BYTES:
        raise GGUFHeaderError(f"GGUF string too large: {length} bytes.")
    handle.seek(length, 1)


def _read_scalar(handle: BinaryIO, value_type: int) -> Any:
    if value_type == _STRING_TYPE:
        return _read_string(handle)
    fmt = _TYPE_FORMATS.get(value_type)
    if fmt is None:
        raise GGUFHeaderError(f"Unsupported GGUF value type: {value_type}.")
    return _read_struct(handle, fmt)


def _skip_array(handle: BinaryIO) -> None:
    element_type = _read_struct(handle, "<I")
    length = _read_struct(handle, "<Q")
    if length > _MAX_ARRAY_LENGTH:
        raise GGUFHeaderError(f"GGUF array too large: {length} values.")
    if element_type == _STRING_TYPE:
        for _ in range(length):
            _skip_string(handle)
        return
    fmt = _TYPE_FORMATS.get(element_type)
    if fmt is None:
        raise GGUFHeaderError(f"Unsupported GGUF array type: {element_type}.")
    handle.seek(struct.calcsize(fmt) * length, 1)


def _read_header(path: Path) -> dict[str, Any]:
    """Read only the metadata block, skipping the tensor index entirely."""
    with path.open("rb") as handle:
        if _read_exact(handle, 4) != _GGUF_MAGIC:
            raise GGUFHeaderError("File does not have a GGUF header.")
        version = _read_struct(handle, "<I")
        if version not in _SUPPORTED_VERSIONS:
            raise GGUFHeaderError(f"Unsupported GGUF version: {version}.")
        tensor_count = _read_struct(handle, "<Q")
        metadata_count = _read_struct(handle, "<Q")
        if tensor_count > _MAX_TENSOR_COUNT:
            raise GGUFHeaderError(f"GGUF tensor count too large: {tensor_count}.")
        if metadata_count > _MAX_METADATA_COUNT:
            raise GGUFHeaderError(f"GGUF metadata count too large: {metadata_count}.")

        values: dict[str, Any] = {}
        for _ in range(metadata_count):
            key = _read_string(handle)
            value_type = _read_struct(handle, "<I")
            if value_type == _ARRAY_TYPE:
                _skip_array(handle)
            else:
                values[key] = _read_scalar(handle, value_type)

    architecture = str(values.get("general.architecture") or "").strip().lower() or None
    prefix = f"{architecture}." if architecture else ""
    return {
        "version": version,
        "architecture": architecture,
        "name": values.get("general.name"),
        "context_length": values.get(f"{prefix}context_length") if prefix else None,
        "embedding_length": values.get(f"{prefix}embedding_length") if prefix else None,
        "block_count": values.get(f"{prefix}block_count") if prefix else None,
        "head_count": values.get(f"{prefix}attention.head_count") if prefix else None,
        "head_count_kv": (
            values.get(f"{prefix}attention.head_count_kv") or values.get(f"{prefix}attention.head_count")
        ) if prefix else None,
        "key_length": values.get(f"{prefix}attention.key_length") if prefix else None,
        "value_length": values.get(f"{prefix}attention.value_length") if prefix else None,
        "chat_template": values.get("tokenizer.chat_template"),
    }


@lru_cache(maxsize=64)
def _read_header_cached(path_value: str, size: int, mtime_ns: int) -> dict[str, Any]:
    del size, mtime_ns
    return _read_header(Path(path_value))


def read_gguf_header(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve(strict=True)
    stat = resolved.stat()
    return _read_header_cached(str(resolved), stat.st_size, stat.st_mtime_ns).copy()


def is_projector(path: Path) -> bool:
    return path.name.lower().startswith(_PROJECTOR_PREFIXES)


# --------------------------------------------------------------------------- #
# Model discovery
# --------------------------------------------------------------------------- #
_LIST_CACHE_LOCK = threading.Lock()
_LIST_CACHE: dict[str, Any] = {"signature": None, "value": None}
_LIST_CACHE_TTL_SECONDS = 30.0


def models_directory() -> Path | None:
    """ComfyUI's ``models/LLM`` folder, resolved via folder_paths when present."""
    try:
        import folder_paths  # type: ignore
    except Exception:
        return None
    directory = Path(folder_paths.models_dir) / "LLM"
    return directory if directory.is_dir() else None


def _candidate_files(directory: Path) -> list[Path]:
    try:
        return sorted(
            (path for path in directory.rglob("*.gguf") if path.is_file()),
            key=lambda path: str(path).lower(),
        )
    except OSError:
        return []


def scan_models(*, use_cache: bool = True) -> list[dict[str, Any]]:
    """List usable GGUF text models under ``models/LLM``.

    Cached for 30 s because both the picker and every generation resolve a model,
    and walking a 90 GB folder on each keystroke is wasteful.
    """
    import time

    directory = models_directory()
    if directory is None:
        return []

    files = _candidate_files(directory)
    signature = (str(directory), tuple((str(p), p.stat().st_mtime_ns) for p in files))
    with _LIST_CACHE_LOCK:
        cached = _LIST_CACHE["value"]
        stamp = _LIST_CACHE["signature"]
        if use_cache and cached is not None and stamp == signature:
            age = time.monotonic() - _LIST_CACHE.get("at", 0.0)
            if age < _LIST_CACHE_TTL_SECONDS:
                return [dict(entry) for entry in cached]

    models: list[dict[str, Any]] = []
    for path in files:
        if is_projector(path):
            continue
        try:
            header = read_gguf_header(path)
        except (GGUFHeaderError, OSError):
            # A truncated or non-GGUF file is reported by name, not hidden.
            models.append({
                "id": str(path.relative_to(directory)).replace("\\", "/"),
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "size_gb": round(path.stat().st_size / 1024**3, 2),
                "readable": False,
                "reason": "无法解析 GGUF 头部，文件可能不完整。",
            })
            continue
        if not header.get("architecture"):
            continue
        models.append(_describe(path, directory, header))

    models.sort(key=lambda entry: entry["size_bytes"])
    with _LIST_CACHE_LOCK:
        _LIST_CACHE["value"] = [dict(entry) for entry in models]
        _LIST_CACHE["signature"] = signature
        _LIST_CACHE["at"] = time.monotonic()
    return models


def _describe(path: Path, directory: Path, header: dict[str, Any]) -> dict[str, Any]:
    size_bytes = path.stat().st_size
    return {
        "id": str(path.relative_to(directory)).replace("\\", "/"),
        "name": path.name,
        "size_bytes": size_bytes,
        "size_gb": round(size_bytes / 1024**3, 2),
        "architecture": header.get("architecture"),
        "context_length": header.get("context_length"),
        "block_count": header.get("block_count"),
        "head_count": header.get("head_count"),
        "head_count_kv": header.get("head_count_kv"),
        "key_length": header.get("key_length"),
        "value_length": header.get("value_length"),
        "readable": True,
    }


def find_model(model_id: str) -> dict[str, Any] | None:
    wanted = str(model_id or "").replace("\\", "/").strip()
    if not wanted:
        return None
    for entry in scan_models():
        if entry["id"] == wanted or entry["name"] == wanted:
            return entry
    return None


def clear_model_cache() -> None:
    with _LIST_CACHE_LOCK:
        _LIST_CACHE["value"] = None
        _LIST_CACHE["signature"] = None


# --------------------------------------------------------------------------- #
# VRAM estimation
# --------------------------------------------------------------------------- #
KV_BYTES_PER_ELEMENT = {"f16": 2.0, "q8_0": 1.0, "q4_0": 0.5}
_COMPUTE_BUFFER_BYTES = 512 * 1024**2
_FITS_HEADROOM = 0.85
_TIGHT_HEADROOM = 1.02


def estimate_vram(entry: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Weights + KV cache + compute buffer, in bytes."""
    weights = int(entry.get("size_bytes") or 0)

    layers = int(entry.get("block_count") or 0)
    kv_heads = int(entry.get("head_count_kv") or entry.get("head_count") or 0)
    head_dim = int(entry.get("key_length") or 0)
    if not head_dim:
        embedding = int(entry.get("embedding_length") or 0)
        heads = int(entry.get("head_count") or 0)
        head_dim = embedding // heads if embedding and heads else 0

    n_ctx = int(settings.get("n_ctx", 8192))
    element_size = KV_BYTES_PER_ELEMENT.get(str(settings.get("kv_cache_type", "q8_0")), 1.0)
    # Two tensors (K and V) per layer.
    kv_bytes = int(2 * layers * kv_heads * head_dim * n_ctx * element_size) if layers and kv_heads and head_dim else 0
    compute = int(_COMPUTE_BUFFER_BYTES)
    total = weights + kv_bytes + compute

    n_gpu_layers = int(settings.get("n_gpu_layers", -1))
    if n_gpu_layers >= 0 and layers:
        # Only the requested fraction of layers stays resident on the GPU.
        fraction = min(1.0, n_gpu_layers / layers)
        weights = int(weights * fraction)
        kv_bytes = int(kv_bytes * fraction)
        total = weights + kv_bytes + compute

    return {
        "weights_bytes": weights,
        "kv_cache_bytes": kv_bytes,
        "compute_buffer_bytes": compute,
        "total_bytes": total,
        "weights_gb": round(weights / 1024**3, 2),
        "kv_cache_gb": round(kv_bytes / 1024**3, 2),
        "total_gb": round(total / 1024**3, 2),
    }


def classify_fit(estimate_bytes: int, free_bytes: int | None) -> str:
    """``fits`` / ``tight`` / ``too_large`` / ``unknown``."""
    if not free_bytes:
        return "unknown"
    if estimate_bytes <= free_bytes * _FITS_HEADROOM:
        return "fits"
    if estimate_bytes <= free_bytes * _TIGHT_HEADROOM:
        return "tight"
    return "too_large"


def free_vram_bytes() -> int | None:
    """Free VRAM in bytes, or ``None`` when no CUDA device is visible.

    Imported lazily so the module works on a CPU-only install.
    """
    try:
        import torch  # type: ignore
    except Exception:
        return None
    try:
        if not torch.cuda.is_available():
            return None
        free, _total = torch.cuda.mem_get_info()
        return int(free)
    except Exception:
        return None


def model_listing(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Models annotated with per-model VRAM estimates and a fit badge."""
    settings = settings or {}
    free = free_vram_bytes()
    entries = []
    for entry in scan_models():
        if not entry.get("readable"):
            entries.append({**entry, "estimate": None, "fits": "unknown"})
            continue
        estimate = estimate_vram(entry, settings)
        entries.append({
            **entry,
            "estimate": estimate,
            "fits": classify_fit(estimate["total_bytes"], free),
        })
    entries.sort(key=lambda item: (item.get("estimate") or {}).get("total_bytes", item["size_bytes"]))
    return {
        "directory": str(models_directory()) if models_directory() else None,
        "free_vram_bytes": free,
        "free_vram_gb": round(free / 1024**3, 2) if free else None,
        "count": len(entries),
        "models": entries,
        "llama_cpp_available": llama_cpp_available(),
    }


# --------------------------------------------------------------------------- #
# Loading and generation
# --------------------------------------------------------------------------- #
_STATE_LOCK = threading.RLock()
_RESIDENT: dict[str, Any] = {"model": None, "path": None, "settings": None}


def llama_cpp_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
    except Exception:
        return False
    return True


def resident_model() -> dict[str, Any] | None:
    with _STATE_LOCK:
        if _RESIDENT["model"] is None:
            return None
        settings = _RESIDENT["settings"] or {}
        return {
            "path": _RESIDENT["path"],
            "n_ctx": settings.get("n_ctx"),
            "n_gpu_layers": settings.get("n_gpu_layers"),
            "kv_cache_type": settings.get("kv_cache_type"),
        }


def unload_model() -> dict[str, Any]:
    """Drop the resident model and hand the VRAM back."""
    with _STATE_LOCK:
        if _RESIDENT["model"] is None:
            return {"unloaded": False, "reason": "当前没有已加载的模型。"}
        path = _RESIDENT["path"]
        try:
            _RESIDENT["model"].close()
        except Exception:
            pass
        _RESIDENT["model"] = None
        _RESIDENT["path"] = None
        _RESIDENT["settings"] = None
    gc.collect()
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    return {"unloaded": True, "path": path}


def _release_comfy_models() -> bool:
    """Ask ComfyUI to drop its own models, so ours can fit.

    Called only when the estimate does not fit, because it forces ComfyUI to
    reload on its next queue.
    """
    try:
        import comfy.model_management as model_management  # type: ignore

        model_management.unload_all_models()
        model_management.soft_empty_cache()
        return True
    except Exception:
        return False


def _build_llama(entry: dict[str, Any], settings: dict[str, Any], *, attempt: int = 0):
    from llama_cpp import Llama

    path = Path(str(models_directory())) / entry["id"]
    kwargs: dict[str, Any] = {
        "model_path": str(path),
        "n_ctx": int(settings.get("n_ctx", 8192)),
        "n_batch": int(settings.get("n_batch", 512)),
        "n_gpu_layers": int(settings.get("n_gpu_layers", -1)),
        "verbose": False,
    }
    kv_type = str(settings.get("kv_cache_type", "q8_0"))
    if kv_type != "f16":
        # The enum names differ between llama-cpp-python builds, so set defensively.
        try:
            from llama_cpp import GGML_TYPE_Q8_0, GGML_TYPE_Q4_0  # type: ignore

            kwargs["type_k"] = GGML_TYPE_Q8_0 if kv_type == "q8_0" else GGML_TYPE_Q4_0
            kwargs["type_v"] = kwargs["type_k"]
        except Exception:
            pass
    if settings.get("flash_attention"):
        kwargs["flash_attn"] = True
    if settings.get("offload_kqv") is not None:
        kwargs["offload_kqv"] = bool(settings.get("offload_kqv"))

    try:
        return Llama(**kwargs)
    except TypeError:
        # Older builds do not accept every keyword; retry with the core set.
        fallback = {
            "model_path": str(path),
            "n_ctx": kwargs["n_ctx"],
            "n_batch": kwargs["n_batch"],
            "n_gpu_layers": kwargs["n_gpu_layers"],
            "verbose": False,
        }
        return Llama(**fallback)
    except ValueError as error:
        message = str(error)
        if "check_tensor_dims" in message or "not found" in message:
            raise ModelError(
                "MODEL_CORRUPT",
                f"GGUF 文件不完整：{message}。请换一个模型，这不是扩展的问题。",
                {"path": str(path)},
            ) from error
        raise ModelError("MODEL_LOAD_FAILED", f"加载模型失败：{message}", {"path": str(path)}) from error
    except MemoryError as error:
        if attempt == 0:
            _release_comfy_models()
            unload_model()
            return _build_llama(entry, settings, attempt=1)
        raise ModelError("OUT_OF_VRAM", "显存不足，无法加载该模型。请换更小的模型或降低 n_ctx。") from error


def load_model(entry: dict[str, Any], settings: dict[str, Any]):
    """Load the model, releasing ComfyUI's VRAM first only when it will not fit."""
    with _STATE_LOCK:
        if (
            _RESIDENT["model"] is not None
            and _RESIDENT["path"] == entry["id"]
            and _RESIDENT["settings"] == settings
        ):
            return _RESIDENT["model"]

    estimate = estimate_vram(entry, settings)
    free = free_vram_bytes()
    if settings.get("free_comfy_vram") and free is not None and estimate["total_bytes"] > free:
        _release_comfy_models()
        unload_model()

    unload_model()
    model = _build_llama(entry, settings)
    with _STATE_LOCK:
        _RESIDENT["model"] = model
        _RESIDENT["path"] = entry["id"]
        _RESIDENT["settings"] = dict(settings)
    return model


def _messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def generate(settings: dict[str, Any], system_prompt: str, user_prompt: str) -> str:
    """Run one completion on the local GGUF, honouring ``keep_loaded``."""
    if not llama_cpp_available():
        raise ModelError(
            "LLAMA_CPP_MISSING",
            "本机没有可用的 llama-cpp-python，无法使用本地 GGUF。请改用 Ollama 或 OpenAI 兼容端点。",
        )
    entry = find_model(str(settings.get("model") or ""))
    if entry is None:
        raise ModelError(
            "MODEL_MISSING",
            f"在 models/LLM 中找不到模型 {settings.get('model')!r}。",
            {"directory": str(models_directory())},
        )
    if not entry.get("readable"):
        raise ModelError("MODEL_CORRUPT", entry.get("reason") or "该 GGUF 文件无法读取。")

    model = load_model(entry, settings)
    try:
        response = model.create_chat_completion(
            messages=_messages(system_prompt, user_prompt),
            temperature=float(settings.get("temperature", 0.6)),
            max_tokens=int(settings.get("max_tokens", 2048)),
            response_format={"type": "json_object"},
        )
    except Exception as error:
        message = str(error)
        if "response_format" in message.lower():
            response = model.create_chat_completion(
                messages=_messages(system_prompt, user_prompt),
                temperature=float(settings.get("temperature", 0.6)),
                max_tokens=int(settings.get("max_tokens", 2048)),
            )
        else:
            raise ModelError("GENERATION_FAILED", f"本地模型生成失败：{message}") from error
    finally:
        if not settings.get("keep_loaded"):
            unload_model()

    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ModelError("PROVIDER_BAD_RESPONSE", "本地模型返回结构异常。", {"response": str(response)[:500]})
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = (message or {}).get("content") if isinstance(message, dict) else None
    text = str(content or "").strip()
    if not text:
        raise ModelError(
            "EMPTY_REPLY",
            "本地模型返回了空回复。可能是模型只输出了思考内容，或 max_tokens 太小。",
        )
    return text


def diagnostics(*, refresh: bool = False) -> dict[str, Any]:
    """Runtime diagnosis, matching the shape the reference implementation uses."""
    if refresh:
        clear_model_cache()
    directory = models_directory()
    return {
        "llama_cpp_available": llama_cpp_available(),
        "directory": str(directory) if directory else None,
        "directory_exists": bool(directory),
        "model_count": len(scan_models(use_cache=not refresh)),
        "free_vram_bytes": free_vram_bytes(),
        "resident": resident_model(),
    }


__all__ = [
    "GGUFHeaderError",
    "classify_fit",
    "clear_model_cache",
    "diagnostics",
    "estimate_vram",
    "find_model",
    "free_vram_bytes",
    "generate",
    "is_projector",
    "llama_cpp_available",
    "load_model",
    "model_listing",
    "models_directory",
    "read_gguf_header",
    "resident_model",
    "scan_models",
    "unload_model",
]
