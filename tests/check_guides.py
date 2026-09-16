"""Verify the bundled guides load and pass their SHA-256 integrity checks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.guides import GuideError, guide_catalog, load_guide  # noqa: E402

failures = []
for guide_id in ("style", "lyrics"):
    try:
        guide = load_guide(guide_id)
    except GuideError as error:
        failures.append(f"{guide_id}: {error}")
        print(f"  FAIL {guide_id}: {error}")
        continue
    print(f"  ok   {guide_id}: {len(guide['content'])} chars, sha {guide['content_sha256'][:16]}")

print(f"  catalog entries: {len(guide_catalog())}")

# The guide must be non-trivial: a truncated file would still hash consistently.
style = load_guide("style")["content"]
lyrics = load_guide("lyrics")["content"]
for label, text, needles in (
    ("style", style, ["Mandarin", "instrumental", "JSON", "eight words"]),
    ("lyrics", lyrics, ["word for word", "[Chorus]", "seven to eleven", "rhyme"]),
):
    for needle in needles:
        if needle.lower() not in text.lower():
            failures.append(f"{label} guide missing required rule: {needle!r}")
            print(f"  FAIL {label} guide missing {needle!r}")
if not failures:
    print("  ok   both guides contain their required rules")

if failures:
    print(f"\n{len(failures)} FAILURE(S)")
    sys.exit(1)
print("\nguide checks passed")
