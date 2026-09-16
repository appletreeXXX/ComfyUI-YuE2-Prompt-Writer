"""Smoke test for the deterministic lyric engine. Run with any Python 3.10+."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.lyrics import (  # noqa: E402
    analyze,
    detect_language,
    estimate_duration,
    parse_lyrics,
    parse_section_header,
)

FAILURES = []


def check(label, actual, expected):
    if actual != expected:
        FAILURES.append(f"{label}: expected {expected!r}, got {actual!r}")
        print(f"  FAIL {label}: expected {expected!r}, got {actual!r}")
    else:
        print(f"  ok   {label}")


print("== header parsing ==")
check("bracket english", parse_section_header("[Verse 1]"), ("Verse", 1))
check("bracket chinese", parse_section_header("【副歌】"), ("Chorus", None))
check("paren alias", parse_section_header("(Chorus)"), ("Chorus", None))
check("bare with colon", parse_section_header("Pre-Chorus 2:"), ("Pre-Chorus", 2))
check("chinese 主歌", parse_section_header("[主歌 2]"), ("Verse", 2))
check("hook maps to chorus", parse_section_header("[Hook]"), ("Chorus", None))
check("not a header", parse_section_header("我在夜里唱着这首歌"), None)
check("long line not header", parse_section_header("Verse " + "a" * 40), None)

print("\n== repeated sections keep bare headers ==")
SHEET = """[Verse 1]
第一句歌词在这里
第二句歌词在这里

[Chorus]
副歌重复这一句
副歌再重复一次

[Verse 2]
另一段不同的词啊
再写一句不同的词

[Chorus]
副歌重复这一句
副歌再重复一次
"""
sections = parse_lyrics(SHEET)
from backend.lyrics import number_sections  # noqa: E402

number_sections(sections)
headers = [s.header() for s in sections]
check("headers", headers, ["[Verse 1]", "[Chorus]", "[Verse 2]", "[Chorus]"])

print("\n== inference without headers ==")
BARE = """第一段第一句
第一段第二句

副歌这一句
副歌再一句

第三段第一句
第三段第二句

副歌这一句
副歌再一句
"""
sections = parse_lyrics(BARE)
number_sections(sections)
check("inferred tags", [s.tag for s in sections], ["Verse", "Verse", "Verse", "Chorus"])

print("\n== language detection ==")
check("mandarin", detect_language("我在夜里唱着这首歌，想着你的样子")[0], "Mandarin")
check("english", detect_language("I sing this song at night and think of you")[0], "English")
check("japanese", detect_language("きみのことを歌うよ、夜の中で")[0], "Japanese")
check("korean", detect_language("나는 밤에 이 노래를 불러요")[0], "Korean")
check(
    "cantonese",
    detect_language("我哋今日去咗嗰度食飯，佢哋嘅嘢好食，唔知你哋有冇食過呢啲嘢呀")[0],
    "Cantonese",
)

print("\n== normalization ==")
sheet = analyze(SHEET, requested_language="Mandarin", vocal_id="duet")
check("language", sheet.language, "Mandarin")
check("singable lines", sheet.singable_lines, 8)
check("normalized ends with newline", sheet.normalized().endswith("\n"), True)
check("normalized keeps bare chorus", "[Chorus]" in sheet.normalized(), True)
check("no stray numbering", "[Chorus 1]" in sheet.normalized(), False)
check("duet annotated has Male", "Male" in sheet.annotated("duet"), True)
check("duet chorus is Both", "Both" in sheet.annotated("duet"), True)

print("\n== duration ==")
duration = estimate_duration(sheet.sections, sheet.language)
check("duration positive", duration["seconds"] > 0, True)
check("duration has label", "约" in duration["label"], True)

print("\n== quality notes ==")
single_chorus = analyze("[Verse]\n一句\n两句\n\n[Chorus]\n三句\n四句\n", vocal_id="female")
check("warns on single chorus", any("副歌" in n for n in single_chorus.warnings), True)
mismatch = analyze("我唱中文歌词啊\n再唱一句中文\n", requested_language="English")
check("warns on language mismatch", any("English" in n for n in mismatch.warnings), True)

print("\n== the 'auto' sentinel is not treated as a language ==")
from backend.lyrics import analyze_payload  # noqa: E402

auto_result = analyze_payload("[Verse]\n霓虹在车窗外倒退\n收音机里旧歌低回\n", {"language": "auto"})
check(
    "no 'auto' in the quality notes",
    any("auto" in note for note in auto_result["quality_notes"]),
    False,
)
check("detected language still reported", auto_result["language"], "Mandarin")
explicit = analyze_payload("[Verse]\n霓虹在车窗外倒退\n收音机里旧歌低回\n", {"language": "English"})
check(
    "an explicit request still warns on mismatch",
    any("English" in note for note in explicit["quality_notes"]),
    True,
)
check(
    "None language is the same as auto",
    any("auto" in note for note in analyze_payload("一句歌词在此\n", {"language": None})["quality_notes"]),
    False,
)

print("\n== empty input ==")
empty = analyze("")
check("empty sections", empty.sections, [])
check("empty normalized", empty.normalized(), "\n")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S)")
    for failure in FAILURES:
        print(" -", failure)
    sys.exit(1)
print("all lyric engine checks passed")
