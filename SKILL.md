---
name: audio-transcribe
description: 把会议/录音/视频里的音频转成中文文字（Whisper 语音识别），支持整段或指定时间段（--start/--end）转写，并产出会议摘要、任务摘要，且对正文中的黑话/专业术语做标注与解释。当用户说 转文字 / 转写 / 语音转文字 / 录音转文字 / 音频转中文 / 把这段音频转成文本 / 从某分钟转到最后 / 生成字幕 / 会议纪要 / 会议摘要 / transcribe / 语音识别 等时使用。基于 faster-whisper（CPU/int8），模型与依赖可全落外置盘；转写后用 subAgent 分块校正标点/分段/清理口癖，再由主 session 产出摘要与术语解释。
---

# audio-transcribe — 会议录音转文字 + 纪要 + 黑话标注

用 faster-whisper（CTranslate2 int8，纯 CPU）把音频转成中文，支持**整段**或**指定时间段**（`--start`/`--end`）；转写后用 subAgent 分块专业化优化，产出会议摘要、任务摘要，并**标注解释黑话/术语**。

## 环境常量（默认落外置盘，路径均可环境变量覆盖）

| 变量 | 默认值 | 作用 |
|---|---|---|
| `AUDIO_TRANSCRIBE_BASE` | `/Volumes/ExtendHD/Environment` | 依赖/模型/临时文件根目录 |
| `AUDIO_TRANSCRIBE_FFMPEG` | `$BASE/.../Tools/bin/ffmpeg` | ffmpeg 路径 |
| `AUDIO_TRANSCRIBE_TMP` | `$BASE/tmp/audio-transcribe` | 中间产物目录 |
| `AUDIO_TRANSCRIBE_PYTHON` | `$BASE/.../envs/audio-transcribe/bin/python` | conda 专用环境 Python（`setup.sh` 构建：torch + faster-whisper + pyannote） |
| `AUDIO_TRANSCRIBE_PYANNOTE_CONFIG` | `$BASE/models/pyannote/diarization-3.1/config.yaml` | 离线 pyannote pipeline 配置 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 模型下载镜像（huggingface.co 被墙时可用） |
| `HF_HOME` | `$BASE/models/whisper` | 模型缓存目录 |

默认值按作者本机「外置盘」习惯设定；他人改动默认值只需设置对应环境变量。

本 skill 目录（即本仓库根目录）：
- `transcribe.py` — 转写脚本（含 `--start/--end`）
- `diarize.py` — 声纹说话人分离（离线 pyannote + whisper 段对齐）
- `setup.sh` — 幂等初始化：conda 环境 audio-transcribe + 依赖 + whisper 模型
- `setup_diarize.sh` — pyannote 声纹模型准备（需 HF_TOKEN，curl 走镜像、完全离线）
- `glossary.example.md` — 领域黑话/术语表模板（用户可预填，标注时优先采用）

## 流程

### 0. 环境检查（缺失才 setup）
```bash
PY="${AUDIO_TRANSCRIBE_BASE:-/Volumes/ExtendHD/Environment}/miniconda3/miniconda3/envs/audio-transcribe/bin/python"
"$PY" -c "import faster_whisper" 2>/dev/null && echo ok || bash ./setup.sh medium
```

### 1. 探测音频
```bash
ffmpeg -v error -show_entries format=duration -show_entries stream=codec_name,sample_rate,channels \
  -of default=noprint_wrappers=1 "<输入文件>"
```
拿时长（秒）。**耗时估算**：i7-9750H（6核12线程）上 medium ≈ 0.6–0.7× 实时，large-v3 约慢一倍、small 快近一倍。先把估时告知用户，长录音默认后台跑，模型选型（medium/small/large-v3）让用户拍板。

### 2. 转写（整段或部分）
```bash
# 整段
"$PY" transcribe.py --input "<文件>" --out-dir "$AUDIO_TRANSCRIBE_TMP" --model medium --language zh
# 部分：从 1:29:24 到末尾
"$PY" transcribe.py --input "<文件>" --start 1:29:24 --out-dir "$AUDIO_TRANSCRIBE_TMP"
# 前 60 秒（冒烟/抽查）
"$PY" transcribe.py --input "<文件>" --end 60 --out-dir "$AUDIO_TRANSCRIBE_TMP"
```
脚本内部：ffmpeg 归一化到 16kHz 单声道临时 wav（有 `--start/--end` 时切片），转写后时间戳自动加回 `--start` 偏移 → `_raw.txt` 里是**绝对时间**，临时 wav 转完即删。产物：
- `<名>_raw.txt`（带 `[起-止]` 绝对时间戳，对照/核验用）
- `<名>_text.txt`（纯文本逐段一行，喂后处理用）

### 3. 全量跑法（长录音）
用 `run_in_background: true` 启动；脚本逐段 flush，可随时 `tail` `_raw.txt` 看进度，完成后等后台通知。多份录音可并行（各自降 `--threads`），或按「短的先跑」串行。

### 4. 专业化优化（subAgent 分块并行）
读 `<名>_text.txt`，按 **~5000 字/块**切分，并行派发 subAgent 逐块润色：补全中文标点、按语义分段、清理「呃/嗯/然后…然后」等口癖与明显重复；**不改原意、不增删实质内容**。主 session 按序合并 → 写最终 `transcription/<名>.txt`（部分转写的在首行注「转写起点 xx:xx:xx」）。

### 5. 生成摘要（每份录音，主 session 通读优化后全文产出）
- `会议摘要`：日期、参与者（可推断）、主题、关键讨论、结论/决策；
- `任务摘要`：待办/后续任务，含负责人与时间点（原文有则记，无则只列任务）。
写入 `transcription/<名前缀>_会议摘要.md`、`<名前缀>_任务摘要.md`。

### 6. 黑话/术语标注解释（合并进第 5 步的 `会议摘要`，或独立一节）
1. 识别正文中的领域术语、缩写、专有名词、黑话（如 MCP、多智能体、规格文档驱动、session、hanis 工具…）。
2. 首次出现处内联标注：`MCP（Model Context Protocol）`。
3. 文末附「术语/黑话对照表」逐条解释；**优先用 `glossary.example.md` 预填项**，缺失的由 agent 依上下文 + 常识推断并标 `（推断）`。
产出：在每份 `会议摘要.md` 末尾追加「术语/黑话解释」一节。

### 7.（可选）音色说话人分离——从音频层面区分谁在说
转写只给文字，不知道是谁说的；需要从**音色**区分时用 `diarize.py`：
```bash
"$PY" diarize.py --input "<原音频>" --segments "$AUDIO_TRANSCRIBE_TMP/<名>_raw.txt" \
  --out "$AUDIO_TRANSCRIBE_TMP/<名>_diarized.txt" [--start HH:MM:SS] [--num-speakers N]
```
- 前置：`bash setup_diarize.sh`（需 HF_TOKEN 且已在 HF 网页接受 pyannote 两个模型授权）；产出为**离线本地模型**，不联网。
- 输出每段带 `【Speaker_K】`（K=声纹簇编号，不等同人名）。
- **定名**：LLM/subAgent 按内容把 Speaker_K 映射为人名（边老师/学生/王老师…），产出 `transcription/<名>_带说话人.txt`。
- 只有「谁在何时说话」由声纹保证；「叫什么名字」靠 LLM 内容映射（无声音样本 enrollment）。

## 参数说明（transcribe.py）

| 参数 | 默认 | 说明 |
|---|---|---|
| `--input` | 必填 | 音频路径（m4a/mp3/wav 等） |
| `--out-dir` | 必填 | 原始转写输出目录 |
| `--start` | 无 | 起始时间，秒或 `HH:MM:SS`（部分转写） |
| `--end` | 无 | 结束时间，秒或 `HH:MM:SS` |
| `--model` | medium | tiny/base/small/medium/large-v2/large-v3 |
| `--language` | zh | `auto` 自动检测；中文建议显式 `zh` |
| `--beam-size` | 5 | 越大越准越慢 |
| `--compute-type` | int8 | CPU 推荐 int8 |
| `--threads` | 12 | CPU 线程数 |
| `--no-vad` | 关 | 默认开静音检测（长录音更省时） |
| `--initial-prompt` | 中文标点引导 | 优化中文与标点 |

## 目录约定

```
transcription/                          # 最终交付（扁平）
├── <日期>.txt                          # 优化后转写（部分转写首行注范围）
├── <日期>_会议摘要.md                  # 含「术语/黑话解释」一节
└── <日期>_任务摘要.md

$AUDIO_TRANSCRIBE_TMP/                  # 中间产物（切段 wav、_raw.txt，可清理）
```

## 注意事项

- 依赖/模型/缓存/临时文件默认落外置盘，可通过环境变量覆盖到任意本地路径。
- 模型下载默认走 `hf-mirror.com` 镜像；如网络可直连 huggingface.co，可 `export HF_ENDPOINT=https://huggingface.co`。
- 转写是前置步骤；优化与摘要 token 消耗大，优化务必分块并行。
- 核验无漏段：`_raw.txt` 首段时间戳 ≈ 起始（整段则 ≈0s）、末段 ≈ 总时长。
- 转写本身不做说话人分离；需要区分多人时复用本 skill 第 7 步（`diarize.py` 音色分离 + LLM 定名）。
- 首次使用前把 `glossary.example.md` 复制为 `glossary.md` 并填入你的领域黑话，术语解释会更准。