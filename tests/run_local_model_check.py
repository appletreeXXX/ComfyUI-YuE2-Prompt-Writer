"""Real end-to-end run on the local GGUF: theme -> lyrics -> style prompt.

Optional smoke test. It loads a real model onto the GPU, so it needs CUDA and a
GGUF under ``models/LLM``. Verify the *wiring* with the other check scripts; run
this one when you want proof the default provider actually produces a prompt.

Usage::

    python tests/run_local_model_check.py --list        # just list models
    python tests/run_local_model_check.py               # style prompt only
    python tests/run_local_model_check.py --idea "雨夜开车"  # full chain
"""

import argparse
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Stage the ComfyUI modules ComfyUI itself provides.
from aiohttp import web  # noqa: E402

routes = web.RouteTableDef()
server_stub = types.ModuleType("server")
server_stub.PromptServer = type("PromptServer", (), {"instance": type("P", (), {"routes": routes})()})
sys.modules["server"] = server_stub

models_dir = ROOT.parent.parent / "models"
folder_stub = types.ModuleType("folder_paths")
folder_stub.models_dir = str(models_dir)
sys.modules["folder_paths"] = folder_stub

from backend import assembly  # noqa: E402
from backend.models import local_backend as lb  # noqa: E402

BRIEF = {
    "genre": "citypop",
    "vocal": "female",
    "lyrics": (
        "[Verse]\n霓虹在车窗外倒退\n收音机里旧歌低回\n\n"
        "[Chorus]\n就让我一直开着车\n开过这座睡着的城\n\n"
        "[Verse]\n雨刷划开一片模糊\n导航说着下个路口\n\n"
        "[Chorus]\n就让我一直开着车\n开过这座睡着的城\n"
    ),
    "mood": "auto",
    "tempo": "auto",
    "structure": "auto",
    "language": "auto",
    "cot": "full",
    "vae": "YuE2-Vae",
    "lyric_length": "standard",
    "seed": -1,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="list models and exit")
    parser.add_argument("--model", default="", help="model id; default is the largest that fits")
    parser.add_argument("--idea", default="", help="also run idea -> lyrics -> style on one load")
    parser.add_argument("--n-ctx", type=int, default=8192)
    args = parser.parse_args()

    listing = lb.model_listing({"n_ctx": args.n_ctx, "n_gpu_layers": -1, "kv_cache_type": "q8_0"})
    print(f"models/LLM: {listing['directory']}")
    print(f"free VRAM: {listing['free_vram_gb']} GB   llama-cpp-python: {listing['llama_cpp_available']}")
    for model in listing["models"]:
        estimate = model.get("estimate") or {}
        print(f"  {model['size_gb']:>6.2f} GB  {model['id']}  [{model['fits']}] est {estimate.get('total_gb')} GB")
    if args.list:
        return 0
    if not listing["models"]:
        print("no models found; nothing to do")
        return 1

    # The largest model that loads fully is the quality/speed sweet spot.
    chosen = args.model or next(
        (m["id"] for m in reversed(listing["models"]) if m["fits"] == "fits"),
        listing["models"][0]["id"],
    )
    print(f"\nusing: {chosen}")

    settings = {
        "kind": "local",
        "model": chosen,
        "n_ctx": args.n_ctx,
        "n_gpu_layers": -1,
        "kv_cache_type": "q8_0",
        "reasoning_budget": 0,
        "keep_loaded": bool(args.idea),  # reuse one load for the whole chain
        "free_comfy_vram": True,
        "max_tokens": 2048,
        "temperature": 0.6,
    }

    failures = []
    try:
        if args.idea:
            print("\n--- stage 1: idea -> lyrics ---")
            start = time.perf_counter()
            written = assembly.run_lyrics_generate({**BRIEF, "idea": args.idea}, settings)
            print(f"  {time.perf_counter() - start:.1f}s")
            print(f"  title: {written['title']}")
            print("  " + "\n  ".join(written["normalized_lyrics"].splitlines()[:14]))
            if written.get("quality_notes"):
                print(f"  quality notes: {written['quality_notes']}")
            lyrics = written["normalized_lyrics"]
        else:
            lyrics = BRIEF["lyrics"]

        print("\n--- stage 2: lyrics -> style prompt ---")
        start = time.perf_counter()
        result = assembly.run_generate({**BRIEF, "lyrics": lyrics}, settings)
        elapsed = time.perf_counter() - start
        print(f"  {elapsed:.1f}s")
        print(f"  source: {result['source']}")

        if result.get("error"):
            print(f"  MODEL ERROR: {result['error']}")
            failures.append("model call failed")

        print(f"\n  style ({result['fragment_count']} fragments):")
        print(f"    {result['style']}")
        if result.get("notes"):
            print(f"  notes: {result['notes']}")
        if result.get("vocal_arrangement"):
            print(f"  arrangement: {result['vocal_arrangement']}")

        # Assertions that catch a model which ignored the guide.
        fragments = result["style_fragments"]
        if result["source"].startswith("model:"):
            if not any(f.lower() in {"mandarin", "cantonese", "english", "japanese", "korean"} for f in fragments):
                print("\n  WARNING: no language tag in the style prompt")
                failures.append("model omitted the language tag")
            if any(any("\u4e00" <= c <= "\u9fff" for c in f) for f in fragments):
                failures.append("CJK leaked into the style prompt")
            else:
                print("\n  ok   no CJK leaked into the style prompt")
            if not (8 <= len(fragments) <= 20):
                failures.append(f"fragment count {len(fragments)} outside 8-20")
            else:
                print("  ok   fragment count within 8-20")
    finally:
        released = lb.unload_model()
        print(f"\nunload: {released}")
        print(f"free VRAM after: {(lb.free_vram_bytes() or 0) / 1024**3:.2f} GB")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        for failure in failures:
            print(" -", failure)
        return 1
    print("\nlocal model run passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
