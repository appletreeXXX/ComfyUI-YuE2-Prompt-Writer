"""Bundled writing contracts, pinned by SHA-256.

The hashes are copied out of ``guides/`` and verified on load. The point is not
paranoia about tampering — it is that a silently edited guide would change every
generation without any visible signal. Editing a guide without updating its hash
here makes the extension refuse to use it, loudly.

To recompute after editing a guide (from the extension root)::

    python -c "import hashlib,pathlib; \\
      t=pathlib.Path('guides/yue2_style_prompt_guide_en.md').read_text(encoding='utf-8-sig') \\
        .replace('\\r\\n','\\n').rstrip()+'\\n'; print(hashlib.sha256(t.encode()).hexdigest())"
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path


GUIDES_DIR = Path(__file__).resolve().parent.parent / "guides"


class GuideError(RuntimeError):
    """Raised when a guide is missing or fails its integrity check."""


@dataclass(frozen=True)
class GuideSpec:
    id: str
    title: str
    filename: str
    source_sha256: str
    purpose: str


GUIDES: dict[str, GuideSpec] = {
    "style": GuideSpec(
        id="style",
        title="YuE2 Style Prompt Writing Guide",
        filename="yue2_style_prompt_guide_en.md",
        source_sha256="21332b0a456a31767ad4525d40e457f102fba2f8673cc5415c8a421c6c898f5a",
        purpose="Contracts the writing model to emit English comma-separated style fragments.",
    ),
    "lyrics": GuideSpec(
        id="lyrics",
        title="YuE2 Lyrics Writing Guide",
        filename="yue2_lyrics_writing_guide_en.md",
        source_sha256="d2f44a005ddd1943aade32a02d2e7cd7943c6f8b524058d5093f90355d387d2f",
        purpose="Contracts the writing model to emit a singable, structurally valid lyric sheet.",
    ),
}


def _normalized(text: str) -> str:
    """Normalize line endings and guarantee a single trailing newline."""
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


@lru_cache(maxsize=4)
def load_guide(guide_id: str) -> dict[str, str]:
    """Load a guide and verify it against its pinned hash."""
    spec = GUIDES.get(guide_id)
    if spec is None:
        raise GuideError(f"Unknown guide: {guide_id!r}.")
    path = GUIDES_DIR / spec.filename
    if not path.is_file():
        raise GuideError(f"Missing bundled guide file: {spec.filename}.")
    content = _normalized(path.read_text(encoding="utf-8-sig"))
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if digest != spec.source_sha256:
        raise GuideError(
            f"Integrity check failed for {spec.filename}. "
            "If you edited the guide, update source_sha256 in backend/guides.py."
        )
    return {
        **asdict(spec),
        "content_sha256": digest,
        "content": content,
    }


def guide_catalog() -> list[dict[str, str]]:
    """Metadata for every bundled guide, without the bodies."""
    return [
        {key: value for key, value in load_guide(guide_id).items() if key != "content"}
        for guide_id in GUIDES
    ]


def guide_content(guide_id: str) -> str:
    return load_guide(guide_id)["content"]


__all__ = [
    "GUIDES",
    "GUIDES_DIR",
    "GuideError",
    "GuideSpec",
    "guide_catalog",
    "guide_content",
    "load_guide",
]
