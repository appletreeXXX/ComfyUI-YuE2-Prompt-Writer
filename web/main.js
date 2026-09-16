import { app } from "/scripts/app.js";
import {
  analyzeLyrics,
  cancel,
  generate,
  getCatalog,
  getHealth,
  getModels,
  preview,
  testProvider,
  unloadModel,
  writeLyrics,
} from "./api/yue2.js";

const EXTENSION_NAME = "yue2.prompt.writer";
const STYLE_URL = new URL("./styles/yue2.css", import.meta.url).href;

// Launcher position and the lyric draft are the two things worth persisting.
const LAUNCHER_KEY = "yue2PromptWriter.launcher.v1";
const DRAFT_KEY = "yue2PromptWriter.draft.v1";
const DRAG_THRESHOLD_PX = 4;

// Output longer than this starts collapsed, so one long block cannot push the
// rest of the panel out of reach; the reader expands it in place.
const COLLAPSE_THRESHOLD = 600;

const state = {
  open: false,
  catalog: null,
  health: null,
  brief: {
    genre: "citypop",
    vocal: "female",
    mood: "auto",
    tempo: "auto",
    structure: "auto",
    language: "auto",
    cot: "full",
    vae: "YuE2-Vae",
    lyric_length: "standard",
    title: "",
    idea: "",
    lyrics: "",
    notes: "",
    seed: -1,
    chain_lyrics: true,
  },
  provider: {
    kind: "local",
    model: "",
    n_ctx: 8192,
    n_gpu_layers: -1,
    kv_cache_type: "q8_0",
    reasoning_budget: 0,
    keep_loaded: false,
    free_comfy_vram: true,
    max_tokens: 2048,
    temperature: 0.6,
    host: "",
    api_key: "",
  },
  result: null,
  busy: false,
};

let root = null;
let statusTimer = null;

// --------------------------------------------------------------------------
// Persistence
// --------------------------------------------------------------------------
function loadLauncherPosition() {
  try {
    const raw = JSON.parse(localStorage.getItem(LAUNCHER_KEY) || "null");
    if (raw && Number.isFinite(raw.left) && Number.isFinite(raw.top)) return raw;
  } catch {
    /* a corrupt value is not worth reporting */
  }
  return null;
}

function saveLauncherPosition(left, top) {
  try {
    localStorage.setItem(LAUNCHER_KEY, JSON.stringify({ left, top }));
  } catch {
    /* storage may be full or blocked */
  }
}

function loadDraft() {
  try {
    const raw = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
    if (raw && typeof raw === "object") {
      for (const key of ["lyrics", "idea", "title", "notes", "genre", "vocal", "language", "mood", "tempo"]) {
        if (typeof raw[key] === "string") state.brief[key] = raw[key];
      }
    }
  } catch {
    /* ignore */
  }
}

function saveDraft() {
  try {
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({
        lyrics: state.brief.lyrics,
        idea: state.brief.idea,
        title: state.brief.title,
        notes: state.brief.notes,
        genre: state.brief.genre,
        vocal: state.brief.vocal,
        language: state.brief.language,
        mood: state.brief.mood,
        tempo: state.brief.tempo,
      }),
    );
  } catch {
    /* ignore */
  }
}

// --------------------------------------------------------------------------
// Launcher
// --------------------------------------------------------------------------
function clampToViewport(left, top) {
  const size = 52;
  const margin = 8;
  return {
    left: Math.min(Math.max(margin, left), window.innerWidth - size - margin),
    top: Math.min(Math.max(margin, top), window.innerHeight - size - margin),
  };
}

function installLauncher() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "yue2-launcher";
  button.textContent = "YuE2";
  button.title = "YuE2 提示词工作台";
  button.setAttribute("aria-label", "打开 YuE2 提示词工作台");

  const saved = loadLauncherPosition();
  const initial = saved
    ? clampToViewport(saved.left, saved.top)
    : clampToViewport(window.innerWidth - 70, window.innerHeight - 70);
  button.style.left = `${initial.left}px`;
  button.style.top = `${initial.top}px`;
  button.style.right = "auto";
  button.style.bottom = "auto";

  let dragging = false;
  let moved = false;
  let offsetX = 0;
  let offsetY = 0;

  const onPointerMove = (event) => {
    if (!dragging) return;
    const dx = event.clientX - offsetX;
    const dy = event.clientY - offsetY;
    if (!moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
    // A drag is only a drag past the threshold, so a click still opens the panel.
    if (!moved) {
      moved = true;
      button.dataset.dragging = "true";
    }
    const position = clampToViewport(event.clientX - offsetX, event.clientY - offsetY);
    button.style.left = `${position.left}px`;
    button.style.top = `${position.top}px`;
  };

  const onPointerUp = () => {
    if (!dragging) return;
    dragging = false;
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    delete button.dataset.dragging;
    if (moved) {
      saveLauncherPosition(parseFloat(button.style.left), parseFloat(button.style.top));
    } else {
      togglePanel();
    }
  };

  button.addEventListener("pointerdown", (event) => {
    dragging = true;
    moved = false;
    const rect = button.getBoundingClientRect();
    offsetX = event.clientX - rect.left;
    offsetY = event.clientY - rect.top;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  });

  // Re-clamp when the window shrinks so the button never leaves the viewport.
  window.addEventListener("resize", () => {
    const position = clampToViewport(parseFloat(button.style.left), parseFloat(button.style.top));
    button.style.left = `${position.left}px`;
    button.style.top = `${position.top}px`;
  });

  document.body.appendChild(button);
}

// --------------------------------------------------------------------------
// Panel scaffold
// --------------------------------------------------------------------------
const OUTPUTS = [
  { key: "style", title: "① Style 提示词" },
  { key: "normalized_lyrics", title: "② 规范化歌词" },
  { key: "annotated_lyrics", title: "③ 带声部标注的歌词" },
  { key: "vocal_arrangement", title: "④ 人声编排建议" },
  { key: "json", title: "⑤ YuE2 JSON" },
  { key: "python_snippet", title: "⑥ Python 调用片段" },
];

function markup() {
  return `
<div class="yue2-backdrop" data-yue2-backdrop hidden></div>
<section class="yue2-panel" data-yue2-panel role="dialog" aria-modal="true" aria-label="YuE2 提示词工作台" hidden>
  <header class="yue2-header">
    <h2>YuE2 提示词工作台</h2>
    <span class="yue2-version" data-yue2-version></span>
    <span class="yue2-spacer"></span>
    <button type="button" class="yue2-button" data-yue2-local-preview>本地预览</button>
    <button type="button" class="yue2-button yue2-button-primary" data-yue2-generate>AI 生成提示词</button>
    <button type="button" class="yue2-button" data-yue2-close aria-label="关闭">关闭</button>
  </header>

  <div class="yue2-body">
    <div class="yue2-column">
      <div class="yue2-status" data-yue2-status hidden></div>

      <div class="yue2-section">
        <h3>歌曲设定</h3>
        <div class="yue2-field">
          <label for="yue2-genre">曲风</label>
          <select id="yue2-genre" data-yue2-genre></select>
        </div>
        <div class="yue2-field">
          <label>人声</label>
          <div class="yue2-vocal-row" data-yue2-vocals></div>
        </div>
        <div class="yue2-grid-2">
          <div class="yue2-field">
            <label for="yue2-language">语言</label>
            <select id="yue2-language" data-yue2-language></select>
          </div>
          <div class="yue2-field">
            <label for="yue2-mood">情绪</label>
            <select id="yue2-mood" data-yue2-mood></select>
          </div>
          <div class="yue2-field">
            <label for="yue2-tempo">速度</label>
            <select id="yue2-tempo" data-yue2-tempo></select>
          </div>
          <div class="yue2-field">
            <label for="yue2-structure">篇幅</label>
            <select id="yue2-structure" data-yue2-structure></select>
          </div>
          <div class="yue2-field">
            <label for="yue2-cot">规划模式 (cot)</label>
            <select id="yue2-cot" data-yue2-cot></select>
          </div>
          <div class="yue2-field">
            <label for="yue2-vae">VAE</label>
            <select id="yue2-vae" data-yue2-vae></select>
          </div>
        </div>
        <div class="yue2-grid-2">
          <div class="yue2-field">
            <label for="yue2-title">标题</label>
            <input type="text" id="yue2-title" data-yue2-title placeholder="可留空" />
          </div>
          <div class="yue2-field">
            <label for="yue2-seed">seed</label>
            <input type="number" id="yue2-seed" data-yue2-seed value="-1" />
          </div>
        </div>
        <div class="yue2-field">
          <label for="yue2-notes">额外要求</label>
          <input type="text" id="yue2-notes" data-yue2-notes placeholder="例如：必须加入萨克斯，不要失真吉他" />
        </div>
      </div>

      <div class="yue2-section">
        <h3>歌词</h3>
        <div class="yue2-field">
          <label for="yue2-idea">主题 / 一句话想法</label>
          <input type="text" id="yue2-idea" data-yue2-idea placeholder="例如：雨夜开车去找一个还没走的人" />
        </div>
        <div class="yue2-grid-2">
          <div class="yue2-field">
            <label for="yue2-lyric-length">歌词篇幅</label>
            <select id="yue2-lyric-length" data-yue2-lyric-length></select>
          </div>
          <div class="yue2-field">
            <label>&nbsp;</label>
            <label class="yue2-checkbox">
              <input type="checkbox" data-yue2-chain checked />
              写完后接着生成提示词
            </label>
          </div>
        </div>
        <div class="yue2-button-row" style="margin-bottom:10px">
          <button type="button" class="yue2-button" data-yue2-write-lyrics>AI 写歌词</button>
          <button type="button" class="yue2-button" data-yue2-analyze>重新分析</button>
          <button type="button" class="yue2-button" data-yue2-clear-lyrics>清空歌词</button>
        </div>
        <div class="yue2-field">
          <label for="yue2-lyrics">歌词内容</label>
          <textarea id="yue2-lyrics" class="yue2-lyrics-box" data-yue2-lyrics
            placeholder="粘贴歌词，有没有 [Verse] / [Chorus] 标签都可以"></textarea>
        </div>
        <div class="yue2-section" style="border:none;padding:0">
          <div class="yue2-chips" data-yue2-chips></div>
          <ul class="yue2-notes" data-yue2-notes-list></ul>
        </div>
      </div>

      <div class="yue2-section">
        <h3>写作模型 (Provider)</h3>
        <div class="yue2-grid-2">
          <div class="yue2-field">
            <label for="yue2-provider-kind">类型</label>
            <select id="yue2-provider-kind" data-yue2-provider-kind>
              <option value="local">Local GGUF (models/LLM)</option>
              <option value="ollama">Ollama (local server)</option>
              <option value="openai">OpenAI-compatible endpoint</option>
            </select>
          </div>
          <div class="yue2-field" data-yue2-local-field>
            <label for="yue2-model">模型</label>
            <select id="yue2-model" data-yue2-model></select>
          </div>
          <div class="yue2-field" data-yue2-remote-field hidden>
            <label for="yue2-model-name">模型名称</label>
            <input type="text" id="yue2-model-name" data-yue2-model-name placeholder="例如 qwen3:8b" />
          </div>
          <div class="yue2-field" data-yue2-remote-field hidden>
            <label for="yue2-host">服务地址</label>
            <input type="text" id="yue2-host" data-yue2-host placeholder="留空则用 http://127.0.0.1:11434" />
          </div>
        </div>
        <div class="yue2-grid-2">
          <div class="yue2-field">
            <label for="yue2-nctx">n_ctx</label>
            <input type="number" id="yue2-nctx" data-yue2-nctx value="8192" />
          </div>
          <div class="yue2-field">
            <label for="yue2-ngl">n_gpu_layers</label>
            <input type="number" id="yue2-ngl" data-yue2-ngl value="-1" />
          </div>
        </div>
        <label class="yue2-checkbox" style="margin-bottom:6px">
          <input type="checkbox" data-yue2-keep-loaded />
          生成后保留模型（占显存）
        </label>
        <div class="yue2-button-row">
          <button type="button" class="yue2-button" data-yue2-test>测试</button>
          <button type="button" class="yue2-button" data-yue2-unload>卸载模型</button>
        </div>
        <div class="yue2-notes" data-yue2-provider-info style="margin-top:8px"></div>
      </div>
    </div>

    <div class="yue2-column" data-yue2-outputs>
      <div class="yue2-empty" data-yue2-output-empty>
        点「本地预览」立刻生成一份不调用模型的提示词，或配置写作模型后点「AI 生成提示词」。
      </div>
    </div>
  </div>
</section>`;
}

// --------------------------------------------------------------------------
// Rendering
// --------------------------------------------------------------------------
function setStatus(message, tone = "info") {
  if (!root) return;
  const element = root.querySelector("[data-yue2-status]");
  if (!element) return;
  if (!message) {
    element.hidden = true;
    return;
  }
  element.hidden = false;
  element.textContent = message;
  element.dataset.tone = tone;
  if (statusTimer) clearTimeout(statusTimer);
  if (tone !== "error") {
    statusTimer = setTimeout(() => {
      element.hidden = true;
    }, 6000);
  }
}

function fillSelect(selector, options, current, labelKey = "label", valueKey = "id") {
  const element = root.querySelector(selector);
  if (!element) return;
  element.innerHTML = "";
  for (const option of options) {
    const item = document.createElement("option");
    item.value = String(option[valueKey]);
    item.textContent = String(option[labelKey]);
    element.appendChild(item);
  }
  element.value = String(current);
}

function renderCatalog() {
  const catalog = state.catalog;
  if (!catalog) return;

  fillSelect("[data-yue2-genre]", catalog.genres.map((g) => ({ id: g.id, label: `${g.label_zh}（${g.tags[0]}）` })), state.brief.genre);
  fillSelect("[data-yue2-language]", catalog.languages, state.brief.language);
  fillSelect("[data-yue2-mood]", catalog.moods, state.brief.mood);
  fillSelect("[data-yue2-tempo]", catalog.tempos, state.brief.tempo);
  fillSelect("[data-yue2-structure]", catalog.structures, state.brief.structure);
  fillSelect("[data-yue2-cot]", catalog.cot, state.brief.cot);
  fillSelect("[data-yue2-vae]", catalog.vaes, state.brief.vae);
  fillSelect("[data-yue2-lyric-length]", catalog.lyric_lengths, state.brief.lyric_length);

  const vocalRow = root.querySelector("[data-yue2-vocals]");
  vocalRow.innerHTML = "";
  for (const vocal of catalog.vocals) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = vocal.label_zh;
    button.dataset.vocal = vocal.id;
    button.setAttribute("aria-pressed", String(vocal.id === state.brief.vocal));
    button.addEventListener("click", () => {
      state.brief.vocal = vocal.id;
      renderCatalog();
      saveDraft();
      scheduleAnalysis();
    });
    vocalRow.appendChild(button);
  }
}

function renderResult() {
  const container = root.querySelector("[data-yue2-outputs]");
  const result = state.result;
  if (!result) return;

  container.innerHTML = "";
  for (const output of OUTPUTS) {
    const value = String(result[output.key] ?? "").trim();
    if (!value) continue;
    const block = document.createElement("div");
    block.className = "yue2-output";
    const collapsible = value.length > COLLAPSE_THRESHOLD;
    if (collapsible) block.dataset.collapsed = "true";
    block.innerHTML = `
      <div class="yue2-output-head">
        <h4>${output.title}</h4>
        <span class="yue2-spacer"></span>
        ${
          collapsible
            ? `<button type="button" class="yue2-toggle" data-expanded="false"
                 aria-expanded="false">展开全文</button>`
            : ""
        }
        <button type="button" class="yue2-copy">复制</button>
      </div>
      <pre></pre>`;
    block.querySelector("pre").textContent = value;

    const toggleButton = block.querySelector(".yue2-toggle");
    if (toggleButton) {
      toggleButton.addEventListener("click", () => {
        const collapsed = block.dataset.collapsed === "true";
        if (collapsed) {
          delete block.dataset.collapsed;
          toggleButton.textContent = "收起";
          toggleButton.dataset.expanded = "true";
          toggleButton.setAttribute("aria-expanded", "true");
        } else {
          block.dataset.collapsed = "true";
          toggleButton.textContent = "展开全文";
          toggleButton.dataset.expanded = "false";
          toggleButton.setAttribute("aria-expanded", "false");
        }
      });
    }

    const copyButton = block.querySelector(".yue2-copy");
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(value);
        copyButton.textContent = "已复制";
        copyButton.dataset.copied = "true";
        setTimeout(() => {
          copyButton.textContent = "复制";
          delete copyButton.dataset.copied;
        }, 1500);
      } catch {
        setStatus("剪贴板不可用，请手动选中复制。", "warn");
      }
    });
    container.appendChild(block);
  }

  const meta = document.createElement("div");
  meta.className = "yue2-section";
  const source = result.source === "local_preview"
    ? "本地预览（未调用模型）"
    : result.source === "fallback"
      ? "内置曲风库（模型调用失败后的回退）"
      : `写作模型（${result.source || "unknown"}）`;
  meta.innerHTML = `<h3>本次生成</h3>`;
  const list = document.createElement("ul");
  list.className = "yue2-notes";
  const rows = [
    `来源：${source}`,
    `片段数：${result.fragment_count ?? 0}`,
  ];
  if (result.provider_note) rows.push(`提示：${result.provider_note}`);
  if (result.notes) rows.push(`模型说明：${result.notes}`);
  const analysis = result.analysis || {};
  if (analysis.language) rows.push(`检测语言：${analysis.language}`);
  if (analysis.duration?.label) rows.push(`时长估算：${analysis.duration.label}`);
  for (const row of rows) {
    const item = document.createElement("li");
    item.textContent = row;
    list.appendChild(item);
  }
  meta.appendChild(list);
  container.appendChild(meta);
}

function renderAnalysis(analysis) {
  if (!analysis) return;
  const chips = root.querySelector("[data-yue2-chips]");
  const notes = root.querySelector("[data-yue2-notes-list]");
  chips.innerHTML = "";
  notes.innerHTML = "";

  for (const section of analysis.sections || []) {
    const chip = document.createElement("span");
    chip.className = "yue2-chip";
    chip.textContent = section.header;
    chips.appendChild(chip);
  }
  if (analysis.language) {
    const chip = document.createElement("span");
    chip.className = "yue2-chip";
    chip.textContent = `${analysis.language}${analysis.language_confidence ? ` · ${analysis.language_confidence}` : ""}`;
    chips.appendChild(chip);
  }
  if (analysis.duration?.label) {
    const chip = document.createElement("span");
    chip.className = "yue2-chip";
    chip.textContent = analysis.duration.label;
    chips.appendChild(chip);
  }
  for (const note of analysis.quality_notes || []) {
    const item = document.createElement("li");
    item.textContent = note;
    notes.appendChild(item);
  }
}

// --------------------------------------------------------------------------
// Payload
// --------------------------------------------------------------------------
function buildPayload() {
  return {
    genre: state.brief.genre,
    vocal: state.brief.vocal,
    mood: state.brief.mood,
    tempo: state.brief.tempo,
    structure: state.brief.structure,
    language: state.brief.language,
    cot: state.brief.cot,
    vae: state.brief.vae,
    lyric_length: state.brief.lyric_length,
    title: state.brief.title,
    idea: state.brief.idea,
    lyrics: state.brief.lyrics,
    notes: state.brief.notes,
    seed: Number(state.brief.seed) || -1,
    provider: providerPayload(),
  };
}

function providerPayload() {
  const kind = state.provider.kind;
  const base = {
    kind,
    n_ctx: Number(state.provider.n_ctx) || 8192,
    n_gpu_layers: Number(state.provider.n_gpu_layers),
    kv_cache_type: state.provider.kv_cache_type,
    reasoning_budget: state.provider.reasoning_budget,
    keep_loaded: state.provider.keep_loaded,
    free_comfy_vram: state.provider.free_comfy_vram,
    max_tokens: state.provider.max_tokens,
    temperature: state.provider.temperature,
  };
  if (kind === "local") return { ...base, model: state.provider.model };
  const modelField = root.querySelector("[data-yue2-model-name]");
  const hostField = root.querySelector("[data-yue2-host]");
  return {
    ...base,
    model: modelField?.value.trim() || state.provider.model,
    host: hostField?.value.trim() || state.provider.host,
    api_key: state.provider.api_key,
  };
}

// --------------------------------------------------------------------------
// Actions
// --------------------------------------------------------------------------
let analysisTimer = null;

function scheduleAnalysis() {
  if (analysisTimer) clearTimeout(analysisTimer);
  analysisTimer = setTimeout(async () => {
    try {
      const response = await analyzeLyrics(state.brief.lyrics, {
        language: state.brief.language,
        vocal: state.brief.vocal,
        lyric_length: state.brief.lyric_length,
      });
      renderAnalysis(response.analysis);
    } catch {
      /* analysis is advisory; a failure must not disturb the user */
    }
  }, 250);
}

function setBusy(busy) {
  state.busy = busy;
  for (const selector of ["[data-yue2-generate]", "[data-yue2-local-preview]", "[data-yue2-write-lyrics]", "[data-yue2-analyze]", "[data-yue2-test]"]) {
    const element = root.querySelector(selector);
    if (element) element.disabled = busy;
  }
}

async function runPreview() {
  try {
    setBusy(true);
    state.result = await preview(buildPayload());
    renderResult();
    setStatus("已用内置曲风库生成提示词。", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function runGenerate() {
  if (state.provider.kind === "local" && !state.provider.model) {
    setStatus("请先在「写作模型」里选择一个本地模型，或用「本地预览」。", "warn");
    return;
  }
  try {
    setBusy(true);
    setStatus("正在生成提示词…", "info");
    const result = await generate(buildPayload());
    state.result = result;
    renderResult();
    if (result.error) {
      setStatus(`模型调用失败（${result.error.message}），已改用内置曲风库。`, "warn");
    } else {
      setStatus("生成完成。", "ok");
    }
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function runWriteLyrics() {
  if (!state.brief.idea && !state.brief.lyrics) {
    setStatus("请先填一个主题，或粘贴一段草稿让它改写。", "warn");
    return;
  }
  if (state.provider.kind === "local" && !state.provider.model) {
    setStatus("写歌词需要写作模型，请先选择一个本地模型。", "warn");
    return;
  }
  try {
    setBusy(true);
    setStatus("正在写歌词…", "info");
    const result = await writeLyrics(buildPayload());
    state.brief.lyrics = result.normalized_lyrics || result.raw_lyrics || "";
    if (result.title && !state.brief.title) state.brief.title = result.title;
    root.querySelector("[data-yue2-lyrics]").value = state.brief.lyrics;
    root.querySelector("[data-yue2-title]").value = state.brief.title;
    saveDraft();
    renderAnalysis(result.analysis);
    setStatus(`歌词已写入（${result.quality_notes?.length || 0} 条质量提示）。`, "ok");
    if (state.brief.chain_lyrics) await runGenerate();
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

async function runTest() {
  try {
    setBusy(true);
    setStatus("正在测试…", "info");
    const result = await testProvider(providerPayload());
    const info = root.querySelector("[data-yue2-provider-info]");
    if (!result.ok) {
      info.textContent = `连接失败：${result.error?.message || "未知错误"}`;
      setStatus("写作模型连接失败。", "error");
      return;
    }
    if (state.provider.kind === "local") {
      info.textContent = [
        `目录：${result.directory || "未找到 models/LLM"}`,
        `模型数：${result.model_count}`,
        `可用显存：${result.free_vram_gb ?? "未知"} GB`,
        `llama-cpp-python：${result.llama_cpp_available ? "可用" : "缺失"}`,
      ].join(" ｜ ");
      renderLocalModels(result.models || []);
    } else {
      info.textContent = `地址：${result.host} ｜ 模型数：${result.model_count}`;
    }
    setStatus("写作模型可用。", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    setBusy(false);
  }
}

function renderLocalModels(models) {
  const select = root.querySelector("[data-yue2-model]");
  select.innerHTML = "";
  if (!models.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "models/LLM 中没有可用的 GGUF";
    select.appendChild(option);
    return;
  }
  const badge = { fits: "可全量加载", tight: "需部分卸载到 CPU", too_large: "显存不足", unknown: "显存未知" };
  for (const model of models) {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = `${model.size_gb} GB · ${model.id}（${badge[model.fits] || model.fits}）`;
    select.appendChild(option);
  }
  // Default to the largest model that still loads fully: the quality/speed balance.
  const best = [...models].reverse().find((model) => model.fits === "fits") || models[0];
  select.value = best.id;
  state.provider.model = best.id;
}

async function runUnload() {
  try {
    const result = await unloadModel();
    setStatus(result.unloaded ? "已卸载模型，显存已释放。" : result.reason || "没有已加载的模型。", "ok");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

// --------------------------------------------------------------------------
// Wiring
// --------------------------------------------------------------------------
function bind() {
  const panel = root.querySelector("[data-yue2-panel]");
  const backdrop = root.querySelector("[data-yue2-backdrop]");

  root.querySelector("[data-yue2-close]").addEventListener("click", closePanel);
  backdrop.addEventListener("click", closePanel);

  const bindSelect = (selector, key, after) => {
    const element = root.querySelector(selector);
    element.addEventListener("change", () => {
      state.brief[key] = element.value;
      saveDraft();
      if (after) after();
    });
  };
  bindSelect("[data-yue2-language]", "language", scheduleAnalysis);
  bindSelect("[data-yue2-mood]", "mood");
  bindSelect("[data-yue2-tempo]", "tempo");
  bindSelect("[data-yue2-structure]", "structure");
  bindSelect("[data-yue2-cot]", "cot");
  bindSelect("[data-yue2-vae]", "vae");
  bindSelect("[data-yue2-lyric-length]", "lyric_length", scheduleAnalysis);
  bindSelect("[data-yue2-genre]", "genre");

  const lyrics = root.querySelector("[data-yue2-lyrics]");
  lyrics.addEventListener("input", () => {
    state.brief.lyrics = lyrics.value;
    saveDraft();
    scheduleAnalysis();
  });

  const bindText = (selector, key, save = true) => {
    const element = root.querySelector(selector);
    element.addEventListener("input", () => {
      state.brief[key] = element.value;
      if (save) saveDraft();
    });
  };
  bindText("[data-yue2-idea]", "idea");
  bindText("[data-yue2-title]", "title");
  bindText("[data-yue2-notes]", "notes");
  bindText("[data-yue2-seed]", "seed", false);

  root.querySelector("[data-yue2-chain]").addEventListener("change", (event) => {
    state.brief.chain_lyrics = event.target.checked;
  });

  root.querySelector("[data-yue2-provider-kind]").addEventListener("change", (event) => {
    state.provider.kind = event.target.value;
    renderProviderFields();
  });
  const nctx = root.querySelector("[data-yue2-nctx]");
  nctx.addEventListener("input", () => {
    state.provider.n_ctx = Number(nctx.value) || 8192;
  });
  const ngl = root.querySelector("[data-yue2-ngl]");
  ngl.addEventListener("input", () => {
    state.provider.n_gpu_layers = Number(ngl.value);
  });
  root.querySelector("[data-yue2-model]").addEventListener("change", (event) => {
    state.provider.model = event.target.value;
  });
  root.querySelector("[data-yue2-keep-loaded]").addEventListener("change", (event) => {
    state.provider.keep_loaded = event.target.checked;
  });

  root.querySelector("[data-yue2-local-preview]").addEventListener("click", runPreview);
  root.querySelector("[data-yue2-generate]").addEventListener("click", runGenerate);
  root.querySelector("[data-yue2-write-lyrics]").addEventListener("click", runWriteLyrics);
  root.querySelector("[data-yue2-analyze]").addEventListener("click", scheduleAnalysis);
  root.querySelector("[data-yue2-clear-lyrics]").addEventListener("click", () => {
    state.brief.lyrics = "";
    lyrics.value = "";
    saveDraft();
    renderAnalysis(null);
    root.querySelector("[data-yue2-chips]").innerHTML = "";
    root.querySelector("[data-yue2-notes-list]").innerHTML = "";
  });
  root.querySelector("[data-yue2-test]").addEventListener("click", runTest);
  root.querySelector("[data-yue2-unload]").addEventListener("click", runUnload);

  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !event.target.closest("input, textarea, select")) {
      closePanel();
    }
  });
}

function renderProviderFields() {
  const kind = state.provider.kind;
  for (const element of root.querySelectorAll("[data-yue2-local-field]")) {
    element.hidden = kind !== "local";
  }
  for (const element of root.querySelectorAll("[data-yue2-remote-field]")) {
    element.hidden = kind === "local";
  }
}

async function loadCatalogAndHealth() {
  try {
    const [catalog, health] = await Promise.all([getCatalog(), getHealth()]);
    state.catalog = catalog;
    state.health = health;
    renderCatalog();

    root.querySelector("[data-yue2-version]").textContent = `v${health.version}`;
    const info = root.querySelector("[data-yue2-provider-info]");
    if (!health.llama_cpp_available) {
      info.textContent = "未检测到 llama-cpp-python，本地 GGUF 不可用，请改用 Ollama 或 OpenAI 兼容端点。";
    } else if (!health.llm_models_directory) {
      info.textContent = "未找到 models/LLM 目录。";
    } else {
      info.textContent = `models/LLM：${health.llm_models_directory}`;
    }

    if (state.provider.kind === "local") {
      const listing = await getModels();
      renderLocalModels(listing.models || []);
    }
  } catch (error) {
    setStatus(`初始化失败：${error.message}`, "error");
  }
}

// --------------------------------------------------------------------------
// Panel lifecycle
// --------------------------------------------------------------------------
function openPanel() {
  if (!root) {
    root = document.createElement("div");
    root.innerHTML = markup();
    document.body.appendChild(root);
    bind();
    loadCatalogAndHealth();
    loadDraft();
    root.querySelector("[data-yue2-lyrics]").value = state.brief.lyrics;
    root.querySelector("[data-yue2-idea]").value = state.brief.idea;
    root.querySelector("[data-yue2-title]").value = state.brief.title;
    root.querySelector("[data-yue2-notes]").value = state.brief.notes;
    root.querySelector("[data-yue2-provider-kind]").value = state.provider.kind;
    renderProviderFields();
    scheduleAnalysis();
  }
  root.querySelector("[data-yue2-panel]").hidden = false;
  root.querySelector("[data-yue2-backdrop]").hidden = false;
  state.open = true;
}

function closePanel() {
  if (!root) return;
  root.querySelector("[data-yue2-panel]").hidden = true;
  root.querySelector("[data-yue2-backdrop]").hidden = true;
  state.open = false;
  saveDraft();
}

function togglePanel() {
  if (state.open) closePanel();
  else openPanel();
}

function injectStyles() {
  if (document.getElementById("yue2-prompt-writer-styles")) return;
  const link = document.createElement("link");
  link.id = "yue2-prompt-writer-styles";
  link.rel = "stylesheet";
  link.href = STYLE_URL;
  document.head.appendChild(link);
}

app.registerExtension({
  name: EXTENSION_NAME,
  commands: [
    { id: "yue2-prompt-writer.open", label: "Open YuE2 Prompt Writer", function: openPanel },
  ],
  menuCommands: [
    { path: ["Extensions", "YuE2 Prompt Writer"], commands: ["yue2-prompt-writer.open"] },
  ],
  async setup() {
    injectStyles();
    installLauncher();
  },
});
