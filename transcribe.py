#!/usr/bin/env python
"""faster-whisper 录音转写脚本（Intel Mac / CPU 优化）。

依赖：conda 环境 audio-transcribe（/Volumes/ExtendHD/Environment/miniconda3/miniconda3/envs/audio-transcribe）内的 faster-whisper。
模型、镜像缓存、临时 wav 全部落外置盘（不写内置盘）。

用法示例：
  TRANSCRIBE=/Volumes/ExtendHD/Environment/claude-skills/audio-transcribe/transcribe.py
  # 全量
  python "$TRANSCRIBE" --input 录音.m4a --out-dir /Volumes/ExtendHD/Environment/tmp/audio-transcribe
  # 部分：从 1:29:24 到末尾
  python "$TRANSCRIBE" --input 录音.m4a --start 1:29:24 --out-dir /Volumes/ExtendHD/Environment/tmp/audio-transcribe
  # 前 60 秒（冒烟测试）
  python "$TRANSCRIBE" --input 录音.m4a --end 60 --out-dir .../tmp
"""
import argparse
import os
import subprocess
import sys
import tempfile

# 路径可用环境变量覆盖；默认值按作者本机「外置盘」习惯（可自行改成任意本地路径）。
BASE = os.environ.get("AUDIO_TRANSCRIBE_BASE", "/Volumes/ExtendHD/Environment")
FFMPEG = os.environ.get("AUDIO_TRANSCRIBE_FFMPEG",
                        f"{BASE}/miniconda3/miniconda3/envs/Tools/bin/ffmpeg")
TMPDIR = os.environ.get("AUDIO_TRANSCRIBE_TMP", f"{BASE}/tmp/audio-transcribe")

# 镜像与缓存：优先尊重用户已有的 HF_ENDPOINT/HF_HOME，否则用镜像 + 外置盘缓存，避免写内置盘。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HOME", f"{BASE}/models/whisper")

from faster_whisper import WhisperModel  # noqa: E402


def parse_time(s):
    """接受秒数或 HH:MM:SS / MM:SS，返回浮点秒；None 原样返回。"""
    if s is None:
        return None
    s = str(s).strip()
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 3:
            h, m, sec = parts
            return int(h) * 3600 + int(m) * 60 + float(sec)
        if len(parts) == 2:
            m, sec = parts
            return int(m) * 60 + float(sec)
        raise SystemExit(f"无法解析时间: {s}")
    return float(s)


def fmt(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def normalize(input_path, start, end):
    """ffmpeg 归一化为 16kHz 单声道 wav（可选 -ss/-to 切片），返回临时文件路径。"""
    os.makedirs(TMPDIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="cut_", suffix=".wav", dir=TMPDIR)
    os.close(fd)
    os.unlink(tmp_path)  # ffmpeg 会重建，避免占用

    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", input_path]
    if start is not None:
        cmd += ["-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp_path]

    print(f"[ffmpeg] start={start} end={end} -> {os.path.basename(tmp_path)}", flush=True)
    subprocess.run(cmd, check=True)
    return tmp_path


def main():
    p = argparse.ArgumentParser(description="faster-whisper 转写")
    p.add_argument("--input", required=True, help="音频路径（m4a/mp3/wav 等）")
    p.add_argument("--out-dir", required=True, help="输出目录，写 <名>_raw.txt 与 <名>_text.txt")
    p.add_argument("--start", default=None, help="起始时间：秒或 HH:MM:SS")
    p.add_argument("--end", default=None, help="结束时间：秒或 HH:MM:SS")
    p.add_argument("--model", default="medium",
                   help="tiny/base/small/medium/large-v2/large-v3，默认 medium")
    p.add_argument("--language", default="zh", help="目标语言，默认 zh；用 auto 可自动检测")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--threads", type=int, default=12, help="CPU 线程数，默认 12")
    p.add_argument("--compute-type", default="int8", help="int8 / float32")
    p.add_argument("--no-vad", action="store_true", help="关闭静音检测（默认开启）")
    p.add_argument("--initial-prompt", default="以下是普通话的简体中文转写，包含正确标点符号。")
    args = p.parse_args()

    start = parse_time(args.start)
    end = parse_time(args.end)

    print(f"[model] loading {args.model} (int8, cpu) ...", flush=True)
    model = WhisperModel(args.model, device="cpu",
                         compute_type=args.compute_type, cpu_threads=args.threads)

    tmp_path = normalize(args.input, start, end)
    try:
        segments, info = model.transcribe(
            tmp_path,
            language=args.language,
            beam_size=args.beam_size,
            vad_filter=not args.no_vad,
            initial_prompt=args.initial_prompt,
        )
        print(f"lang={info.language} duration={info.duration:.1f}s", flush=True)

        os.makedirs(args.out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(args.input))[0]
        raw_path = os.path.join(args.out_dir, f"{stem}_raw.txt")
        text_path = os.path.join(args.out_dir, f"{stem}_text.txt")

        offset = start if start is not None else 0.0
        with open(raw_path, "w", encoding="utf-8") as raw, \
             open(text_path, "w", encoding="utf-8") as txt:
            for seg in segments:
                text = seg.text.strip()
                raw.write(f"[{fmt(seg.start + offset)} - {fmt(seg.end + offset)}] {text}\n")
                raw.flush()
                txt.write(text + "\n")
                txt.flush()
                print(f"{fmt(seg.start + offset)} -> {fmt(seg.end + offset)}  {text}", flush=True)

        print("DONE", flush=True)
    finally:
        try:
            os.unlink(tmp_path)
            print(f"[ffmpeg] removed temp {os.path.basename(tmp_path)}", flush=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()