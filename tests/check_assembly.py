"""Verify assembly: brief validation, style sanitisation, parsing, fallback.

The sanitisation tests matter most: leaked Chinese lyric fragments and
sentence-shaped entries in a style prompt are the documented failure mode this
plugin exists to prevent.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import assembly  # noqa: E402
from backend.assembly import AssemblyError, local_preview, normalize_brief, parse_json_reply, sanitize_style  # noqa: E402
from backend.models.contract import ModelError, validate_settings  # noqa: E402

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")
        print(f"  FAIL {label}: expected {expected!r}, got {actual!r}")
    else:
        print(f"  ok   {label}")


print("== brief validation ==")
# The workspace default payload. mood/tempo/language all default to "auto".
DEFAULT_PAYLOAD = {
    "genre": "citypop",
    "vocal": "female",
    "lyrics": "",
    "idea": "",
    "mood": "auto",
    "tempo": "auto",
    "structure": "auto",
    "language": "auto",
    "cot": "full",
    "vae": "YuE2-Vae",
    "lyric_length": "standard",
    "seed": -1,
}

try:
    brief = normalize_brief(DEFAULT_PAYLOAD)
    print("  ok   default payload accepted (auto mood/tempo/language)")
except AssemblyError as error:
    failures.append(f"default payload rejected: {error.message}")
    print(f"  FAIL default payload rejected: {error.message}")
    brief = None

print("\n== auto is valid for every 'auto' control ==")
for key in ("mood", "tempo", "structure", "language"):
    try:
        normalize_brief({**DEFAULT_PAYLOAD, key: "auto"})
        print(f"  ok   {key}=auto accepted")
    except AssemblyError as error:
        failures.append(f"{key}=auto rejected: {error.message}")
        print(f"  FAIL {key}=auto rejected")

print("\n== unknown values are rejected ==")
for key, bad in (("mood", "angry"), ("tempo", "hyper"), ("language", "klingon"), ("cot", "sometimes")):
    try:
        normalize_brief({**DEFAULT_PAYLOAD, key: bad})
        failures.append(f"{key}={bad} was accepted, expected rejection")
        print(f"  FAIL {key}={bad} was accepted")
    except AssemblyError:
        print(f"  ok   {key}={bad} rejected")

print("\n== style sanitisation ==")
check(
    "splits on commas",
    sanitize_style("City Pop, upbeat, groovy bass"),
    ["City Pop", "upbeat", "groovy bass"],
)
check(
    "strips code fences",
    sanitize_style("```json\nCity Pop, upbeat\n```"),
    ["City Pop", "upbeat"],
)
check(
    "drops leaked CJK fragments",
    sanitize_style("City Pop, 我在夜里唱着这首歌, upbeat"),
    ["City Pop", "upbeat"],
)
check(
    "drops sentence-shaped fragments",
    sanitize_style("City Pop, this is a very long descriptive sentence about the song, upbeat"),
    ["City Pop", "upbeat"],
)
check(
    "deduplicates case-insensitively",
    sanitize_style("upbeat, Upbeat, UPBEAT"),
    ["upbeat"],
)
check(
    "trims trailing periods",
    sanitize_style("City Pop., upbeat."),
    ["City Pop", "upbeat"],
)
check(
    "splits on newlines too",
    sanitize_style("City Pop\nupbeat\nsynth"),
    ["City Pop", "upbeat", "synth"],
)
long_list = ", ".join(f"tag{index}" for index in range(40))
check("caps at the fragment budget", len(sanitize_style(long_list)), 20)
check("empty input yields no fragments", sanitize_style("   "), [])
check("non-string input does not crash", sanitize_style(None), [])
check("list input is joined", sanitize_style(["City Pop", "upbeat"]), ["City Pop", "upbeat"])

print("\n== JSON reply parsing ==")
check(
    "plain json",
    parse_json_reply('{"style": "a, b"}')["style"],
    "a, b",
)
check(
    "fenced json",
    parse_json_reply('```json\n{"style": "a, b"}\n```')["style"],
    "a, b",
)
check(
    "json embedded in prose",
    parse_json_reply('Sure! Here it is:\n{"style": "a, b"}\nHope that helps.')["style"],
    "a, b",
)
check(
    "reasoning field is dropped",
    "thinking" in parse_json_reply('{"thinking": "hmm", "style": "a, b"}'),
    False,
)
check(
    "raw newlines inside a string are salvaged",
    "line2" in parse_json_reply('{"lyrics": "line1\nline2"}')["lyrics"],
    True,
)

print("\n== reasoning-only and empty replies are reported clearly ==")
for label, reply, code in (
    ("thinking only", '{"thinking": "I considered many things"}', "THINKING_ONLY"),
    ("not json", "I cannot help with that.", "REPLY_NOT_JSON"),
    ("empty", "   ", "EMPTY_REPLY"),
):
    try:
        parse_json_reply(reply)
        failures.append(f"{label}: expected ModelError {code}")
        print(f"  FAIL {label}: no error raised")
    except ModelError as error:
        check(f"{label} -> {code}", error.code, code)

print("\n== fallback style covers all six components ==")
payload = {
    **DEFAULT_PAYLOAD,
    "lyrics": "[Verse]\n霓虹在车窗外倒退\n收音机里旧歌低回\n\n[Chorus]\n就让我一直开着车\n开过这座睡着的城\n",
}
preview = local_preview(payload)
fragments = preview["style_fragments"]
style = preview["style"]
print(f"  style: {style}")
check("source is local_preview", preview["source"], "local_preview")
check("language tag present", "Mandarin" in fragments, True)
check("vocal tag present", any("female" in f for f in fragments), True)
check("fragment count in range", 8 <= len(fragments) <= 20, True)
check("no CJK in the style", not any(any("\u4e00" <= c <= "\u9fff" for c in f) for f in fragments), True)
check("style is a comma-joined string", style == ", ".join(fragments), True)

print("\n== instrumental tracks name a lead instrument ==")
inst = local_preview({**DEFAULT_PAYLOAD, "vocal": "instrumental"})
check("instrumental tag present", "instrumental" in inst["style_fragments"], True)
check("no lead vocal tag", any("lead vocal" in f for f in inst["style_fragments"]), False)
check("names a lead instrument", any(f.startswith("lead melody on") for f in inst["style_fragments"]), True)

print("\n== explicit language overrides detection ==")
english_lyrics = {**DEFAULT_PAYLOAD, "lyrics": "[Verse]\nI drive alone tonight\nUnder the city lights\n", "language": "auto"}
check("auto detects English", "English" in local_preview(english_lyrics)["style_fragments"], True)
forced = {**english_lyrics, "language": "cantonese"}
check("explicit request wins", "Cantonese" in local_preview(forced)["style_fragments"], True)

print("\n== six outputs are all present ==")
for key in ("style", "normalized_lyrics", "annotated_lyrics", "vocal_arrangement", "json", "python_snippet"):
    present = bool(str(preview.get(key) or "").strip())
    check(f"output {key} non-empty", present, True)

print("\n== the JSON document matches the official field set ==")
document = preview["document"]
check("document keys", sorted(document.keys()), ["cot", "lyrics", "seed", "style", "title"])
check("cot value is official", document["cot"] in ("full", "melody", "off"), True)
check("seed passthrough", document["seed"], -1)
check("document style matches", document["style"], preview["style"])
check("python snippet is runnable shape", "YuE2Pipeline" in preview["python_snippet"], True)
check("python snippet honours vae", 'vae="YuE2-Vae"' in preview["python_snippet"], True)

print("\n== long lyrics are compacted, not truncated mid-section ==")
huge = "\n\n".join(f"[Verse]\n" + "\n".join(f"第{index}句歌词内容写在这里" for index in range(30)) for _ in range(20))
assert len(huge) > assembly.MAX_LYRIC_CHARS_FOR_PROMPT, "test fixture must exceed the budget"
compacted = assembly._compact_lyrics(huge)
check("compaction reduces size", len(compacted) < len(huge), True)
check("compaction stays within budget", len(compacted) <= assembly.MAX_LYRIC_CHARS_FOR_PROMPT + 200, True)
check("compaction keeps section headers", "[Verse]" in compacted, True)

print("\n== a short sheet is left untouched ==")
short = "[Verse]\n一句\n两句\n\n[Chorus]\n三句\n四句\n"
check("short sheet passes through verbatim", assembly._compact_lyrics(short), short)

print("\n== provider settings validation ==")
try:
    settings = validate_settings({"kind": "local", "model": "a/qwen.gguf"})
    check("local needs no host", settings["kind"], "local")
    check("local defaults n_ctx", settings["n_ctx"], 8192)
except ModelError as error:
    failures.append(f"local settings rejected: {error.message}")
    print(f"  FAIL {error.message}")

for label, bad, code in (
    ("unknown kind", {"kind": "gemini"}, "INVALID_SETTINGS"),
    ("local without model", {"kind": "local", "model": ""}, "INVALID_SETTINGS"),
    ("openai without host", {"kind": "openai", "model": "gpt-4o-mini"}, "INVALID_SETTINGS"),
    ("n_ctx out of range", {"kind": "local", "model": "a.gguf", "n_ctx": 999999}, "INVALID_SETTINGS"),
    ("bad kv cache type", {"kind": "local", "model": "a.gguf", "kv_cache_type": "q2_k"}, "INVALID_SETTINGS"),
    ("temperature not a number", {"kind": "local", "model": "a.gguf", "temperature": "hot"}, "INVALID_SETTINGS"),
):
    try:
        validate_settings(bad)
        failures.append(f"{label}: expected {code}")
        print(f"  FAIL {label}: accepted")
    except ModelError as error:
        check(f"{label} -> {code}", error.code, code)

print("\n== openai host is normalised to a /v1 base ==")
check(
    "bare host gains scheme and /v1",
    validate_settings({"kind": "openai", "model": "m", "host": "127.0.0.1:1234"})["host"],
    "http://127.0.0.1:1234/v1",
)
check(
    "existing /v1 is kept",
    validate_settings({"kind": "openai", "model": "m", "host": "http://localhost:1234/v1"})["host"],
    "http://localhost:1234/v1",
)
check(
    "ollama default host",
    validate_settings({"kind": "ollama", "model": "qwen3:8b"})["host"],
    "http://127.0.0.1:11434",
)

print("\n== api keys never come back out ==")
from backend.models.contract import public_settings  # noqa: E402

exposed = public_settings(validate_settings({"kind": "openai", "model": "m", "host": "h", "api_key": "sk-secret"}))
check("key is blanked", exposed["api_key"], "")
check("presence flag set", exposed["has_api_key"], True)
check(
    "no secret in the serialised form",
    "sk-secret" in json.dumps(exposed),
    False,
)

print()
if failures:
    print(f"{len(failures)} FAILURE(S)")
    for failure in failures:
        print(" -", failure)
    sys.exit(1)
print("assembly checks passed")
