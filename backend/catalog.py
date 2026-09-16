"""Genre, vocal, language and chain-of-thought catalogs for YuE2 style prompts.

Every style tag here is English, because YuE2's ``style`` parameter is trained on
English comma-separated descriptors. The Chinese labels are display strings for
the workspace UI only and are never sent to the model or written into a prompt.

The module is pure data plus lookup helpers: no I/O, no network, no ComfyUI
imports. That keeps it testable without a ComfyUI install and lets the
deterministic fallback writer work even when no model provider is configured.
"""

from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
# Genre presets
# --------------------------------------------------------------------------- #
# Each preset carries the dimensions the writing guide asks a model to cover, so
# the fallback writer can assemble a usable style prompt without a model:
#   tags        - the core style identifiers, always emitted first
#   instruments - arrangement-level instrument names
#   moods       - emotional colour
#   atmosphere  - spatial / scene-setting descriptors
#   tempo       - default groove feel (overridable by the tempo control)
#   rhythm      - rhythmic character
#   production  - mix and production hints
GENRE_PRESETS: dict[str, dict[str, Any]] = {
    "citypop": {
        "label_zh": "城市流行",
        "tags": ["City Pop", "upbeat", "danceable"],
        "instruments": ["groovy bass", "electric guitar", "synth", "Rhodes piano", "tight drums"],
        "moods": ["energetic", "joyful", "nostalgic"],
        "atmosphere": ["neon city night", "summer evening"],
        "tempo": "mid-tempo",
        "rhythm": "syncopated groove",
        "production": ["glossy 80s production", "wide stereo chorus"],
    },
    "jazzfunk": {
        "label_zh": "爵士放克",
        "tags": ["Jazz-funk", "warm", "groovy"],
        "instruments": ["Rhodes piano", "electric bass", "tight drums", "brass section", "clavinet"],
        "moods": ["warm", "sensual", "playful"],
        "atmosphere": ["smoky lounge", "late night"],
        "tempo": "mid-tempo",
        "rhythm": "funk sixteenth-note groove",
        "production": ["punchy rhythm section", "vintage warmth"],
    },
    "ballad": {
        "label_zh": "抒情慢歌",
        "tags": ["Ballad", "slow", "emotional"],
        "instruments": ["grand piano", "strings", "acoustic guitar", "soft drums"],
        "moods": ["tender", "melancholic", "hopeful"],
        "atmosphere": ["intimate", "rain outside"],
        "tempo": "slow",
        "rhythm": "sparse and rubato",
        "production": ["lush string reverb", "vocal forward"],
    },
    "rock": {
        "label_zh": "摇滚",
        "tags": ["Rock", "driving", "powerful"],
        "instruments": ["distorted electric guitar", "bass guitar", "live drums"],
        "moods": ["defiant", "passionate", "raw"],
        "atmosphere": ["sweaty club", "stadium"],
        "tempo": "fast",
        "rhythm": "straight backbeat",
        "production": ["wall of guitars", "aggressive compression"],
    },
    "pop": {
        "label_zh": "流行",
        "tags": ["Pop", "catchy", "bright"],
        "instruments": ["synth pads", "punchy kick", "claps", "electric guitar"],
        "moods": ["cheerful", "confident", "youthful"],
        "atmosphere": ["radio-ready", "sunlit"],
        "tempo": "up-tempo",
        "rhythm": "four-on-the-floor",
        "production": ["polished modern mix", "wide vocal doubles"],
    },
    "rnb": {
        "label_zh": "节奏布鲁斯",
        "tags": ["R&B", "smooth", "sensual"],
        "instruments": ["electric piano", "sub bass", "finger snaps", "muted guitar"],
        "moods": ["sultry", "tender", "confident"],
        "atmosphere": ["candlelit room", "late night drive"],
        "tempo": "slow",
        "rhythm": "laid-back swing",
        "production": ["airtight low end", "silky vocal chain"],
    },
    "hiphop": {
        "label_zh": "嘻哈",
        "tags": ["Hip-hop", "boom bap", "confident"],
        "instruments": ["sampled drums", "808 sub bass", "vinyl crackle", "turntable scratch"],
        "moods": ["gritty", "swaggering", "reflective"],
        "atmosphere": ["urban night", "street corner"],
        "tempo": "mid-tempo",
        "rhythm": "swung boom bap",
        "production": ["dusty sampled textures", "hard-hitting drums"],
    },
    "trap": {
        "label_zh": "陷阱说唱",
        "tags": ["Trap", "dark", "hard-hitting"],
        "instruments": ["808 bass", "rolling hi-hats", "dark synth", "sparse piano"],
        "moods": ["menacing", "cold", "hypnotic"],
        "atmosphere": ["midnight", "empty city"],
        "tempo": "mid-tempo",
        "rhythm": "triplet hi-hat rolls",
        "production": ["distorted 808", "wide reverb space"],
    },
    "edm": {
        "label_zh": "电子舞曲",
        "tags": ["EDM", "energetic", "euphoric"],
        "instruments": ["supersaw lead", "sidechained bass", "big kick", "risers"],
        "moods": ["ecstatic", "uplifting", "intense"],
        "atmosphere": ["festival main stage", "laser lights"],
        "tempo": "fast",
        "rhythm": "four-on-the-floor",
        "production": ["huge drop", "stereo-wide supersaw"],
    },
    "housemusic": {
        "label_zh": "浩室",
        "tags": ["House", "groovy", "hypnotic"],
        "instruments": ["four-on-the-floor kick", "deep bassline", "chord stabs", "shakers"],
        "moods": ["sleek", "sensual", "relentless"],
        "atmosphere": ["warehouse party", "afterhours"],
        "tempo": "mid-tempo",
        "rhythm": "steady four-on-the-floor",
        "production": ["warm analog compression", "long filters"],
    },
    "lofi": {
        "label_zh": "低保真",
        "tags": ["Lo-fi", "chill", "mellow"],
        "instruments": ["muted piano", "soft brushed drums", "warm bass", "vinyl noise"],
        "moods": ["calm", "wistful", "cosy"],
        "atmosphere": ["study room", "rainy afternoon"],
        "tempo": "slow",
        "rhythm": "loose swung beat",
        "production": ["tape saturation", "bit-crushed samples"],
    },
    "folk": {
        "label_zh": "民谣",
        "tags": ["Folk", "acoustic", "sincere"],
        "instruments": ["fingerpicked acoustic guitar", "harmonica", "upright bass", "light percussion"],
        "moods": ["gentle", "nostalgic", "honest"],
        "atmosphere": ["campfire", "country road"],
        "tempo": "mid-tempo",
        "rhythm": "rolling fingerpicked pattern",
        "production": ["dry natural room", "minimal overdubs"],
    },
    "country": {
        "label_zh": "乡村",
        "tags": ["Country", "warm", "storytelling"],
        "instruments": ["acoustic guitar", "pedal steel", "fiddle", "walking bass"],
        "moods": ["heartfelt", "rootsy", "optimistic"],
        "atmosphere": ["open prairie", "front porch"],
        "tempo": "mid-tempo",
        "rhythm": "two-step shuffle",
        "production": ["crisp acoustic separation", "bright vocal"],
    },
    "folkrock": {
        "label_zh": "民谣摇滚",
        "tags": ["Folk rock", "driving", "earnest"],
        "instruments": ["jangly electric guitar", "acoustic guitar", "bass", "live drums"],
        "moods": ["earnest", "restless", "hopeful"],
        "atmosphere": ["highway at dusk", "small town"],
        "tempo": "up-tempo",
        "rhythm": "straight rock beat",
        "production": ["live band feel", "natural dynamics"],
    },
    "indiepop": {
        "label_zh": "独立流行",
        "tags": ["Indie pop", "dreamy", "quirky"],
        "instruments": ["chorus-soaked guitar", "vintage synth", "tambourine", "melodic bass"],
        "moods": ["dreamy", "bittersweet", "playful"],
        "atmosphere": ["sunlit bedroom", "seaside town"],
        "tempo": "mid-tempo",
        "rhythm": "gentle driving beat",
        "production": ["lo-fi charm", "heavy reverb guitars"],
    },
    "synthwave": {
        "label_zh": "合成器浪潮",
        "tags": ["Synthwave", "retro", "neon"],
        "instruments": ["analog synth bass", "gated reverb drums", "arpeggiated pads", "electric guitar"],
        "moods": ["nostalgic", "cinematic", "melancholic"],
        "atmosphere": ["neon highway", "retro future"],
        "tempo": "mid-tempo",
        "rhythm": "driving eighth-note pulse",
        "production": ["gated reverb", "saturated tape", "wide chorus"],
    },
    "ambient": {
        "label_zh": "氛围",
        "tags": ["Ambient", "slow", "textural"],
        "instruments": ["evolving synth pads", "field recordings", "bowed strings", "soft piano"],
        "moods": ["serene", "contemplative", "vast"],
        "atmosphere": ["glacial landscape", "weightless space"],
        "tempo": "slow",
        "rhythm": "free-floating without a beat",
        "production": ["long reverb tails", "gradual sonic evolution"],
    },
    "classical": {
        "label_zh": "古典",
        "tags": ["Classical", "orchestral", "expressive"],
        "instruments": ["string orchestra", "timpani", "woodwinds", "solo piano"],
        "moods": ["majestic", "dramatic", "tender"],
        "atmosphere": ["concert hall", "film score"],
        "tempo": "slow",
        "rhythm": "through-composed rubato",
        "production": ["natural hall reverb", "wide orchestral image"],
    },
    "jazz": {
        "label_zh": "爵士",
        "tags": ["Jazz", "swinging", "improvisational"],
        "instruments": ["upright bass", "brushed drums", "grand piano", "tenor saxophone"],
        "moods": ["sophisticated", "smoky", "relaxed"],
        "atmosphere": ["dim jazz club", "late night"],
        "tempo": "mid-tempo",
        "rhythm": "swung ride cymbal",
        "production": ["live room sound", "natural instrument separation"],
    },
    "blues": {
        "label_zh": "布鲁斯",
        "tags": ["Blues", "soulful", "gritty"],
        "instruments": ["slide guitar", "harmonica", "walking bass", "shuffled drums"],
        "moods": ["weary", "soulful", "resilient"],
        "atmosphere": ["juke joint", "delta crossroads"],
        "tempo": "mid-tempo",
        "rhythm": "shuffle groove",
        "production": ["raw amp tone", "room mic bleed"],
    },
    "soul": {
        "label_zh": "灵魂乐",
        "tags": ["Soul", "warm", "powerful"],
        "instruments": ["Hammond organ", "horns", "electric bass", "live drums"],
        "moods": ["passionate", "uplifting", "heartfelt"],
        "atmosphere": ["church hall", "revue stage"],
        "tempo": "mid-tempo",
        "rhythm": "driving gospel groove",
        "production": ["vintage console warmth", "bold horn stabs"],
    },
    "funk": {
        "label_zh": "放克",
        "tags": ["Funk", "tight", "syncopated"],
        "instruments": ["slap bass", "wah guitar", "clavinet", "tight drums", "horn hits"],
        "moods": ["playful", "confident", "kinetic"],
        "atmosphere": ["dancefloor", "get-down party"],
        "tempo": "fast",
        "rhythm": "sixteenth-note syncopation",
        "production": ["dry punchy mix", "deep pocket"],
    },
    "disco": {
        "label_zh": "迪斯科",
        "tags": ["Disco", "glittery", "relentless"],
        "instruments": ["disco strings", "four-on-the-floor kick", "funky guitar", "hi-hat accents"],
        "moods": ["celebratory", "seductive", "euphoric"],
        "atmosphere": ["mirrorball ballroom", "1979 dancefloor"],
        "tempo": "fast",
        "rhythm": "four-on-the-floor with open hi-hats",
        "production": ["lush string stabs", "wide stereo mix"],
    },
    "metal": {
        "label_zh": "金属",
        "tags": ["Metal", "heavy", "aggressive"],
        "instruments": ["down-tuned guitars", "double-kick drums", "distorted bass", "lead guitar"],
        "moods": ["furious", "epic", "dark"],
        "atmosphere": ["cavernous", "apocalyptic"],
        "tempo": "fast",
        "rhythm": "double-kick gallop",
        "production": ["scooped midrange guitars", "tight triggered drums"],
    },
    "punk": {
        "label_zh": "朋克",
        "tags": ["Punk", "fast", "raw"],
        "instruments": ["power-chord guitar", "driving bass", "fast drums"],
        "moods": ["rebellious", "urgent", "snotty"],
        "atmosphere": ["basement show", "sweaty basement"],
        "tempo": "fast",
        "rhythm": "breakneck straight beat",
        "production": ["raw unpolished", "everything clipping slightly"],
    },
    "reggae": {
        "label_zh": "雷鬼",
        "tags": ["Reggae", "laid-back", "warm"],
        "instruments": ["skanking guitar", "deep bass", "one-drop drums", "horns", "organ bubble"],
        "moods": ["relaxed", "spiritual", "sunny"],
        "atmosphere": ["beach sunset", "island breeze"],
        "tempo": "slow",
        "rhythm": "one-drop with skank",
        "production": ["deep dub reverb", "prominent bass"],
    },
    "latin": {
        "label_zh": "拉丁",
        "tags": ["Latin", "rhythmic", "passionate"],
        "instruments": ["nylon guitar", "congas", "trumpet", "piano montuno", "shakers"],
        "moods": ["passionate", "festive", "romantic"],
        "atmosphere": ["havana street", "hot summer night"],
        "tempo": "mid-tempo",
        "rhythm": "clave-based groove",
        "production": ["percussion forward", "bright horns"],
    },
    "bossanova": {
        "label_zh": "巴萨诺瓦",
        "tags": ["Bossa nova", "gentle", "intimate"],
        "instruments": ["nylon guitar", "soft brushed drums", "upright bass", "flute"],
        "moods": ["tender", "breezy", "wistful"],
        "atmosphere": ["beach cafe", "quiet evening"],
        "tempo": "slow",
        "rhythm": "bossa nova guitar pattern",
        "production": ["close-miked intimacy", "delicate dynamics"],
    },
    "kpop": {
        "label_zh": "韩式流行",
        "tags": ["K-pop", "polished", "dynamic"],
        "instruments": ["punchy synth", "trap-influenced drums", "bright piano", "vocal stacks"],
        "moods": ["confident", "playful", "intense"],
        "atmosphere": ["spotlight stage", "colourful studio"],
        "tempo": "up-tempo",
        "rhythm": "half-time chorus with trap hats",
        "production": ["maximalist arrangement", "punchy mix bus"],
    },
    "cpop": {
        "label_zh": "中文流行",
        "tags": ["Mandopop", "melodic", "sentimental"],
        "instruments": ["piano", "strings", "acoustic guitar", "programmed drums"],
        "moods": ["sentimental", "tender", "bittersweet"],
        "atmosphere": ["rainy city", "empty apartment"],
        "tempo": "mid-tempo",
        "rhythm": "steady pop backbeat",
        "production": ["vocal-forward mix", "lush strings"],
    },
    "cantopop": {
        "label_zh": "粤语流行",
        "tags": ["Cantopop", "melodic", "nostalgic"],
        "instruments": ["synth pads", "electric guitar", "strings", "programmed drums"],
        "moods": ["nostalgic", "melancholic", "hopeful"],
        "atmosphere": ["hong kong night", "neon harbour"],
        "tempo": "mid-tempo",
        "rhythm": "polished pop groove",
        "production": ["glossy 90s production", "wide reverb"],
    },
    "anime": {
        "label_zh": "动漫",
        "tags": ["Anime", "energetic", "theatrical"],
        "instruments": ["electric guitar", "orchestral strings", "driving drums", "synth lead"],
        "moods": ["passionate", "heroic", "bittersweet"],
        "atmosphere": ["opening sequence", "climactic battle"],
        "tempo": "fast",
        "rhythm": "driving rock beat with orchestral accents",
        "production": ["wall of sound", "soaring chorus"],
    },
    "gospel": {
        "label_zh": "福音",
        "tags": ["Gospel", "uplifting", "powerful"],
        "instruments": ["Hammond organ", "massed choir", "piano", "live drums"],
        "moods": ["jubilant", "devotional", "triumphant"],
        "atmosphere": ["church sanctuary", "choir loft"],
        "tempo": "mid-tempo",
        "rhythm": "shuffled gospel groove",
        "production": ["huge choir reverb", "dynamic builds"],
    },
    "dream": {
        "label_zh": "梦泡",
        "tags": ["Dream pop", "hazy", "ethereal"],
        "instruments": ["reverb-drenched guitar", "shimmering synth", "soft drums", "ethereal vocals"],
        "moods": ["hazy", "yearning", "serene"],
        "atmosphere": ["cloud layer", "weightless drift"],
        "tempo": "mid-tempo",
        "rhythm": "soft pulse buried in reverb",
        "production": ["lush reverb wash", "blurred transients"],
    },
    "acoustic": {
        "label_zh": "不插电",
        "tags": ["Acoustic", "intimate", "stripped-back"],
        "instruments": ["steel-string guitar", "light percussion", "upright bass"],
        "moods": ["sincere", "warm", "intimate"],
        "atmosphere": ["small room", "unplugged session"],
        "tempo": "slow",
        "rhythm": "gentle strummed pattern",
        "production": ["no overdubs", "breath and finger noise left in"],
    },
}

# The first preset is the workspace default.
DEFAULT_GENRE = "citypop"


# --------------------------------------------------------------------------- #
# Vocal settings
# --------------------------------------------------------------------------- #
VOCAL_SETTINGS: dict[str, dict[str, Any]] = {
    "male": {
        "label_zh": "男声",
        "style_tag": "male lead vocal",
        "guide_zh": "全曲男声主唱",
        "annotated": {"main": "Male", "duet": None, "backing": "Male backing"},
    },
    "female": {
        "label_zh": "女声",
        "style_tag": "female lead vocal",
        "guide_zh": "全曲女声主唱",
        "annotated": {"main": "Female", "duet": None, "backing": "Female backing"},
    },
    "duet": {
        "label_zh": "男女混唱",
        "style_tag": "male and female duet vocals",
        "guide_zh": "男女交替主歌、副歌齐唱",
        "annotated": {"main": "Duet", "duet": "Lead", "backing": "Both"},
    },
    "instrumental": {
        "label_zh": "纯器乐",
        "style_tag": "instrumental",
        "guide_zh": "无人生演唱，纯器乐演奏",
        "annotated": {"main": "Instrumental", "duet": None, "backing": None},
    },
}
DEFAULT_VOCAL = "female"


# --------------------------------------------------------------------------- #
# Mood / tempo / structure / language / cot controls
# --------------------------------------------------------------------------- #
# ``auto`` exists in every control (mood, tempo, language) because the workspace
# default payload sends it. Version 0.3.0 shipped a fix for exactly this: an
# earlier catalog omitted ``mood: "auto"`` and every request failed validation.
MOODS: dict[str, str | None] = {
    "auto": None,
    "happy": "happy",
    "sad": "sad",
    "energetic": "energetic",
    "calm": "calm",
    "romantic": "romantic",
    "dark": "dark",
    "nostalgic": "nostalgic",
    "hopeful": "hopeful",
    "melancholic": "melancholic",
    "defiant": "defiant",
    "dreamy": "dreamy",
}
DEFAULT_MOOD = "auto"

TEMPOS: dict[str, str | None] = {
    "auto": None,
    "slow": "slow",
    "mid-tempo": "mid-tempo",
    "up-tempo": "up-tempo",
    "fast": "fast",
}
DEFAULT_TEMPO = "auto"

# Coarse duration intents rather than exact BPM: YuE2 reads feel, not a number.
STRUCTURES: dict[str, str | None] = {
    "auto": None,
    "short": "short",
    "standard": "standard",
    "extended": "extended",
}
DEFAULT_STRUCTURE = "auto"
STRUCTURE_LABELS: dict[str, str] = {
    "short": "简短",
    "standard": "标准",
    "extended": "加长",
}

LANGUAGES: dict[str, str | None] = {
    "auto": None,
    "mandarin": "Mandarin",
    "cantonese": "Cantonese",
    "english": "English",
    "japanese": "Japanese",
    "korean": "Korean",
}
DEFAULT_LANGUAGE = "auto"

# Mirrors the official YuE2 chain-of-thought planning modes.
COT_MODES: dict[str, str] = {
    "full": "full",
    "melody": "melody",
    "off": "off",
}
DEFAULT_COT = "full"
COT_LABELS: dict[str, str] = {
    "full": "旋律 + 和弦规划（原创歌曲）",
    "melody": "仅旋律规划（翻唱推荐）",
    "off": "不做符号规划（最快）",
}

VAE_CHOICES: dict[str, str] = {
    "YuE2-Vae": "YuE2-Vae",
    "YuE2-Vae-legacy": "YuE2-Vae-legacy",
}
DEFAULT_VAE = "YuE2-Vae"

# Lyric sheet length intents, used by the idea-to-lyrics step.
LYRIC_LENGTHS: dict[str, str] = {
    "short": "short",
    "standard": "standard",
    "long": "long",
}
DEFAULT_LYRIC_LENGTH = "standard"
LYRIC_LENGTH_LABELS: dict[str, str] = {
    "short": "简短（单主歌 + 副歌）",
    "standard": "标准（两主歌 + 副歌 ×2）",
    "long": "加长（三主歌 + 桥段 + 副歌 ×3）",
}


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def genre_preset(genre_id: str) -> dict[str, Any]:
    """Return a genre preset, falling back to the default when unknown."""
    preset = GENRE_PRESETS.get(genre_id)
    if preset is None:
        preset = GENRE_PRESETS[DEFAULT_GENRE]
    return {"id": genre_id if genre_id in GENRE_PRESETS else DEFAULT_GENRE, **preset}


def vocal_setting(vocal_id: str) -> dict[str, Any]:
    setting = VOCAL_SETTINGS.get(vocal_id)
    if setting is None:
        setting = VOCAL_SETTINGS[DEFAULT_VOCAL]
    return {"id": vocal_id if vocal_id in VOCAL_SETTINGS else DEFAULT_VOCAL, **setting}


def _control_options(values: dict[str, str | None], labels: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {"id": key, "label": labels.get(key, key), "style_tag": value}
        for key, value in values.items()
    ]


def mood_options() -> list[dict[str, Any]]:
    return _control_options(MOODS, {})


def tempo_options() -> list[dict[str, Any]]:
    return _control_options(TEMPOS, {})


def structure_options() -> list[dict[str, Any]]:
    return [
        {"id": key, "label": STRUCTURE_LABELS.get(key, key), "style_tag": value}
        for key, value in STRUCTURES.items()
    ]


def language_options() -> list[dict[str, Any]]:
    return _control_options(LANGUAGES, {})


def cot_options() -> list[dict[str, Any]]:
    return [
        {"id": key, "label": COT_LABELS.get(key, key), "style_tag": value}
        for key, value in COT_MODES.items()
    ]


def lyric_length_options() -> list[dict[str, Any]]:
    return [
        {"id": key, "label": LYRIC_LENGTH_LABELS.get(key, key), "style_tag": value}
        for key, value in LYRIC_LENGTHS.items()
    ]


def catalog() -> dict[str, Any]:
    """Full catalog for the workspace UI."""
    return {
        "genres": [
            {"id": genre_id, **preset}
            for genre_id, preset in GENRE_PRESETS.items()
        ],
        "default_genre": DEFAULT_GENRE,
        "vocals": [
            {"id": vocal_id, **setting}
            for vocal_id, setting in VOCAL_SETTINGS.items()
        ],
        "default_vocal": DEFAULT_VOCAL,
        "moods": mood_options(),
        "default_mood": DEFAULT_MOOD,
        "tempos": tempo_options(),
        "default_tempo": DEFAULT_TEMPO,
        "structures": structure_options(),
        "default_structure": DEFAULT_STRUCTURE,
        "languages": language_options(),
        "default_language": DEFAULT_LANGUAGE,
        "cot": cot_options(),
        "default_cot": DEFAULT_COT,
        "vaes": [{"id": key, "label": value} for key, value in VAE_CHOICES.items()],
        "default_vae": DEFAULT_VAE,
        "lyric_lengths": lyric_length_options(),
        "default_lyric_length": DEFAULT_LYRIC_LENGTH,
    }


__all__ = [
    "COT_LABELS",
    "COT_MODES",
    "DEFAULT_COT",
    "DEFAULT_GENRE",
    "DEFAULT_LANGUAGE",
    "DEFAULT_LYRIC_LENGTH",
    "DEFAULT_MOOD",
    "DEFAULT_STRUCTURE",
    "DEFAULT_TEMPO",
    "DEFAULT_VAE",
    "DEFAULT_VOCAL",
    "GENRE_PRESETS",
    "LANGUAGES",
    "LYRIC_LENGTHS",
    "LYRIC_LENGTH_LABELS",
    "MOODS",
    "STRUCTURE_LABELS",
    "STRUCTURES",
    "TEMPOS",
    "VAE_CHOICES",
    "VOCAL_SETTINGS",
    "catalog",
    "cot_options",
    "genre_preset",
    "language_options",
    "lyric_length_options",
    "mood_options",
    "structure_options",
    "tempo_options",
    "vocal_setting",
]
