"""End-to-end HTTP checks: start the real routes the way ComfyUI does.

ComfyUI is not installed in a unit-test sense, so a stub ``server`` module
provides ``PromptServer.instance.routes`` and the routes are imported for real.
That means this exercises the actual aiohttp handlers, not a reimplementation.

Requires aiohttp, which ships with ComfyUI. When it is missing the script skips
rather than failing, so it stays runnable in a bare interpreter.
"""

import asyncio
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    print("SKIP: aiohttp is not available (it ships with ComfyUI).")
    sys.exit(0)

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")
        print(f"  FAIL {label}: expected {expected!r}, got {actual!r}")
    else:
        print(f"  ok   {label}")


# ---- stub the ComfyUI server module ---------------------------------------- #
routes = web.RouteTableDef()


class _PromptServer:
    def __init__(self):
        self.routes = routes


stub = types.ModuleType("server")
stub.PromptServer = type("PromptServer", (), {"instance": _PromptServer()})
sys.modules["server"] = stub

# folder_paths is optional; the real ComfyUI provides it.
if "folder_paths" not in sys.modules:
    real_models = ROOT.parent.parent / "models"
    if real_models.is_dir():
        fake = types.ModuleType("folder_paths")
        fake.models_dir = str(real_models)
        sys.modules["folder_paths"] = fake

import backend.routes as routes_module  # noqa: E402
from backend.routes import ROUTE_PREFIX  # noqa: E402

PREFIX = ROUTE_PREFIX
print(f"route prefix: {PREFIX}")
print(f"registered routes: {len([r for r in routes])}")

DEFAULT_PAYLOAD = {
    "genre": "citypop",
    "vocal": "female",
    "lyrics": (
        "[Verse]\n霓虹在车窗外倒退\n收音机里旧歌低回\n\n"
        "[Chorus]\n就让我一直开着车\n开过这座睡着的城\n\n"
        "[Verse]\n雨刷划开一片模糊\n导航说着下个路口\n\n"
        "[Chorus]\n就让我一直开着车\n开过这座睡着的城\n"
    ),
    "idea": "",
    "mood": "auto",
    "tempo": "auto",
    "structure": "auto",
    "language": "auto",
    "cot": "full",
    "vae": "YuE2-Vae",
    "lyric_length": "standard",
    "seed": -1,
    "provider": {"kind": "local", "model": "nonexistent.gguf"},
}


async def main():
    app = web.Application()
    app.add_routes(routes)

    print("\n== health ==")
    async with TestClient(TestServer(app)) as client:
        response = await client.get(f"{PREFIX}/health")
        check("health status", response.status, 200)
        health = await response.json()
        check("health ok flag", health.get("ok"), True)
        check("health reports a version", bool(health.get("version")), True)
        print(f"  version: {health['version']}, llama_cpp: {health['llama_cpp_available']}")
        print(f"  models dir: {health['llm_models_directory']}")

        print("\n== catalog ==")
        response = await client.get(f"{PREFIX}/catalog")
        check("catalog status", response.status, 200)
        catalog = await response.json()
        genre_count = len(catalog["genres"])
        check("at least 32 genre presets", genre_count >= 32, True)
        print(f"  genre presets: {genre_count}")
        check("genres have English tags", all(isinstance(g["tags"], list) and g["tags"] for g in catalog["genres"]), True)
        check("mood includes auto", any(m["id"] == "auto" for m in catalog["moods"]), True)
        check("tempo includes auto", any(t["id"] == "auto" for t in catalog["tempos"]), True)
        check("language includes auto", any(l["id"] == "auto" for l in catalog["languages"]), True)
        check("cot has the three official modes", sorted(c["id"] for c in catalog["cot"]), ["full", "melody", "off"])
        check("vocal settings include duet", any(v["id"] == "duet" for v in catalog["vocals"]), True)

        print("\n== guides ==")
        response = await client.get(f"{PREFIX}/guides")
        guides = (await response.json())["guides"]
        check("two guides bundled", sorted(g["id"] for g in guides), ["lyrics", "style"])
        response = await client.get(f"{PREFIX}/guide/style")
        check("style guide fetchable", response.status, 200)
        body = await response.json()
        check("style guide has content", len(body["content"]) > 1000, True)
        response = await client.get(f"{PREFIX}/guide/nope")
        check("unknown guide is a 404", response.status, 404)

        print("\n== plan (deterministic, no model) ==")
        response = await client.post(f"{PREFIX}/plan", json=DEFAULT_PAYLOAD)
        check("plan status", response.status, 200)
        plan = await response.json()
        analysis = plan["analysis"]
        check("plan detects Mandarin", analysis["language"], "Mandarin")
        # ``structure`` is a de-duplicated summary, so a repeated chorus appears
        # once; ``sections`` is the exhaustive list and must show all four blocks.
        check("plan lists all four sections", len(analysis["sections"]), 4)
        check(
            "plan section headers",
            [s["header"] for s in analysis["sections"]],
            ["[Verse 1]", "[Chorus]", "[Verse 2]", "[Chorus]"],
        )
        check("structure summary de-duplicates", analysis["structure"], "[Verse 1] - [Chorus] - [Verse 2]")
        check("plan has a duration estimate", bool(analysis["duration"]["label"]), True)
        print(f"  structure: {analysis['structure']}")
        print(f"  duration: {analysis['duration']['label']}, singable lines: {analysis['singable_lines']}")

        print("\n== plan rejects bad values ==")
        response = await client.post(f"{PREFIX}/plan", json={**DEFAULT_PAYLOAD, "mood": "angry"})
        check("bad mood is a 400", response.status, 400)
        error = (await response.json())["error"]
        check("error code", error["code"], "ASSEMBLY_ERROR")
        check("error lists allowed values", "auto" in error["details"]["allowed"], True)

        print("\n== lyrics analysis ==")
        response = await client.post(f"{PREFIX}/lyrics/analyze", json={"lyrics": DEFAULT_PAYLOAD["lyrics"], "brief": {}})
        check("analyze status", response.status, 200)
        analyzed = (await response.json())["analysis"]
        check("normalized text present", "[Chorus]" in analyzed["normalized"], True)
        check("no stray chorus numbering", "[Chorus 1]" in analyzed["normalized"], False)

        print("\n== local preview (never calls a model) ==")
        response = await client.post(f"{PREFIX}/preview", json=DEFAULT_PAYLOAD)
        check("preview status", response.status, 200)
        result = await response.json()
        check("preview source", result["source"], "local_preview")
        check("style present", bool(result["style"]), True)
        check("six outputs present", all(result.get(k) for k in ("style", "normalized_lyrics", "vocal_arrangement", "json", "python_snippet")), True)
        check("style carries the language tag", "Mandarin" in result["style"], True)
        print(f"  style: {result['style'][:110]}...")

        print("\n== models listing ==")
        response = await client.get(f"{PREFIX}/models")
        check("models status", response.status, 200)
        listing = await response.json()
        check("listing has a count", isinstance(listing["count"], int), True)
        print(f"  directory: {listing['directory']}, count: {listing['count']}, free VRAM: {listing['free_vram_gb']} GB")

        print("\n== provider probe ==")
        response = await client.post(f"{PREFIX}/provider/test", json={"provider": {"kind": "local", "model": "x.gguf"}})
        check("probe status", response.status, 200)
        probe = await response.json()
        check("probe ok", probe["ok"], True)
        check("probe reports llama_cpp", "llama_cpp_available" in probe, True)

        print("\n== unreachable remote providers report cleanly, not as a crash ==")
        response = await client.post(
            f"{PREFIX}/provider/test",
            json={"provider": {"kind": "ollama", "model": "qwen3:8b", "host": "http://127.0.0.1:1"}},
        )
        check("probe still 200", response.status, 200)
        probe = await response.json()
        check("probe reports failure", probe["ok"], False)
        check("failure carries a code", probe["error"]["code"], "PROVIDER_UNREACHABLE")
        check("api key never returned", "api_key" not in json.dumps(probe) or probe.get("provider", {}).get("api_key") == "", True)

        print("\n== generate degrades to the fallback when the model is missing ==")
        response = await client.post(f"{PREFIX}/generate", json=DEFAULT_PAYLOAD)
        check("generate status", response.status, 200)
        generated = await response.json()
        check("fell back", generated["source"], "fallback")
        check("error surfaced", generated["error"]["code"], "MODEL_MISSING")
        check("style still produced", bool(generated["style"]), True)
        print(f"  provider note: {generated['provider_note']}")

        print("\n== settings validation happens before any model work ==")
        response = await client.post(f"{PREFIX}/generate", json={**DEFAULT_PAYLOAD, "provider": {"kind": "nope"}})
        check("bad provider kind is a 400", response.status, 400)
        check("code", (await response.json())["error"]["code"], "INVALID_SETTINGS")

        response = await client.post(f"{PREFIX}/generate", json={**DEFAULT_PAYLOAD, "provider": {"kind": "local", "model": "m.gguf", "n_ctx": 1}})
        check("out-of-range n_ctx is a 400", response.status, 400)

        print("\n== diagnostics ==")
        response = await client.post(f"{PREFIX}/runtime/gguf/diagnostics", json={"refresh": True})
        check("diagnostics status", response.status, 200)
        diag = await response.json()
        check("diagnostics reports availability", "llama_cpp_available" in diag, True)

    print("\n== api keys are never echoed back ==")
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            f"{PREFIX}/provider/test",
            json={"provider": {"kind": "openai", "model": "gpt-4o-mini", "host": "http://127.0.0.1:1", "api_key": "sk-supersecret"}},
        )
        raw = await response.text()
        check("secret not in the response body", "sk-supersecret" in raw, False)


asyncio.run(main())

print()
if failures:
    print(f"{len(failures)} FAILURE(S)")
    for failure in failures:
        print(" -", failure)
    sys.exit(1)
print("route checks passed")
