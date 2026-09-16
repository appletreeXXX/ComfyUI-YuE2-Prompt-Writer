"""Writing-model providers for the YuE2 Prompt Writer.

Three interchangeable backends sit behind one call shape::

    generate(settings, system_prompt, user_prompt) -> str

``local`` runs a GGUF in this process, ``ollama`` talks to a local Ollama server,
and ``openai`` talks to any OpenAI-compatible endpoint.
"""

from . import contract, local_backend, ollama_backend, openai_backend

BACKENDS = {
    "local": local_backend,
    "ollama": ollama_backend,
    "openai": openai_backend,
}

__all__ = ["BACKENDS", "contract", "local_backend", "ollama_backend", "openai_backend"]
