"""Reproduce ComfyUI's custom-node loading against this extension.

This is the check that matters most: the original failure was
``ModuleNotFoundError: No module named '...ComfyUI-YuE2-Prompt-Writer.backend'``
raised by ComfyUI's ``load_custom_node``. This script performs the same import
with the same stub environment, so a regression shows up here rather than after
a ComfyUI restart.
"""

import importlib
import sys
import types
from pathlib import Path

EXTENSION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXTENSION.parent))

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")
        print(f"  FAIL {label}: expected {expected!r}, got {actual!r}")
    else:
        print(f"  ok   {label}")


# ---- stub the two ComfyUI modules the extension imports -------------------- #
print("== staging a ComfyUI-like environment ==")

from aiohttp import web  # noqa: E402

routes = web.RouteTableDef()


class _PromptServer:
    def __init__(self):
        self.routes = routes


server_stub = types.ModuleType("server")
server_stub.PromptServer = type("PromptServer", (), {"instance": _PromptServer()})
sys.modules["server"] = server_stub
print("  stubbed server.PromptServer")

models_dir = EXTENSION.parent.parent / "models"
folder_stub = types.ModuleType("folder_paths")
folder_stub.models_dir = str(models_dir)
folder_stub.add_model_folder_path = lambda *args, **kwargs: None
sys.modules["folder_paths"] = folder_stub
print(f"  stubbed folder_paths.models_dir = {models_dir}")

# ---- the actual import ComfyUI performs ------------------------------------ #
print("\n== importing the extension the way ComfyUI does ==")
try:
    module = importlib.import_module("ComfyUI-YuE2-Prompt-Writer".replace("-", "_"))
    print("  note: hyphenated import path failed, trying the ComfyUI mechanism")
    module = None
except Exception:
    module = None

if module is None:
    # ComfyUI loads the folder as a module spec with the directory name as the
    # module name. Replicate that exactly, hyphens included.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ComfyUI-YuE2-Prompt-Writer",
        EXTENSION / "__init__.py",
        submodule_search_locations=[str(EXTENSION)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["ComfyUI-YuE2-Prompt-Writer"] = module
    spec.loader.exec_module(module)

print("  ok   module imported without ModuleNotFoundError")

print("\n== extension surface ==")
check("WEB_DIRECTORY", module.WEB_DIRECTORY, "./web")
check("NODE_CLASS_MAPPINGS is empty (UI-only extension)", module.NODE_CLASS_MAPPINGS, {})
check("NODE_DISPLAY_NAME_MAPPINGS is empty", module.NODE_DISPLAY_NAME_MAPPINGS, {})
check("__version__ present", bool(module.__version__), True)
print(f"  version: {module.__version__}")
check("models/LLM directory registered", module.LLM_MODELS_DIRECTORY is not None, True)

print("\n== routes registered ==")
prefix = "/yue2_prompt_writer"
# RouteTableDef yields RouteDef entries; they expose ``method`` and ``path``.
paths = sorted({route.path for route in routes})
expected_paths = {
    f"{prefix}/health",
    f"{prefix}/catalog",
    f"{prefix}/guides",
    f"{prefix}/guide/{{guide_id}}",
    f"{prefix}/plan",
    f"{prefix}/lyrics/analyze",
    f"{prefix}/models",
    f"{prefix}/model/unload",
    f"{prefix}/runtime/gguf/diagnostics",
    f"{prefix}/provider/test",
    f"{prefix}/preview",
    f"{prefix}/generate",
    f"{prefix}/lyrics",
    f"{prefix}/cancel",
}
missing = expected_paths - set(paths)
extra = set(paths) - expected_paths
check("no missing endpoints", sorted(missing), [])
check("no unexpected endpoints", sorted(extra), [])
print(f"  registered {len(paths)} routes")

print("\n== frontend assets exist ==")
web_dir = EXTENSION / "web"
for relative in ("main.js", "api/yue2.js", "styles/yue2.css"):
    exists = (web_dir / relative).is_file()
    check(f"web/{relative}", exists, True)

print("\n== the specific import that used to fail ==")
backend_version = importlib.import_module("ComfyUI-YuE2-Prompt-Writer.backend.version")
check("backend.version imports", backend_version.VERSION, module.__version__)
backend_routes = importlib.import_module("ComfyUI-YuE2-Prompt-Writer.backend.routes")
check("backend.routes imports", backend_routes.ROUTE_PREFIX, prefix)

print("\n== all backend modules import cleanly ==")
for name in (
    "backend.catalog",
    "backend.lyrics",
    "backend.guides",
    "backend.assembly",
    "backend.models.contract",
    "backend.models.local_backend",
    "backend.models.ollama_backend",
    "backend.models.openai_backend",
    "backend.models._http",
):
    try:
        importlib.import_module(f"ComfyUI-YuE2-Prompt-Writer.{name}")
        print(f"  ok   {name}")
    except Exception as error:
        failures.append(f"{name} failed to import: {error}")
        print(f"  FAIL {name}: {error}")

print("\n== version consistency across files ==")
pyproject = (EXTENSION / "pyproject.toml").read_text(encoding="utf-8")
check("pyproject carries the same version", f'version = "{module.__version__}"' in pyproject, True)

print()
if failures:
    print(f"{len(failures)} FAILURE(S)")
    for failure in failures:
        print(" -", failure)
    sys.exit(1)
print("extension loads exactly as ComfyUI will load it")
