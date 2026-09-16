# Changelog

## 0.3.0 — source actually published

Up to `561ca41` this repository tracked **8 root files and nothing else**.
`backend/`, `guides/`, `web/` and `tests/` were never committed, so every install
died on the first line of `__init__.py`:

```
ModuleNotFoundError: No module named '...ComfyUI-YuE2-Prompt-Writer.backend'
[IMPORT FAILED] E:\ComfyUI\ComfyUI\custom_nodes\ComfyUI-YuE2-Prompt-Writer
```

The code described below is now committed in full — 35 files, ~6.8k lines. It was
reimplemented against the contracts this CHANGELOG and the README already spelled
out (module layout, endpoint names, route prefix, the `auto` sentinel, the
SHA-256-pinned guides, the section-numbering rule, non-empty fallbacks), using
`ComfyUI-MiniMaxH3-Prompt-Writer` — the implementation this README names as its
architectural reference — as the model for the provider layer and the GGUF reader.
It is functionally equivalent, **not** the original author's source.

### Fixed since 0.3.0 was written

- **`backend/lyricist.py` folded into `backend/lyrics.py` + `backend/assembly.py`.**
  Idea-to-lyrics ends up at `POST /yue2_prompt_writer/lyrics` exactly as
  documented; the split is by responsibility (engine vs. prompt assembly), not by
  feature.
- **The `auto` sentinel no longer leaks into user-visible text.** A generated sheet
  could come back with `你要求的是 auto，但检测到更像 Mandarin`; `analyze_payload()`
  now treats `auto` as "no preference" at the source.
- **GGUF listing reads the metadata block only.** Walking every tensor entry with
  `gguf.GGUFReader` costs seconds per multi-GB file; skipping the tensor index takes
  a real 9-model / ~90 GB folder from >120 s to under a second (measured here: 3
  models in 0.45 s).

### Verified

- Replays ComfyUI's own `load_custom_node()` with stub `server` / `folder_paths`:
  all 9 backend modules import, all 14 routes register.
- `tests/run_all.py` — 7 check scripts, all green.
- Real GPU run on `qwen3.5-9b`: idea → lyrics 37.4 s, style prompt 14.0 s
  (15 fragments, `Mandarin` tag correctly placed, no CJK leakage); VRAM back to
  baseline after unload; `qwen3.8-27b` (11.13 GB est.) correctly marked `too_large`
  against 10.78 GB free.

## 0.3.0

Idea-to-lyrics, plus two fixes that the new end-to-end run exposed.

### Added

- **Idea → lyrics** (`backend/lyricist.py`, `POST /yue2_prompt_writer/lyrics`).
  Type a theme or a one-line idea and the same local model writes a singable
  lyric sheet: bracketed section headers, blank-line layout, the chorus repeated
  word for word, section lengths and rhyme rules the guide spells out. The sheet
  comes back **normalised** through the existing lyric engine, so it drops
  straight into the lyric box — and from there into the style step.
- **A second bundled contract** (`guides/yue2_lyrics_writing_guide_en.md`), pinned
  by SHA-256 like the style guide: format rules, structure by length, syllable
  and rhyme guidance (Chinese and English), duet handling, and a worked example.
- **Quality notes** on every generated sheet: missing or single chorus, too few
  or too many singable lines, no verse, and a language mismatch against what was
  requested.
- **One-click chain** in the workspace: "AI 写歌词" fills the lyric box and, by
  default, continues straight into style generation. The chain can be switched
  off to edit the lyrics first.
- `--idea` in `tests/run_local_model_check.py` runs the whole chain on a single
  model load.
- **A draggable launcher.** The floating `YuE2` button can be dragged anywhere and
  remembers where you left it, so it no longer has to sit on top of ComfyUI's own
  controls. A drag is told apart from a click (4 px threshold), the position is
  clamped to the viewport and re-clamped when the window shrinks, and clearing
  `yue2PromptWriter.launcher.v1` from local storage resets it to the default
  corner.

### Fixed

- **`mood: "auto"` was rejected**, so *every* request from the workspace failed
  with `Unknown mood: 'auto'`. `auto` now exists in the mood catalog exactly as it
  already did for tempo and language. The panel's own default payload is now
  pinned by both test suites.
- **Repeated sections were numbered by kind** rather than by content, so a
  chorus sung three times could come back as `[Chorus 1]`/`[Chorus 2]` and a
  repeated pre-chorus as `[Pre-Chorus 1]`/`[Pre-Chorus 2]`. Numbering now depends
  on whether same-kind sections actually differ, so `[Verse 1]`/`[Verse 2]`
  appear while repeated choruses and pre-choruses keep bare headers — matching
  YuE2's own examples.
- **Model listing took over two minutes.** `gguf.GGUFReader` walks every tensor
  entry as well as the metadata, which costs seconds per multi-gigabyte file. The
  header is now parsed directly, reading only the metadata block and skipping the
  tensor index: 9 models (≈90 GB) went from >120 s to **0.49 s**. Results are also
  cached for 30 s, because the picker and every generation both resolve a model.

## 0.2.0

Local model backend, tuned for a 16 GB card.

### Added

- **In-process GGUF backend** (`backend/models/local_backend.py`), now the
  default provider. It lists the GGUFs under ComfyUI's `models/LLM` folder,
  loads one with `llama-cpp-python` **inside the ComfyUI process**, generates,
  and then releases it so the VRAM goes back to ComfyUI. No Ollama, no extra
  server, no network.
- **VRAM-aware loading.** The GGUF header is read for layer count, KV-head count
  and head dimension, then a per-generation estimate (weights + KV cache +
  compute buffer) is compared against the free VRAM. `n_gpu_layers` defaults to
  llama.cpp's `"auto"` so an oversized model is offloaded partially instead of
  failing, and the KV cache defaults to `q8_0` to halve its footprint.
- **Release only when needed.** If the estimate does not fit, ComfyUI's own
  models are dropped first (via its `/free` endpoint) — and only then, because
  that forces a reload later. `keep_loaded` is off by default.
- **Model picker** (`GET /yue2_prompt_writer/models`) with per-model size, layer
  count and a `fits` / `tight` / `too_large` badge, plus a manual
  `POST /yue2_prompt_writer/model/unload`.
- **Reasoning-model handling.** Some local fine-tunes open a `thinking` /
  `reasoning` key before the answer and burn the whole output budget on it. Three
  layers now deal with that: the system prompt forbids those fields, they are
  dropped when present, and a reply truncated *after* the `style` value is
  salvaged. A thinking-only reply now returns an actionable error instead of a
  vague parse failure.
- **Context-budget compaction**: a lyric sheet longer than 6000 characters is
  shortened for the prompt (section shape preserved) so a small `n_ctx` still
  fits.
- `llama_cpp` availability, model directories and the resident model are reported
  by `/health`.

### Changed

- The provider contract gained a `local` kind and the GGUF fields (`model` is the
  GGUF name, plus `n_ctx`, `n_gpu_layers`, `n_batch`, `kv_cache_type`,
  `flash_attention`, `offload_kqv`, `reasoning_budget`, `keep_loaded`,
  `free_comfy_vram`). `local` no longer requires a host.
- The workspace defaults to the local backend; Ollama and OpenAI-compatible
  endpoints remain available as alternatives.
- `/generate` now reports how many characters of prompt were sent.

## 0.1.0

First release. A YuE2-3B prompt-writing workspace for ComfyUI, modelled on the
structure of `duckyshell/ComfyUI-MiniMaxH3-Prompt-Writer`.

### Added

- **Workspace UI** (`web/`): a floating `YuE2` launcher opens a two-column
  panel — song settings and lyrics on the left, six copyable outputs on the
  right. No build step; plain ES modules and one stylesheet.
- **Six outputs**: the `style` prompt, the normalized lyric sheet, the
  duet-annotated lyric sheet, the vocal arrangement, a YuE2 JSON matching the
  official `examples/*.json` shape, and a runnable `YuE2Pipeline` snippet.
- **Deterministic lyric engine** (`backend/lyrics.py`): section header
  parsing (bilingual aliases, `[Verse 1]` numbering preserved), blank-line
  section inference with verse/chorus detection by repetition, language
  detection (Mandarin / Cantonese / English / Japanese / Korean), vocal
  assignment for male / female / duet / instrumental, duration estimation.
- **Style catalog** (`backend/catalog.py`): 32 genre presets with English style
  tags, instruments, moods, atmosphere, tempo, rhythm and production hints,
  plus mood / tempo / structure / language / chain-of-thought options.
- **Bundled writing guide** (`guides/`, `backend/guides.py`): a frozen English
  contract covering the six style components, the language-tag rules and the
  JSON output schema, pinned by SHA-256 so it cannot drift silently.
- **Writing providers** (`backend/models/`): Ollama (`/api/chat`) and
  OpenAI-compatible (`/chat/completions`) backends on `aiohttp` only, with
  capability probes, timeouts and structured error codes.
- **Fallback writer**: with no provider configured the style prompt is
  assembled from the catalog, so the workspace always produces something usable.
- **ComfyUI endpoints** (`backend/routes.py`): `/health`, `/catalog`, `/guide`,
  `/plan`, `/generate`, `/provider/test` under `/yue2_prompt_writer`.

### Notes

- The UI is a workspace, not a node: `NODE_CLASS_MAPPINGS` stays empty and no
  graph is ever modified or queued.
- `style` sanitization drops leaked lyrics (CJK fragments), sentence-shaped
  fragments and duplicates, then trims to 20 fragments.
- Model failures are non-fatal: the response carries the deterministic fallback
  plus the reason.

## Tests

- `python tests/run_tests.py` — 99 dependency-free assertions.
- `python tests/run_api_tests.py` — 110 end-to-end HTTP assertions.
- `python tests/run_local_model_check.py` — optional smoke test on a real GPU;
  `--idea` runs idea -> lyrics -> style on one model load and times each stage.
