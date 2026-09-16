"""Request assembly, reply cleaning, and the deterministic fallback writer.

This module owns the contract between the workspace payload and the providers,
and it owns the answer hygiene: a model reply is never trusted verbatim. The
``style`` value in particular is sanitised, because the single most common
failure is a model leaking Chinese lyric fragments or whole sentences into what
must be a short list of English fragments.

Everything here is pure except :func:`run_generate`, which delegates to a
provider. That split is what lets the fallback path work with no model at all.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import catalog
from .guides import GuideError, guide_content
from .lyrics import analyze, estimate_duration, vocal_arrangement
from .models import BACKENDS
from .models.contract import (
    ModelError,
    drop_reasoning_fields,
    final_text,
    strip_json_fence,
)


MAX_STYLE_FRAGMENTS = 20
MIN_STYLE_FRAGMENTS = 8
MAX_FRAGMENT_WORDS = 8
MAX_LYRIC_CHARS_FOR_PROMPT = 6000


class AssemblyError(ModelError):
    def __init__(self, message: str, details: Any = None):
        super().__init__("ASSEMBLY_ERROR", message, details)


# --------------------------------------------------------------------------- #
# Brief handling
# --------------------------------------------------------------------------- #
def normalize_brief(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a workspace payload into the fields assembly depends on.

    ``mood`` accepting ``auto`` is load-bearing: an earlier catalog omitted it and
    every request from the workspace default payload failed validation.
    """
    raw = dict(payload or {})

    genre_id = str(raw.get("genre") or catalog.DEFAULT_GENRE)
    vocal_id = str(raw.get("vocal") or catalog.DEFAULT_VOCAL)
    brief: dict[str, Any] = {
        "genre": genre_id,
        "genre_preset": catalog.genre_preset(genre_id),
        "vocal": vocal_id,
        "vocal_setting": catalog.vocal_setting(vocal_id),
        "lyrics": str(raw.get("lyrics") or ""),
        "idea": str(raw.get("idea") or "").strip(),
        "title": str(raw.get("title") or "").strip(),
        "extra_notes": str(raw.get("notes") or "").strip(),
        "temperature": raw.get("temperature"),
    }

    for key, table, default, label in (
        ("mood", catalog.MOODS, catalog.DEFAULT_MOOD, "mood"),
        ("tempo", catalog.TEMPOS, catalog.DEFAULT_TEMPO, "tempo"),
        ("structure", catalog.STRUCTURES, catalog.DEFAULT_STRUCTURE, "structure"),
        ("language", catalog.LANGUAGES, catalog.DEFAULT_LANGUAGE, "language"),
    ):
        value = str(raw.get(key) or default)
        if value not in table:
            raise AssemblyError(
                f"Unknown {label}: {value!r}.",
                {"allowed": list(table)},
            )
        brief[key] = value

    cot = str(raw.get("cot") or catalog.DEFAULT_COT)
    if cot not in catalog.COT_MODES:
        raise AssemblyError(f"Unknown cot: {cot!r}.", {"allowed": list(catalog.COT_MODES)})
    brief["cot"] = cot

    vae = str(raw.get("vae") or catalog.DEFAULT_VAE)
    brief["vae"] = vae if vae in catalog.VAE_CHOICES else catalog.DEFAULT_VAE

    lyric_length = str(raw.get("lyric_length") or catalog.DEFAULT_LYRIC_LENGTH)
    brief["lyric_length"] = lyric_length if lyric_length in catalog.LYRIC_LENGTHS else catalog.DEFAULT_LYRIC_LENGTH

    brief["seed"] = _coerce_seed(raw.get("seed"))
    return brief


def _coerce_seed(value: Any) -> int:
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return -1
    return seed


def _resolved_language(brief: dict[str, Any], detected: str) -> str:
    """Explicit request wins; otherwise use what the lyrics actually are."""
    requested = catalog.LANGUAGES.get(brief.get("language") or "auto")
    if requested:
        return requested
    if detected and detected != "unknown":
        return detected
    return "English"


def _compact_lyrics(text: str) -> str:
    """Shorten a very long sheet for the prompt while keeping its shape.

    A naive truncation would cut mid-section and hide the structure from the
    model; dropping whole sections keeps the shape legible.
    """
    if len(text) <= MAX_LYRIC_CHARS_FOR_PROMPT:
        return text
    blocks = [block for block in text.split("\n\n") if block.strip()]
    kept: list[str] = []
    total = 0
    for block in blocks:
        if total + len(block) > MAX_LYRIC_CHARS_FOR_PROMPT and kept:
            break
        kept.append(block)
        total += len(block) + 2
    return "\n\n".join(kept)


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #
def build_style_request(brief: dict[str, Any], analysis: dict[str, Any]) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for a style-prompt generation."""
    try:
        guide = guide_content("style")
    except GuideError as error:
        raise AssemblyError(str(error)) from error

    preset = brief["genre_preset"]
    vocal = brief["vocal_setting"]
    language = _resolved_language(brief, analysis.get("language", "unknown"))
    mood = catalog.MOODS.get(brief["mood"])
    tempo = catalog.TEMPOS.get(brief["tempo"]) or preset["tempo"]
    structure = catalog.STRUCTURES.get(brief["structure"])

    lines = [
        "## Song brief",
        f"- Genre preset: {preset['label_zh']} (baseline tags: {', '.join(preset['tags'])})",
        f"- Vocal setting: {vocal['label_zh']} ({vocal['guide_zh']})",
        f"- Language of the lyrics: {language}",
        f"- Required language tag: {language}",
        f"- Mood: {mood or 'not specified — infer from the lyrics'}",
        f"- Tempo: {tempo}",
        f"- Structure: {structure or 'not specified'}",
        f"- Chain-of-thought mode: {brief['cot']}",
    ]
    if brief.get("title"):
        lines.append(f"- Title: {brief['title']}")
    if brief.get("extra_notes"):
        lines.append(f"- Additional requirements from the user: {brief['extra_notes']}")

    lines += [
        "",
        "## Baseline arrangement for this preset",
        f"- Instruments: {', '.join(preset['instruments'])}",
        f"- Atmosphere: {', '.join(preset['atmosphere'])}",
        f"- Rhythm: {preset['rhythm']}",
        f"- Production: {', '.join(preset['production'])}",
        "",
        "## Deterministic analysis of the lyrics",
        f"- Detected language: {analysis.get('language')} (confidence: {analysis.get('language_confidence')})",
        f"- Sections: {analysis.get('structure') or 'none'}",
        f"- Singable lines: {analysis.get('singable_lines', 0)}",
        f"- Estimated duration: {(analysis.get('duration') or {}).get('label', 'unknown')}",
        f"- Suggested vocal arrangement: {analysis.get('vocal_arrangement') or 'n/a'}",
    ]

    notes = analysis.get("quality_notes") or []
    if notes:
        lines.append("- Quality notes:")
        lines += [f"  - {note}" for note in notes]

    lyrics = _compact_lyrics(brief["lyrics"])
    if lyrics.strip():
        lines += ["", "## Lyrics", "```text", lyrics.rstrip(), "```"]
    else:
        lines += ["", "## Lyrics", "(The user has not written lyrics yet. Write the style prompt for an instrumental-leaning arrangement that suits the brief.)"]

    lines += [
        "",
        "Follow the guide exactly. Return only the JSON object with the keys",
        "style, vocal_arrangement and notes.",
    ]
    return guide, "\n".join(lines)


def build_lyrics_request(brief: dict[str, Any]) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for an idea-to-lyrics generation."""
    try:
        guide = guide_content("lyrics")
    except GuideError as error:
        raise AssemblyError(str(error)) from error

    preset = brief["genre_preset"]
    vocal = brief["vocal_setting"]
    language = catalog.LANGUAGES.get(brief.get("language") or "auto") or "Mandarin"
    mood = catalog.MOODS.get(brief["mood"])
    tempo = catalog.TEMPOS.get(brief["tempo"]) or preset["tempo"]
    length_label = catalog.LYRIC_LENGTH_LABELS.get(brief["lyric_length"], brief["lyric_length"])

    lines = [
        "## Lyric writing brief",
        f"- Theme or idea: {brief.get('idea') or '(none given — invent a coherent theme that suits the genre)'}",
        f"- Genre preset: {preset['label_zh']} (imagery should fit: {', '.join(preset['atmosphere'])})",
        f"- Vocal setting: {vocal['label_zh']} ({vocal['guide_zh']})",
        f"- Language to write in: {language}",
        f"- Requested length: {length_label}",
        f"- Mood: {mood or 'let the theme decide'}",
        f"- Tempo: {tempo}",
    ]
    if brief.get("title"):
        lines.append(f"- Working title: {brief['title']}")
    if brief.get("extra_notes"):
        lines.append(f"- Additional requirements from the user: {brief['extra_notes']}")
    if brief.get("lyrics").strip():
        lines += [
            "",
            "## Existing draft to revise",
            "The user already has a draft. Improve it toward the guide's rules rather",
            "than replacing it: keep their language, voice and meaning.",
            "```text",
            _compact_lyrics(brief["lyrics"]).rstrip(),
            "```",
        ]

    lines += [
        "",
        "Follow the guide exactly. Return only the JSON object with the keys",
        "title and lyrics.",
    ]
    return guide, "\n".join(lines)


# --------------------------------------------------------------------------- #
# Reply parsing
# --------------------------------------------------------------------------- #
def parse_json_reply(text: str) -> dict[str, Any]:
    """Extract a JSON object from a model reply, tolerating common drift."""
    cleaned = strip_json_fence(final_text(text))
    if not cleaned:
        raise ModelError("EMPTY_REPLY", "模型返回了空回复。")

    try:
        decoded = json.loads(cleaned)
    except json.JSONDecodeError:
        decoded = _salvage_json(cleaned)

    if decoded is None:
        raise ModelError(
            "REPLY_NOT_JSON",
            "模型没有返回合法的 JSON。请重试，或换一个更强的模型。",
            {"reply": cleaned[:600]},
        )
    if not isinstance(decoded, dict):
        raise ModelError(
            "REPLY_NOT_JSON",
            "模型返回的 JSON 不是对象。",
            {"reply": cleaned[:600]},
        )

    decoded = drop_reasoning_fields(decoded)
    if not decoded:
        raise ModelError(
            "THINKING_ONLY",
            "模型只输出了思考字段，没有给出答案。请把 reasoning_budget 设为 0，或换一个模型。",
        )
    return decoded


def _salvage_json(text: str) -> dict[str, Any] | None:
    """Best-effort recovery for the two shapes models actually produce.

    Models regularly (a) wrap the object in prose, or (b) emit a JSON string whose
    value contains raw newlines. Both are recoverable without a re-generation.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            decoded = json.loads(candidate)
            if isinstance(decoded, dict):
                return decoded
        except json.JSONDecodeError:
            repaired = re.sub(r"(?<!\\)\n", "\\\\n", candidate)
            repaired = repaired.replace("\\\\n", "\\n")
            try:
                decoded = json.loads(repaired)
                if isinstance(decoded, dict):
                    return decoded
            except json.JSONDecodeError:
                pass
    return None


# --------------------------------------------------------------------------- #
# Style sanitisation
# --------------------------------------------------------------------------- #
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_FENCE = re.compile(r"```[a-zA-Z]*|```")


def sanitize_style(raw: Any) -> list[str]:
    """Clean a model-authored style value into a list of fragments.

    Drops, in order: code fences, CJK characters, anything that reads as a
    sentence, and duplicates. Then trims to the fragment budget.
    """
    if isinstance(raw, list):
        text = ", ".join(str(item) for item in raw)
    else:
        text = str(raw or "")
    text = _FENCE.sub("", text)

    fragments: list[str] = []
    seen: set[str] = set()
    for piece in re.split(r"[,;\n|]+", text):
        fragment = piece.strip().strip(".").strip()
        if not fragment:
            continue
        if _CJK.search(fragment):
            # A leaked lyric or a Chinese gloss: never part of a style prompt.
            continue
        if len(fragment.split()) > MAX_FRAGMENT_WORDS:
            # Sentence-shaped. Drop rather than shorten, because a truncated
            # sentence still reads as prose to the model.
            continue
        key = fragment.lower()
        if key in seen:
            continue
        seen.add(key)
        fragments.append(fragment)

    return fragments[:MAX_STYLE_FRAGMENTS]


def fallback_style_fragments(brief: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    """Assemble a usable style list from the catalog, with no model call.

    This is the "no model configured" path, and also the degradation path when a
    provider fails: the workspace always produces something pasteable.
    """
    preset = brief["genre_preset"]
    vocal = brief["vocal_setting"]
    language = _resolved_language(brief, analysis.get("language", "unknown"))

    fragments: list[str] = []
    fragments += preset["tags"]
    fragments.append(language)
    fragments.append(vocal["style_tag"])
    fragments += preset["instruments"]

    mood = catalog.MOODS.get(brief["mood"])
    fragments += [mood] if mood else preset["moods"]

    fragments += preset["atmosphere"]
    tempo = catalog.TEMPOS.get(brief["tempo"]) or preset["tempo"]
    fragments.append(tempo)
    fragments.append(preset["rhythm"])
    fragments += preset["production"]

    if brief["vocal"] == "instrumental":
        # No vocal carries the melody, so name the lead instrument explicitly.
        lead = preset["instruments"][0] if preset["instruments"] else "piano"
        fragments.append(f"lead melody on {lead}")

    return sanitize_style(fragments)


def assemble_style_text(fragments: list[str]) -> str:
    return ", ".join(fragments)


# --------------------------------------------------------------------------- #
# Output bundle
# --------------------------------------------------------------------------- #
def build_json_document(
    brief: dict[str, Any],
    analysis: dict[str, Any],
    style: str,
    title: str,
) -> dict[str, Any]:
    """The YuE2 document, matching the official ``examples/*.json`` field set."""
    seed = brief["seed"]
    if seed < 0:
        # Let YuE2 pick its own seed rather than pinning an arbitrary one.
        seed = -1
    return {
        "title": title or "Untitled",
        "style": style,
        "lyrics": analysis.get("normalized", "").rstrip(),
        "cot": brief["cot"],
        "seed": seed,
    }


def build_python_snippet(document: dict[str, Any], vae: str) -> str:
    """A runnable ``YuE2Pipeline`` example that reads the JSON above."""
    _ = document  # the snippet loads the JSON at runtime; kept for signature symmetry
    return f'''import json
from pathlib import Path

from yue2 import YuE2Pipeline

prompt = json.loads(Path("yue2_prompt.json").read_text(encoding="utf-8"))

pipe = YuE2Pipeline.from_pretrained(
    "m-a-p/YuE2-3B",
    device="cuda",
    vae="{vae}",
)
song = pipe(
    style=prompt["style"],
    lyrics=prompt["lyrics"],
    cot=prompt["cot"],
    seed=prompt["seed"],
    cfg_scale=1.2,
)
song.save("song.flac")
pipe.close()
'''


def build_bundle(
    brief: dict[str, Any],
    analysis: dict[str, Any],
    *,
    fragments: list[str],
    title: str,
    notes: str = "",
    arrangement: str = "",
    source: str = "fallback",
    provider_note: str = "",
) -> dict[str, Any]:
    """Assemble the six workspace outputs from a resolved style list."""
    style = assemble_style_text(fragments)
    document = build_json_document(brief, analysis, style, title)
    return {
        "style": style,
        "style_fragments": fragments,
        "fragment_count": len(fragments),
        "normalized_lyrics": analysis.get("normalized", "").rstrip(),
        "annotated_lyrics": analysis.get("annotated", "").rstrip(),
        "vocal_arrangement": arrangement or analysis.get("vocal_arrangement", ""),
        "json": json.dumps(document, ensure_ascii=False, indent=2),
        "document": document,
        "python_snippet": build_python_snippet(document, brief["vae"]),
        "notes": notes,
        "source": source,
        "provider_note": provider_note,
        "analysis": analysis,
    }


def local_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic output with no provider call. Never fails."""
    brief = normalize_brief(payload)
    analysis = analyze_for(brief)
    fragments = fallback_style_fragments(brief, analysis)
    title = brief.get("title") or _title_from_idea(brief.get("idea")) or "Untitled"
    return build_bundle(
        brief,
        analysis,
        fragments=fragments,
        title=title,
        notes="本地预览：未调用写作模型，提示词由内置曲风库拼装。",
        source="local_preview",
    )


def _title_from_idea(idea: str) -> str:
    text = (idea or "").strip().replace("\n", " ")
    return text[:24] if text else ""


def analyze_for(brief: dict[str, Any]) -> dict[str, Any]:
    """Run the deterministic engine for a normalized brief."""
    from .lyrics import analyze_payload

    return analyze_payload(brief.get("lyrics", ""), brief)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def run_generate(payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Generate a style bundle with the configured provider.

    A provider failure never raises out of here: the deterministic fallback is
    returned alongside the reason, because a failed model call should still leave
    the user with something pasteable. Validation errors do raise, since those
    are programming mistakes rather than runtime conditions.
    """
    brief = normalize_brief(payload)
    analysis = analyze_for(brief)

    system_prompt, user_prompt = build_style_request(brief, analysis)
    kind = str(settings.get("kind") or "local")
    backend = BACKENDS.get(kind)
    if backend is None:
        raise AssemblyError(f"Unknown provider kind: {kind!r}.")

    try:
        reply = backend.generate(settings, system_prompt, user_prompt)
    except ModelError as error:
        fragments = fallback_style_fragments(brief, analysis)
        bundle = build_bundle(
            brief,
            analysis,
            fragments=fragments,
            title=brief.get("title") or _title_from_idea(brief.get("idea")) or "Untitled",
            notes="模型调用失败，已改用内置曲风库生成提示词。",
            source="fallback",
            provider_note=f"{error.code}: {error.message}",
        )
        bundle["error"] = error.as_dict()
        return bundle

    decoded = parse_json_reply(reply)
    fragments = sanitize_style(decoded.get("style"))
    if len(fragments) < MIN_STYLE_FRAGMENTS:
        # Too thin to be useful: keep what the model gave us and append the
        # catalog's baseline so the prompt is still complete.
        baseline = fallback_style_fragments(brief, analysis)
        merged = fragments + [item for item in baseline if item.lower() not in {f.lower() for f in fragments}]
        fragments = sanitize_style(merged)

    title = str(decoded.get("title") or brief.get("title") or _title_from_idea(brief.get("idea")) or "Untitled")
    return build_bundle(
        brief,
        analysis,
        fragments=fragments,
        title=title,
        notes=str(decoded.get("notes") or ""),
        arrangement=str(decoded.get("vocal_arrangement") or ""),
        source=f"model:{kind}",
    )


def run_lyrics_generate(payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Write or revise a lyric sheet from an idea. Raises on failure.

    Unlike style generation there is no meaningful deterministic fallback for
    writing lyrics, so the error propagates and the UI explains it.
    """
    brief = normalize_brief(payload)
    system_prompt, user_prompt = build_lyrics_request(brief)

    kind = str(settings.get("kind") or "local")
    backend = BACKENDS.get(kind)
    if backend is None:
        raise AssemblyError(f"Unknown provider kind: {kind!r}.")

    reply = backend.generate(settings, system_prompt, user_prompt)
    decoded = parse_json_reply(reply)

    lyrics = str(decoded.get("lyrics") or "").strip()
    if not lyrics:
        raise ModelError(
            "EMPTY_REPLY",
            "模型没有返回歌词内容。请重试，或把 max_tokens 调大。",
        )

    analysis = analyze_payload_for(lyrics, brief)
    return {
        "title": str(decoded.get("title") or brief.get("title") or "").strip(),
        "raw_lyrics": lyrics,
        "normalized_lyrics": analysis.get("normalized", "").rstrip(),
        "analysis": analysis,
        "quality_notes": analysis.get("quality_notes", []),
        "source": f"model:{kind}",
    }


def analyze_payload_for(lyrics: str, brief: dict[str, Any]) -> dict[str, Any]:
    from .lyrics import analyze_payload

    return analyze_payload(lyrics, brief)


__all__ = [
    "AssemblyError",
    "MAX_STYLE_FRAGMENTS",
    "analyze_for",
    "assemble_style_text",
    "build_bundle",
    "build_json_document",
    "build_lyrics_request",
    "build_python_snippet",
    "build_style_request",
    "fallback_style_fragments",
    "local_preview",
    "normalize_brief",
    "parse_json_reply",
    "run_generate",
    "run_lyrics_generate",
    "sanitize_style",
]
