"""ComfyUI YuE2 Prompt Writer.

A prompt-writing workspace for YuE2-3B inside ComfyUI. It is a UI extension, not
a workflow node: it turns lyrics, a chosen genre, and a vocal setting into a
ready-to-paste YuE2 ``style`` prompt, a normalized lyric sheet, and a complete
YuE2 generation JSON.

The writing model can run **in this process** from a GGUF in ``models/LLM``
(the default), or through Ollama / any OpenAI-compatible endpoint.

The extension never runs YuE2 and never queues a graph. Model weights are not
bundled.
"""

from pathlib import Path

from .backend.version import VERSION

WEB_DIRECTORY = "./web"

# Register ComfyUI's own models/LLM folder so the local GGUF backend lists and
# loads writing models from where ComfyUI users already keep them.
LLM_MODELS_DIRECTORY: Path | None
try:  # pragma: no cover - requires ComfyUI
    import folder_paths

    LLM_MODELS_DIRECTORY = Path(folder_paths.models_dir) / "LLM"
    LLM_MODELS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    folder_paths.add_model_folder_path("LLM", str(LLM_MODELS_DIRECTORY), is_default=True)
except Exception:  # pragma: no cover - only when imported outside ComfyUI
    LLM_MODELS_DIRECTORY = None

# Importing the route module registers the extension endpoints with ComfyUI.
from .backend import routes as _routes  # noqa: E402,F401

NODE_CLASS_MAPPINGS: dict[str, object] = {}
NODE_DISPLAY_NAME_MAPPINGS: dict[str, str] = {}

__version__ = VERSION

__all__ = [
    "LLM_MODELS_DIRECTORY",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
    "__version__",
]
