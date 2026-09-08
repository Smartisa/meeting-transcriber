# meeting-transcriber

把会议/录音转成中文文字与纪要的 **Claude Code Skill** —— 基于 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 本地离线转写，支持**按时间段切片**转写，由 **AI Agent 校正标点、分段与口癖**，自动产出**会议摘要、任务清单**，并**标注解释领域黑话/术语**。纯 CPU、零联网。

## 特性

- **本地离线转写**：faster-whisper（CTranslate2 int8），纯 CPU 可跑，不依赖云 API。
- **自定义时间段**：`--start` / `--end` 按时间戳切片，只转某一段（如「从 1:29:24 到结尾」）。
- **Agent 保证正确率**：转写后由 AI Agent 分块校正标点、按语义分段、清理口癖与重复。
- **会议摘要 + 任务摘要**：自动产出会议概览、关键讨论、结论决策，以及待办清单。
- **黑话/术语标注解释**：识别领域术语并在首次出现处内联标注，文末附「术语对照表」；支持预填术语表提升准确性。
- **音色说话人分离**（可选）：pyannote 离线声纹分离，逐段输出 `Speaker_K` 标签，再由 AI Agent 映射为人名。

## 快速开始

### 依赖

- Python 3.8+
- `ffmpeg` / `ffprobe`（可执行路径）
- 可选：外置盘 / 大容量目录用于存放模型（默认 `~1.5GB` medium 模型）

### 初始化（幂等）

```bash
bash setup.sh medium
```

`setup.sh` 会：创建 **conda 专用环境 `audio-transcribe`**（torch + faster-whisper + pyannote 整装）→ 安装依赖 → 预下载指定模型（`tiny/base/small/medium/large-v2/large-v3`）。

可选：声纹分离模型准备（需 [HuggingFace token](https://huggingface.co/settings/tokens) 且已在 HF 网页接受两个 pyannote 模型授权）：

```bash
HF_TOKEN=hf_xxx bash setup_diarize.sh
```

### 转写

```bash
PY="$AUDIO_TRANSCRIBE_BASE/venvs/faster-whisper/bin/python"   # 或你 venv 里的 python

# 整段转中文
"$PY" transcribe.py --input 会议.m4a --out-dir ./out --model medium --language zh

# 只转某一段：从 1:29:24 到结尾
"$PY" transcribe.py --input 会议.m4a --start 1:29:24 --out-dir ./out

# 冒烟测试：前 60 秒
"$PY" transcribe.py --input 会议.m4a --end 60 --out-dir ./out
```

产出 `./out/<名>_raw.txt`（带绝对时间戳）与 `<名>_text.txt`（纯文本）。

### 说话人分离（可选）

```bash
"$PY" diarize.py --input 会议.m4a --segments ./out/会议_raw.txt \
  --out ./out/会议_diarized.txt [--start 1:29:24] [--num-speakers 3]
```

输出逐段带 `【Speaker_K】` 标签（K 为声纹簇编号）。随后由 AI Agent 按内容把 `Speaker_K` 映射为人名，并用 `merge_speakers.py` 机械合并成段（正文零改动）：

```bash
python merge_speakers.py --diarized out/会议_diarized.txt \
  --out transcription/会议/会议_带说话人.txt \
  --map "SPEAKER_00=边老师,SPEAKER_04=王老师" --num-speakers 2
```

## 作为 Claude Code Skill 使用

将本目录软链进 Claude Code 的 skills 目录即可：

```bash
ln -s "$(pwd)" ~/.claude/skills/audio-transcribe
```

之后对 Claude Code 说「把这段录音转成中文」「从 1:29:24 转到最后」即可触发；转写后 Claude 会分块校正、产出摘要与术语解释。

## 配置（路径覆盖）

默认路径按作者的「外置盘」习惯设定，可用环境变量覆盖到任意本地位置：

| 变量 | 默认值 | 作用 |
|---|---|---|
| `AUDIO_TRANSCRIBE_BASE` | `/Volumes/ExtendHD/Environment` | 依赖/模型/临时文件根目录 |
| `AUDIO_TRANSCRIBE_FFMPEG` | `$BASE/.../Tools/bin/ffmpeg` | ffmpeg 可执行路径 |
| `AUDIO_TRANSCRIBE_TMP` | `$BASE/tmp/audio-transcribe` | 中间产物目录 |
| `AUDIO_TRANSCRIBE_PYTHON` | `$BASE/.../envs/audio-transcribe/bin/python` | conda 专用环境 Python |
| `AUDIO_TRANSCRIBE_PYANNOTE_CONFIG` | `$BASE/models/pyannote/diarization-3.1/config.yaml` | 离线 pyannote pipeline 配置 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 模型下载镜像 |
| `HF_HOME` | `$BASE/models/whisper` | 模型缓存目录 |

> 网络可直连 huggingface.co 时，可 `export HF_ENDPOINT=https://huggingface.co`。

## 目录约定

```
transcription/                        # 最终交付（按录音日期分文件夹，不平铺）
└── <日期>/
    ├── <日期>.txt                    # 优化后转写
    ├── <日期>_带说话人.txt           # 说话人定名版（可选）
    ├── <日期>_会议摘要.md            # 含「术语/黑话解释」一节
    └── <日期>_任务摘要.md

$AUDIO_TRANSCRIBE_TMP/                # 中间产物（切段 wav、_raw.txt）
```

## 工作流

1. **探测**：ffprobe 拿时长，估算转写耗时（medium ≈ 0.6–0.7× 实时）。
2. **转写**：ffmpeg 归一化到 16kHz 单声道（可切片）→ faster-whisper（`language=zh`、VAD、beam search）→ 带绝对时间戳的原始文本。
3. **优化**：AI Agent 分块并行校正标点/分段/口癖。
4. **产出**：会议摘要 + 任务摘要 + 黑话/术语解释。
5. **（可选）说话人分离**：pyannote 声纹分离 → `Speaker_K` 标签 → AI Agent 映射人名。

## 黑话/术语标注

1. 复制模板并按需填写你的领域术语：

   ```bash
   cp glossary.example.md glossary.md
   ```

2. 转写后 Agent 会识别正文术语、首次出现处内联标注、文末生成对照表；未在 `glossary.md` 预填的条目由 Agent 依上下文推断并标记 `（推断）`。

## License

[MIT](./LICENSE)