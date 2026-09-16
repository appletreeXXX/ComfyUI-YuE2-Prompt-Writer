# ComfyUI YuE2 Prompt Writer

面向 [YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B) 的 ComfyUI 提示词工作台。

给它**歌词**，选**曲风**，选**男声 / 女声 / 男女混唱**，它会产出一份可以直接喂给 YuE2 的
`style` 编曲提示词，外加一份规范化歌词和一个可直接运行的 YuE2 JSON。

这是一个 **ComfyUI UI 扩展**，不是工作流节点：它只写提示词文本，不运行 YuE2、不修改你的
工作流、不排队任务。模型权重也不随扩展分发。

架构与交互方式参考 [duckyshell/ComfyUI-MiniMaxH3-Prompt-Writer](https://github.com/duckyshell/ComfyUI-MiniMaxH3-Prompt-Writer)：
一个浮动工作台面板 + 内置写作契约（guide）+ 可插拔的写作模型 provider。

> **关于本仓库的代码状态。** 上游仓库最初只推送了 8 个根文件，`backend/`、`guides/`、
> `web/`、`tests/` 四个目录没有上传，导致 ComfyUI 加载时必然报
> `ModuleNotFoundError: No module named '...ComfyUI-YuE2-Prompt-Writer.backend'`。
> 因此 `backend/`、`guides/`、`web/`、`tests/` 下的实现是依据本 README 与
> `CHANGELOG.md` 所描述的架构**重新实现**的，并非原作者的原始代码。
> 上游作者重新推送原始代码后，本目录的对应文件应被替换。

---

## 它解决什么问题

YuE2 的 `style` 参数要求是一串**英文、逗号分隔**的风格描述。官方示例长这样：

```text
City Pop, upbeat, danceable, groovy bass, electric guitar, synth, energetic, joyful, neon city night
```

```text
Jazz-funk, warm lead vocal, Rhodes piano, electric bass, tight drums
```

手写这些并不难，但很容易漏掉关键维度（语言标签、人声性别、音色、BPM 感），而
**漏掉 `Mandarin` / `Cantonese` 这类语言标签会直接影响吐字**。本扩展把这件事变成：

1. **还没有歌词？** 填一句主题，点「AI 写歌词」——模型会按你选的曲风、人声、语言和
   篇幅写一份**能唱**的歌词，自动填进歌词框。
2. 已经有歌词就直接粘贴（有没有 `[Verse]` / `[Chorus]` 标签都行）。
3. 下拉选曲风，点一下选人声。
4. 点「AI 生成提示词」。

就得到一份 8–20 个片段的 style 提示词、一份规范化歌词、一份 YuE2 JSON。
整条链路可以一键走完：**主题 → 歌词 → 提示词**。

---

## 六块输出

| 输出 | 说明 |
| --- | --- |
| ① Style 提示词 | 直接填进 YuE2 的 `style` 参数 |
| ② 规范化歌词 | 统一 `[Verse]` / `[Chorus]` 标签、段落空行分隔，与官方 `examples/*.json` 一致 |
| ③ 带声部标注的歌词 | 仅男女混唱时输出，如 `[Verse 1 · Male]` |
| ④ 人声编排建议 | 哪个段落谁唱；混唱时按主歌交替、副歌齐唱自动分配 |
| ⑤ YuE2 JSON | 字段与官方 `examples/tonight-awake.json` 对齐：`title` / `style` / `lyrics` / `cot` / `seed` |
| ⑥ Python 调用片段 | 直接读取上面 JSON 的 `YuE2Pipeline` 调用范例 |

每一块都有单独的「复制」按钮。

---

## 安装

```bash
cd ComfyUI/custom_nodes
git clone <this-repo> ComfyUI-YuE2-Prompt-Writer
```

或者把整个目录压缩包解压到 `ComfyUI/custom_nodes/ComfyUI-YuE2-Prompt-Writer`。

重启 ComfyUI。**不会出现任何节点**，右下角会出现一个紫色 `YuE2` 浮动按钮。

无需额外安装：HTTP provider 只用 ComfyUI 自带的 `aiohttp` 和标准库；**默认的本地模型**走
`llama-cpp-python` —— 能跑 GGUF 节点的 ComfyUI 安装都已经有它。

---

## 配置写作模型

打开工作台 → 「写作模型（Provider）」。默认是**本地模型**：直接在 ComfyUI 进程内加载
`models/LLM` 里的 GGUF，生成完立刻卸载，显存还给 ComfyUI。不需要 Ollama、不需要另开服务、
不需要联网。

### 默认：本地 GGUF（models/LLM）

| 字段 | 值 |
| --- | --- |
| 类型 | Local GGUF (models/LLM) |
| 模型 | 从下拉里选，例如 `Qwen3.5-9B/qwen3.5-9b-nsfw-captioning-v5.Q6_K.gguf` |
| n_ctx | 8192（歌词很长、需要更多上下文时提到 16384） |
| n_gpu_layers | `-1` = 自动（llama.cpp 按可用显存决定放多少层到 GPU） |
| KV cache 类型 | `q8_0`（比 f16 省一半 KV 显存） |
| reasoning_budget | `0` = 不思考（编曲提示词是短结构化输出，思考只烧时间） |
| 生成后保留模型 | 默认**关闭**：生成完立即释放显存 |
| 显存不足时先释放 ComfyUI 的模型 | 默认**开启**：只在装不下时才调用 ComfyUI 的 `/free` |

点「测试」会显示：models/LLM 目录、模型数量、当前可用显存、选中模型的预计占用
（权重 + KV + 计算缓冲），以及能否全量加载。

**16 GB 显存建议**

- 优先选 **5–9 GB** 的 GGUF（9B 级别的 Q4_K_M / Q6_K / Q8_0）。下拉按占用从小到大列出，
  并标注「可全量加载 / 需部分卸载到 CPU / 显存不足」。
- 首次打开面板时会自动选中**能全量加载的最大模型**，这是质量与速度的平衡点。
- 模型越大加载越慢（要从磁盘读权重）。`生成后保留模型` 适合连续微调措辞；但只要你还要
  跑工作流，就该保持关闭，否则会和图像/视频模型抢显存。
- 实在装不下时，把 `n_gpu_layers` 设成正数（例如 20）可只把一部分层放 GPU、其余走 CPU
  —— 能跑，但明显更慢。
- 「卸载模型」按钮可随时手动把模型从显存清掉。

> **损坏的 GGUF 会被明确报出来。** 例如某个文件缺少张量时，加载会失败并返回
> `llama_model_load: error loading model: check_tensor_dims: tensor 'blk.16.attn_norm.weight' not found`。
> 换一个模型即可 —— 那不是扩展的问题，是文件不完整。

> **思考型模型。** 有些本地微调会在 JSON 里先写一个 `thinking` / `reasoning` 字段再给答案，
> 这会吃光输出预算。扩展做了三层处理：system prompt 明确禁止思考字段、拿到回复后丢弃这些
> 字段、被截断的回复仍会尝试抢救出 `style`。若模型只输出了思考，会给出明确提示而不是静默失败。

### 备选：Ollama

如果已经跑着 Ollama，也可以切过去：

```bash
ollama pull qwen3:8b
```

| 字段 | 值 |
| --- | --- |
| 类型 | Ollama (local server) |
| 模型 | `qwen3:8b`（或任何你已 pull 的文本模型） |
| 服务地址 | 留空即用 `http://127.0.0.1:11434` |

### 备选：OpenAI 兼容端点

支持 OpenAI、OpenRouter、LM Studio、vLLM、llama.cpp server 等任何实现了
`POST {base}/chat/completions` 的服务。

| 字段 | 值 |
| --- | --- |
| 类型 | OpenAI-compatible endpoint |
| 模型 | 例如 `gpt-4o-mini`、`qwen3-8b` |
| 服务地址 | 例如 `http://127.0.0.1:1234/v1`（只填主机名时会自动补 `/v1`） |
| API Key | 本地服务可留空 |

> 部分 OpenAI 兼容服务不支持 `response_format`，扩展会自动去掉它重试一次。

### 没有模型也能用

点「本地预览」（或直接在左侧随便改点什么），会立刻用**内置曲风库**拼出一份可用的
style 提示词，不调用任何模型。它比模型版本朴素，但完全可以拿去生成。

---

## 工作流程

```text
主题 / 想法（可选）
        │
        │  ① AI 写歌词 ── system = 内置《YuE2 Lyrics Writing Guide》
        │                  user   = 主题 + 曲风 + 人声 + 语言 + 篇幅
        │                  输出 {"title", "lyrics"} → 立刻走一遍下面的规范化
        ▼
歌词 + 曲风 + 人声
        │
        ├─ 本地确定性分析（每次输入自动跑，不发网络请求）
        │     · 段落识别与规范化：[Verse] / Pre-Chorus / 副歌 / 间奏 / Rap …
        │     · 语言检测：普通话 / 粤语 / 英语 / 日语 / 韩语
        │     · 声部分配：男声 / 女声 / 混唱交替与齐唱 / 纯器乐
        │     · 时长估算与结构提醒
        │
        └─ ② AI 生成提示词 ── 写作模型（可选）
              · system = 内置《YuE2 Style Prompt Writing Guide》
              · user   = 歌词 + 曲风预设 + 人声设定 + 语言 + 本地分析结果
              · 只要求模型返回 {"style", "vocal_arrangement", "notes"}
        │
        └─ 组装 → style / 规范化歌词 / 声部标注 / 编排建议 / YuE2 JSON / Python 片段
```

模型返回的 style 会被清洗：剥离代码围栏、去重、丢掉句子（超过 8 个词）和混入的中文歌词
片段（很常见的失败模式），并截断到 20 个片段。

---

## 与官方 YuE2 的对应关系

生成的 JSON 与官方 `examples/*.json` 字段一致，可以直接照搬官方 quick start：

```python
import json
from pathlib import Path
from yue2 import YuE2Pipeline

prompt = json.loads(Path("yue2_prompt.json").read_text(encoding="utf-8"))
pipe = YuE2Pipeline.from_pretrained("m-a-p/YuE2-3B", device="cuda")
song = pipe(style=prompt["style"], lyrics=prompt["lyrics"],
            cot=prompt["cot"], seed=prompt["seed"], cfg_scale=1.2)
song.save("song.flac")
pipe.close()
```

工作台里的 `cot` 选项直接对应官方三种规划模式：

| 选项 | 用途 |
| --- | --- |
| `full` | 旋律 + 和弦规划（原创歌曲，默认） |
| `melody` | 仅旋律规划（**翻唱推荐**） |
| `off` | 不做符号规划，最快 |

VAE 可选官方两个版本：`YuE2-Vae`（默认，音质更好）与 `YuE2-Vae-legacy`
（音乐性评分更高，用于复现论文结果）。

### 关于 AI 写歌词

歌词由同一个本地模型生成，契约是内置的《YuE2 Lyrics Writing Guide》（同样用 sha256
冻结）。它约束的是**能唱**，而不只是"通顺"：

- 段落标签只用 `[Intro]` / `[Verse]` / `[Pre-Chorus]` / `[Chorus]` / `[Bridge]` / `[Outro]`
  这些规范写法，段与段之间空一行；
- **副歌逐字重复**——YuE2 靠这个识别歌曲结构，所以生成结果里副歌会一模一样地出现 2–3 次；
- 中文每行控制在 7–11 字、段内字数接近，偶数行押韵；
- 按你选的篇幅决定段落数量，按曲风选择意象词汇，按人声设定调整视角（混唱时主歌换成两个
  视角、副歌写成能齐唱）。

生成后会立刻跑一遍**规范化**：段落标签统一，并且**重复的段落不再编号**——`[Verse 1]` /
`[Verse 2]` 只在内容确实不同时才出现，重复的副歌和 Pre-Chorus 保持 `[Chorus]` /
`[Pre-Chorus]`，与官方示例一致。

同时给出**质量提示**，例如"副歌只出现了一次""可唱行数偏少""你要求的是英语但检测到更像
普通话"。这些只是提示，不阻塞使用。

生成的歌词会填进歌词框，可以直接改。默认勾选「接着生成提示词」，一次点击就能拿到全部输出；
想先改歌词就把这个勾去掉。

### 关于声部标注

`[Verse 1 · Male]` 这类写法不等于官方支持的标准标签。所以：

- 「② 规范化歌词」**永远是干净的** `[Verse]` / `[Chorus]`，可以直接交给 YuE2；
- 带声部标注的版本单独放在「③」，仅供你参考，或在你确认可行时手工合并。

---

## 隐私

- **Ollama / 本地 OpenAI 兼容端点**：歌词和设定不离开这台机器。
- **远程 API**：歌词、曲风设定和内置指南会发送到该服务商。
- API Key 默认存在 `sessionStorage`（关掉标签页即失效）；勾选「记住 Key」才会写入
  `localStorage`。后端从不回传 Key。
- 歌词文本只保存在浏览器本地存储中，用于下次打开时恢复草稿。

---

## 已知限制

- 写作模型是**文本模型**，不会真的"听"音乐；它依据的是内置写作契约和你选的曲风预设。
- 语言检测是启发式的：繁体中文会判为普通话（可手动改），粤语靠特征字识别，短样本可能不准。
- 段落推断依赖空行和重复检测；建议歌词里保留 `[Verse]` / `[Chorus]` 标签以获得最稳定的结果。
- 服务地址由你填写，扩展会按要求发起请求；请只指向你信任的端点。

---

## 开发

目录结构：

```text
__init__.py              # WEB_DIRECTORY = "./web"，注册 models/LLM，导入 routes 注册端点
backend/
  version.py             # 版本唯一来源（pyproject.toml 与 __init__.py 都读它）
  catalog.py             # 35 个曲风预设 + 人声 / 情绪 / 速度 / 篇幅 / 语言 / cot 目录
  lyrics.py              # 歌词解析、规范化、语言检测、声部分配（纯函数）
  guides.py              # 内置指南加载 + sha256 完整性校验
  assembly.py            # 组装模型请求、清洗回复、生成三件套与回退 style
  routes.py              # ComfyUI aiohttp 端点，前缀 /yue2_prompt_writer
  models/
    contract.py          # 设置校验（local / ollama / openai）+ 回复提取
    local_backend.py     # 进程内加载 models/LLM 的 GGUF，含 GGUF 头部解析与显存估算
    ollama_backend.py    # Ollama /api/chat
    openai_backend.py    # OpenAI 兼容 /chat/completions
    _http.py             # 共享的 aiohttp 请求与错误映射
guides/                  # 冻结的两份契约（style 提示词 + 歌词写作），sha256 锁定
web/                     # 浮动工作台（原生 ES 模块，无构建步骤）
  main.js                # launcher + 双栏面板 + 六块可复制输出
  api/yue2.js            # 端点客户端
  styles/yue2.css        # 样式
tests/                   # 离线检查脚本
```

跑测试（不需要 pytest、ComfyUI 或额外依赖）：

```bash
python tests/run_all.py                        # 依次跑完全部检查
python tests/run_tests.py                      # 歌词引擎（纯逻辑）
python tests/check_guides.py                   # 指南完整性与必需规则
python tests/check_assembly.py                 # 请求组装、style 清洗、设置校验
python tests/check_extension_load.py           # 按 ComfyUI 的方式导入扩展、核对端点
python tests/check_gguf.py                     # GGUF 扫描与显存估算（跑真实模型目录）
python tests/run_api_tests.py                  # HTTP 端到端，需要 aiohttp（ComfyUI 自带）
python tests/run_local_model_check.py --list   # 列出 models/LLM 的 GGUF 与显存估算
python tests/run_local_model_check.py          # 真实加载 + 生成 + 卸载（需要 GPU）
python tests/run_local_model_check.py --idea "雨夜开车"  # 一次加载跑完主题 → 歌词 → 提示词
```

`tests/run_all.py` 会跳过需要 Node 的前端语法检查（`check_frontend.mjs`）如果 PATH 里没有 `node`。

> **用 ComfyUI 自带的解释器跑测试。** `backend/models/_http.py` 依赖 `aiohttp`，它随 ComfyUI
> 一起提供，普通系统 Python 里没有。用错解释器会看到 3 个「失败」，那其实是环境问题而非代码
> 问题——`run_all.py` 现在会在开跑前检查并明确提示：
>
> ```bash
> E:\ComfyUI\python_embeded\python.exe tests/run_all.py
> ```

各检查脚本覆盖的内容：

- `run_tests.py` — 歌词解析与段落编号规则（重复段落不编号）、中英日韩粤语检测、声部分配、
  `auto` 哨兵值不当作语言、style 清洗、质量提示、时长估算、空输入。
- `check_guides.py` — 两份指南的 sha256 校验，以及必需规则确实存在于正文中。
- `check_assembly.py` — 工作台默认载荷整组字段、未知值拒绝、style 清洗（CJK 与句子片段剔除、
  去重、片段上限）、JSON 回复容错（围栏 / 夹在散文里 / 未转义换行）、思考字段丢弃、
  六块输出齐全、官方 JSON 字段集、长歌词压缩、设置校验与 `api_key` 不外泄。
- `check_extension_load.py` — 用 stub `server` 与 `folder_paths` 复现 ComfyUI 的
  `load_custom_node`，确认 9 个后端模块全部导入、14 个端点全部注册、前端资源就位。
- `check_gguf.py` — 真实 `models/LLM` 目录的扫描耗时、GGUF 头部解析、投影器排除、
  显存估算随 `n_ctx` 变化、部分卸载。
- `run_api_tests.py` — 把 `backend/routes.py` 真正启动起来跑真实 HTTP，覆盖健康检查、
  目录、指南（含 404）、plan、歌词分析、本地预览、模型清单、provider 探针（含不可达）、
  generate 的回退路径、`api_key` 不出现在响应体里。
- `check_frontend.mjs` — 前端 ES 模块语法、模板字符串与 CSS 括号配平，外加输出区的回归
  断言：复制按钮必须带「复制」二字、`.yue2-copy` / `.yue2-toggle` 必须显式声明 `color`
  与字号（否则会被 ComfyUI 的全局按钮重置吃掉）、输出不得再被固定 `max-height` 裁剪、
  长内容折叠与展开控件必须存在、`.yue2-column` 必须能收缩（`min-width: 0`）、
  `.yue2-output` 与 `.yue2-section` 必须 `flex: 0 0 auto`（否则固定高的 flex 列会把
  它们压扁到一起）。

### 视觉验证（可选，不需要 ComfyUI）

两个页面直接 `<link>` 真实的 `web/styles/yue2.css`，在浏览器里打开即可：

- `tests/preview.html` — 单个输出块：确认「复制」按钮可见、折叠/展开正常，
  且**短内容也能折叠**（不是只有长块才有折叠控件）。
- `tests/preview-panel.html` — 完整面板（header + 固定高双列 + 6 个输出块）：
  页面会把量化结论写进顶部横幅，判定每个块是否被压缩或与相邻块重叠。
  内容超过面板高度时，**必须由列的滚动条承载，而不是把块压扁**。
  默认呈现折叠态；加 `?expand=1` 会先全部展开，用来验证展开后仍无重叠。

```bash
# Windows，用系统自带的 Edge，无需安装任何依赖
msedge --headless=new --window-size=760,1100 --screenshot out.png tests/preview.html
msedge --headless=new --window-size=1100,780 --screenshot panel.png tests/preview-panel.html
msedge --headless=new --window-size=1100,780 --screenshot expanded.png "tests/preview-panel.html?expand=1"
```

### 输出区交互

六个输出块（① Style 提示词 … ⑥ Python 调用片段）**行为完全一致**：

- 默认全部**折叠**成一行标题条，面板高度可预期，任何一块都不会把下面的块埋掉。
- 点击标题栏任意处，或点「展开」按钮，都可展开；展开状态在本面板存活期间保留，
  重新生成输出不会把你的展开选择重置。
- 标题栏同时是键盘可达的（`Tab` 聚焦、`Enter`/`Space` 切换），带 `aria-expanded`。

`run_local_model_check.py` 是可选的实机冒烟测试：挑一个真实 GGUF 加载到 GPU，分别计时
加载 / 生成 / 卸载，并确认卸载后显存回到基线。加 `--idea "一句主题"` 会一次加载连着跑完
**主题 → 歌词 → 提示词**。

> 如果修改了 `guides/*.md`，必须同步更新 `backend/guides.py` 里的 `source_sha256`，
> 否则扩展会拒绝使用该指南。新哈希可以用：
>
> ```bash
> python -c "import hashlib,pathlib; t=pathlib.Path('guides/yue2_style_prompt_guide_en.md').read_text(encoding='utf-8-sig').replace('\r\n','\n').rstrip()+'\n'; print(hashlib.sha256(t.encode()).hexdigest())"
> ```

---

## 许可

本扩展代码为 MIT。YuE2 权重为 CC BY-NC 4.0，模型与指南版权归其上游作者所有，不随本扩展分发。
