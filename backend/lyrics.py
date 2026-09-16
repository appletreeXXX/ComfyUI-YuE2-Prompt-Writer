"""Deterministic lyric engine: parse, normalize, detect language, assign voices.

Everything here is a pure function over strings. No I/O, no network, no model.
That matters for two reasons:

* The workspace re-runs this on every keystroke, so it must be instant.
* The normalized sheet it produces is the one handed to YuE2, so the rules have
  to be inspectable and testable rather than hidden inside a model call.

Section numbering follows the official YuE2 examples: repeated sections keep a
bare header, and only sections of the same kind whose *content differs* get
numbered. So a chorus sung three times stays ``[Chorus]``, while two different
verses become ``[Verse 1]`` and ``[Verse 2]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# --------------------------------------------------------------------------- #
# Section headers
# --------------------------------------------------------------------------- #
# Canonical tags, in the order the guide recommends using them.
SECTION_TAGS = (
    "Intro",
    "Verse",
    "Pre-Chorus",
    "Chorus",
    "Post-Chorus",
    "Bridge",
    "Rap",
    "Instrumental",
    "Interlude",
    "Breakdown",
    "Outro",
)

# Bilingual aliases plus the shapes models actually emit. Matching is
# case-insensitive and ignores surrounding brackets/spaces.
_HEADER_ALIASES: dict[str, str] = {
    # English canonical spellings and common drift
    "intro": "Intro",
    "verse": "Verse",
    "prechorus": "Pre-Chorus",
    "pre-chorus": "Pre-Chorus",
    "pre chorus": "Pre-Chorus",
    "chorus": "Chorus",
    "postchorus": "Post-Chorus",
    "post-chorus": "Post-Chorus",
    "post chorus": "Post-Chorus",
    "hook": "Chorus",
    "refrain": "Chorus",
    "bridge": "Bridge",
    "middle8": "Bridge",
    "middle 8": "Bridge",
    "rap": "Rap",
    "instrumental": "Instrumental",
    "solo": "Instrumental",
    "interlude": "Interlude",
    "break": "Breakdown",
    "breakdown": "Breakdown",
    "outro": "Outro",
    "ending": "Outro",
    "coda": "Outro",
    # Chinese aliases
    "前奏": "Intro",
    "序曲": "Intro",
    "主歌": "Verse",
    "副歌前": "Pre-Chorus",
    "预副歌": "Pre-Chorus",
    "导歌": "Pre-Chorus",
    "副歌": "Chorus",
    "高潮": "Chorus",
    "叠句": "Chorus",
    "桥段": "Bridge",
    "过渡": "Bridge",
    "说唱": "Rap",
    "饶舌": "Rap",
    "间奏": "Interlude",
    "纯音乐": "Instrumental",
    "器乐": "Instrumental",
    "尾奏": "Outro",
    "结束": "Outro",
}

# ``[Verse 1]``, ``【副歌】``, ``(Chorus)``, ``Verse 2:`` — capture the tag and an
# optional trailing index.
_HEADER_PATTERN = re.compile(
    r"^\s*[\[\(【]?\s*"
    r"(?P<tag>[A-Za-z][A-Za-z0-9 '\-]*?|[\u4e00-\u9fff]{1,4})"
    r"\s*(?:(?P<index>\d{1,2}))?"
    r"\s*[\]\)】]?\s*[:：]?\s*$"
)


def _canonical_tag(raw: str) -> str | None:
    key = raw.strip().lower().replace("_", " ").strip()
    if key in _HEADER_ALIASES:
        return _HEADER_ALIASES[key]
    collapsed = re.sub(r"[\s\-]+", "", key)
    return _HEADER_ALIASES.get(collapsed)


def parse_section_header(line: str) -> tuple[str, int | None] | None:
    """Return ``(canonical_tag, index)`` when *line* is a section header."""
    stripped = line.strip()
    if not stripped:
        return None
    # A header never carries lyric content, so keep it short.
    if len(stripped) > 32:
        return None
    match = _HEADER_PATTERN.match(stripped)
    if match is None:
        return None
    tag = _canonical_tag(match.group("tag"))
    if tag is None:
        return None
    index_text = match.group("index")
    return tag, int(index_text) if index_text else None


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
@dataclass
class Section:
    tag: str
    lines: list[str] = field(default_factory=list)
    source_index: int | None = None
    number: int | None = None

    @property
    def body(self) -> str:
        return "\n".join(self.lines)

    def header(self) -> str:
        return f"[{self.tag} {self.number}]" if self.number else f"[{self.tag}]"


@dataclass
class LyricSheet:
    sections: list[Section]
    language: str
    language_confidence: str
    requested_language: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def singable_lines(self) -> int:
        return sum(len(section.lines) for section in self.sections)

    def normalized(self) -> str:
        blocks = []
        for section in self.sections:
            body = "\n".join(section.lines)
            blocks.append(f"{section.header()}\n{body}" if body else section.header())
        return "\n\n".join(blocks).strip() + "\n"

    def annotated(self, vocal_id: str) -> str:
        """Sheet with per-section voice labels, for duet review only."""
        if vocal_id not in {"duet", "male", "female"}:
            return ""
        blocks = []
        for position, section in enumerate(self.sections):
            voice = _section_voice(section, position, vocal_id)
            if not voice:
                blocks.append(f"{section.header()}\n{section.body}")
                continue
            blocks.append(f"{section.header()} · {voice}\n{section.body}")
        return "\n\n".join(blocks).strip() + "\n"


def _section_voice(section: Section, position: int, vocal_id: str) -> str | None:
    """Which voice sings a section. Duets alternate verses and share choruses."""
    if vocal_id == "instrumental" or section.tag in {"Intro", "Instrumental", "Interlude", "Outro"}:
        return None
    if vocal_id == "male":
        return "Male"
    if vocal_id == "female":
        return "Female"
    # Duet: alternate leads across verses, sing choruses together.
    if section.tag == "Verse":
        return "Male" if position % 2 == 0 else "Female"
    if section.tag in {"Chorus", "Post-Chorus"}:
        return "Both"
    if section.tag == "Pre-Chorus":
        return "Both"
    if section.tag == "Rap":
        return "Lead"
    return None


def parse_lyrics(text: str) -> list[Section]:
    """Split a lyric sheet into sections, honouring explicit headers.

    When no headers are present, sections are inferred from blank lines. A block
    that repeats an earlier block verbatim is treated as a chorus; otherwise the
    first block is an Intro only when it looks like one, and the rest are verses.
    """
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections: list[Section] = []
    current: Section | None = None
    pending: list[str] = []

    def flush_pending() -> None:
        """Attach buffered header-less lines to the preceding section."""
        nonlocal pending
        if pending:
            if current is not None:
                current.lines.extend(pending)
            pending = []

    for line in raw_lines:
        header = parse_section_header(line)
        if header is not None:
            flush_pending()
            tag, index = header
            current = Section(tag=tag, source_index=index)
            sections.append(current)
            continue
        if not line.strip():
            if current is not None and current.lines and current.lines[-1] != "":
                current.lines.append("")
            continue
        if current is None:
            pending.append(line.rstrip())
        else:
            current.lines.append(line.rstrip())
    flush_pending()

    if not sections:
        sections = _infer_sections(raw_lines)

    for section in sections:
        while section.lines and not section.lines[-1]:
            section.lines.pop()

    sections = [section for section in sections if section.lines or section.tag in {"Intro", "Instrumental", "Outro"}]
    return sections


def _infer_sections(raw_lines: list[str]) -> list[Section]:
    blocks: list[list[str]] = []
    buffer: list[str] = []
    for line in raw_lines:
        if line.strip():
            buffer.append(line.rstrip())
        elif buffer:
            blocks.append(buffer)
            buffer = []
    if buffer:
        blocks.append(buffer)
    if not blocks:
        return []

    seen: list[str] = []
    sections: list[Section] = []
    for index, block in enumerate(blocks):
        key = "\n".join(line.strip() for line in block)
        if key in seen:
            tag = "Chorus"
        elif index == 0 and len(blocks) > 2:
            tag = "Verse"
        else:
            tag = "Verse"
        if key not in seen:
            seen.append(key)
        sections.append(Section(tag=tag, lines=block))
    return sections


# --------------------------------------------------------------------------- #
# Section numbering
# --------------------------------------------------------------------------- #
def number_sections(sections: list[Section]) -> None:
    """Apply official numbering: number by content, not by occurrence.

    Same-kind sections get indices only when their content actually differs.
    Identical repeats therefore stay bare, which is what YuE2's own examples
    look like.
    """
    by_tag: dict[str, list[Section]] = {}
    for section in sections:
        by_tag.setdefault(section.tag, []).append(section)

    for _tag, group in by_tag.items():
        fingerprints = {_fingerprint(section) for section in group}
        if len(fingerprints) <= 1:
            for section in group:
                section.number = None
            continue
        assigned: dict[str, int] = {}
        for section in group:
            key = _fingerprint(section)
            if key not in assigned:
                assigned[key] = len(assigned) + 1
            section.number = assigned[key]

    # Honour an explicit index from the source when the group is numbered anyway,
    # because the author's own ordering is more trustworthy than ours.
    for section in sections:
        if section.number is not None and section.source_index is not None:
            section.number = section.source_index


def _fingerprint(section: Section) -> str:
    return re.sub(r"\s+", "", section.body).lower()


# --------------------------------------------------------------------------- #
# Language detection
# --------------------------------------------------------------------------- #
_CANTONESE_MARKERS = set("嘅咗喺唔冇乜嘢睇啲畀佢哋嚟呢咪嘞囉咁")
_JAPANESE_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> tuple[str, str]:
    """Return ``(language, confidence)`` for a lyric sheet.

    Heuristic by design, and documented as such: traditional Chinese is reported
    as Mandarin (the user can override), Cantonese relies on characteristic
    particles, and short samples are marked low-confidence.
    """
    hangul = len(_HANGUL.findall(text))
    kana = len(_JAPANESE_KANA.findall(text))
    cjk = len(_CJK.findall(text))
    latin = len(_LATIN.findall(text))
    total = hangul + kana + cjk + latin
    if total == 0:
        return "unknown", "low"

    if hangul / total > 0.15:
        return "Korean", "high" if hangul / total > 0.5 else "medium"
    if kana / total > 0.05:
        return "Japanese", "high" if kana / total > 0.2 else "medium"

    if cjk > 0:
        cantonese_hits = sum(1 for char in text if char in _CANTONESE_MARKERS)
        ratio = cantonese_hits / cjk
        if ratio >= 0.02 and cjk >= 20:
            return "Cantonese", "medium"
        confidence = "high" if cjk >= 40 else "medium" if cjk >= 12 else "low"
        return "Mandarin", confidence

    if latin > 0:
        confidence = "high" if latin >= 120 else "medium" if latin >= 40 else "low"
        return "English", confidence

    return "unknown", "low"


def language_matches(requested: str | None, detected: str) -> bool:
    if not requested:
        return True
    return requested.strip().lower() == detected.strip().lower()


# --------------------------------------------------------------------------- #
# Duration estimate
# --------------------------------------------------------------------------- #
_SECONDS_PER_LINE = 3.4
_AVERAGE_CJK_CHARS_PER_SECOND = 3.2


def estimate_duration(sections: list[Section], language: str) -> dict[str, Any]:
    """Rough duration from line count and character density.

    Section-level rather than sample-accurate: YuE2 chops long lyrics, and the
    workspace only needs to warn when a sheet will not fit.
    """
    total_lines = 0
    total_chars = 0
    sung_sections = 0
    for section in sections:
        if section.tag in {"Intro", "Instrumental", "Interlude", "Outro"}:
            total_lines += 1
            continue
        sung_sections += 1
        total_lines += len(section.lines)
        total_chars += sum(len(line) for line in section.lines)

    if language in {"Mandarin", "Cantonese", "Japanese", "Korean"} and total_chars:
        seconds = total_chars / _AVERAGE_CJK_CHARS_PER_SECOND
    else:
        seconds = total_lines * _SECONDS_PER_LINE
    seconds = max(20.0, seconds)
    return {
        "seconds": round(seconds),
        "minutes": round(seconds / 60.0, 1),
        "lines": total_lines,
        "sung_sections": sung_sections,
        "label": f"约 {round(seconds / 60.0, 1)} 分钟",
    }


# --------------------------------------------------------------------------- #
# Vocal arrangement guidance
# --------------------------------------------------------------------------- #
def vocal_arrangement(sections: list[Section], vocal_id: str) -> str:
    if vocal_id == "instrumental":
        return "纯器乐：无人生演唱，旋律由主奏乐器承担。"
    lines: list[str] = []
    if vocal_id in {"male", "female"}:
        label = "男声" if vocal_id == "male" else "女声"
        lines.append(f"全曲由{label}主唱。")
        for section in sections:
            if section.tag in {"Intro", "Instrumental", "Interlude", "Outro"}:
                lines.append(f"{section.header()}：纯器乐。")
        return "\n".join(lines)

    lines.append("男女混唱：主歌由两位歌手交替领唱，副歌齐唱。")
    for position, section in enumerate(sections):
        voice = _section_voice(section, position, vocal_id)
        if section.tag in {"Intro", "Instrumental", "Interlude", "Outro"}:
            lines.append(f"{section.header()}：纯器乐。")
        elif voice == "Both":
            lines.append(f"{section.header()}：齐唱。")
        elif voice:
            lines.append(f"{section.header()}：{voice} 领唱。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Quality notes
# --------------------------------------------------------------------------- #
def quality_notes(
    sheet: LyricSheet,
    *,
    requested_language: str | None = None,
    vocal_id: str = "female",
    length_intent: str = "standard",
) -> list[str]:
    """Non-blocking advisories shown under the lyric box."""
    notes: list[str] = []
    tags = [section.tag for section in sheet.sections]

    chorus_count = tags.count("Chorus")
    if chorus_count == 0:
        notes.append("没有识别到副歌段落，YuE2 依赖重复副歌来判定歌曲结构。")
    elif chorus_count == 1:
        notes.append("副歌只出现了一次，建议重复 2–3 次以便 YuE2 识别结构。")

    if "Verse" not in tags:
        notes.append("没有主歌段落。")

    line_count = sheet.singable_lines
    expected = {"short": (4, 16), "standard": (12, 32), "long": (20, 48)}.get(length_intent)
    if expected and not (expected[0] <= line_count <= expected[1]):
        if line_count < expected[0]:
            notes.append(f"可唱行数偏少（{line_count} 行），{length_intent} 篇幅建议 {expected[0]}–{expected[1]} 行。")
        else:
            notes.append(f"可唱行数偏多（{line_count} 行），过长歌词可能被 YuE2 截断。")

    if requested_language and not language_matches(requested_language, sheet.language):
        notes.append(f"你要求的是 {requested_language}，但检测到更像 {sheet.language}。")

    if vocal_id == "instrumental" and sheet.singable_lines > 0:
        notes.append("已选纯器乐，但歌词框中仍有内容，YuE2 可能仍会尝试演唱。")

    return notes


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def analyze(
    text: str,
    *,
    requested_language: str | None = None,
    vocal_id: str = "female",
    length_intent: str = "standard",
) -> LyricSheet:
    """Parse, normalize, detect and annotate a lyric sheet in one call."""
    sections = parse_lyrics(text)
    number_sections(sections)
    detected, confidence = detect_language(text)

    sheet = LyricSheet(
        sections=sections,
        language=detected,
        language_confidence=confidence,
        requested_language=requested_language,
    )
    sheet.warnings = quality_notes(
        sheet,
        requested_language=requested_language,
        vocal_id=vocal_id,
        length_intent=length_intent,
    )
    return sheet


def analyze_payload(text: str, brief: dict[str, Any] | None = None) -> dict[str, Any]:
    """Workspace-shaped analysis result."""
    brief = brief or {}
    # ``auto`` is a UI sentinel meaning "no preference", not a language name.
    # Leaving it as a string made quality notes read "you asked for auto".
    requested_language = brief.get("language")
    if not requested_language or str(requested_language).strip().lower() == "auto":
        requested_language = None
    sheet = analyze(
        text,
        requested_language=requested_language,
        vocal_id=brief.get("vocal", "female"),
        length_intent=brief.get("lyric_length", "standard"),
    )
    return {
        "normalized": sheet.normalized(),
        "annotated": sheet.annotated(brief.get("vocal", "female")),
        "language": sheet.language,
        "language_confidence": sheet.language_confidence,
        "sections": [
            {
                "tag": section.tag,
                "header": section.header(),
                "number": section.number,
                "lines": len(section.lines),
            }
            for section in sheet.sections
        ],
        "vocal_arrangement": vocal_arrangement(sheet.sections, brief.get("vocal", "female")),
        "duration": estimate_duration(sheet.sections, sheet.language),
        "quality_notes": sheet.warnings,
        "singable_lines": sheet.singable_lines,
        "structure": " - ".join(dict.fromkeys(section.header() for section in sheet.sections)),
    }


__all__ = [
    "LyricSheet",
    "SECTION_TAGS",
    "Section",
    "analyze",
    "analyze_payload",
    "detect_language",
    "estimate_duration",
    "language_matches",
    "number_sections",
    "parse_lyrics",
    "parse_section_header",
    "quality_notes",
    "vocal_arrangement",
]
