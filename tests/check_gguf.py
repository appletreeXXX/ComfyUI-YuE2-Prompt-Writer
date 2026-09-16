"""Verify GGUF discovery, header parsing and VRAM estimation.

Run against the real ``models/LLM`` folder. This is the path that used to take
over two minutes with ``gguf.GGUFReader``, so the test also asserts it is fast.

When ComfyUI's ``folder_paths`` is unavailable the script falls back to the
workspace's own models directory so it can still be run standalone.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.models import local_backend as lb  # noqa: E402

failures = []

# ---- stand in for ComfyUI's folder_paths when running outside ComfyUI ------- #
if lb.models_directory() is None:
    comfy_root = ROOT.parent.parent
    candidate = comfy_root / "models" / "LLM"
    if not candidate.is_dir():
        print(f"SKIP: no models/LLM directory found (looked at {candidate})")
        sys.exit(0)

    import types

    fake = types.ModuleType("folder_paths")
    fake.models_dir = str(candidate.parent)
    sys.modules["folder_paths"] = fake
    lb.clear_model_cache()
    print(f"using fallback models dir: {candidate}")

print("\n== discovery timing ==")
start = time.perf_counter()
models = lb.scan_models(use_cache=False)
elapsed = time.perf_counter() - start
print(f"  found {len(models)} model(s) in {elapsed:.2f}s")
if elapsed > 10:
    failures.append(f"scan took {elapsed:.2f}s, expected well under 10s")
else:
    print("  ok   scan stays fast")

if not models:
    failures.append("no GGUF models discovered")
else:
    print("\n== discovered models ==")
    for entry in models:
        state = "readable" if entry.get("readable") else "UNREADABLE"
        detail = (
            f"{entry.get('architecture')}, {entry.get('block_count')} layers, "
            f"ctx {entry.get('context_length')}"
            if entry.get("readable")
            else entry.get("reason", "")
        )
        print(f"  {entry['size_gb']:>6.2f} GB  {entry['id']}  [{state}] {detail}")

    print("\n== projectors are excluded from the picker ==")
    names = [entry["id"] for entry in models]
    if any("mmproj" in name.lower() for name in names):
        failures.append("projector files leaked into the model list")
    else:
        print("  ok   no mmproj/projector entries")

    print("\n== VRAM estimation ==")
    settings = {"n_ctx": 8192, "n_gpu_layers": -1, "kv_cache_type": "q8_0"}
    free = lb.free_vram_bytes()
    print(f"  free VRAM: {free / 1024**3:.2f} GB" if free else "  free VRAM: unavailable (CPU only)")

    readable = [entry for entry in models if entry.get("readable")]
    for entry in readable:
        estimate = lb.estimate_vram(entry, settings)
        fit = lb.classify_fit(estimate["total_bytes"], free)
        print(
            f"  {entry['id']}: weights {estimate['weights_gb']} GB + kv {estimate['kv_cache_gb']} GB "
            f"= {estimate['total_gb']} GB -> {fit}"
        )
        if estimate["total_bytes"] <= entry["size_bytes"]:
            failures.append(f"{entry['id']}: total estimate is below the raw weight size")
        if not 0 < estimate["kv_cache_gb"] < 40:
            failures.append(f"{entry['id']}: implausible KV cache estimate {estimate['kv_cache_gb']} GB")

    # A smaller n_ctx must never increase the estimate.
    small = lb.estimate_vram(readable[0], {**settings, "n_ctx": 2048})
    large = lb.estimate_vram(readable[0], {**settings, "n_ctx": 32768})
    if small["total_bytes"] >= large["total_bytes"]:
        failures.append("KV cache scaling does not respond to n_ctx")
    else:
        print(f"  ok   KV cache scales with n_ctx ({small['kv_cache_gb']} GB -> {large['kv_cache_gb']} GB)")

    # Partial offload must reduce the resident weight footprint.
    partial = lb.estimate_vram(readable[0], {**settings, "n_gpu_layers": 8})
    print(f"  ok   partial offload: {partial['weights_gb']} GB on GPU at 8 layers")

print("\n== listing shape ==")
listing = lb.model_listing({"n_ctx": 8192, "n_gpu_layers": -1, "kv_cache_type": "q8_0"})
print(f"  directory: {listing['directory']}")
print(f"  count: {listing['count']}, llama_cpp available: {listing['llama_cpp_available']}")
if listing["count"] != len(models):
    failures.append("model_listing count disagrees with scan_models")
else:
    print("  ok   listing count matches discovery")

print("\n== diagnostics ==")
diag = lb.diagnostics(refresh=True)
print(f"  {diag}")

print()
if failures:
    print(f"{len(failures)} FAILURE(S)")
    for failure in failures:
        print(" -", failure)
    sys.exit(1)
print("GGUF backend checks passed")
