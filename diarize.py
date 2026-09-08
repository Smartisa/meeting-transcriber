#!/usr/bin/env python
"""pyannote 声纹说话人分离脚本（离线，纯 CPU）。

用法示例：
  DZ=/Volumes/ExtendHD/Environment/claude-skills/audio-transcribe/diarize.py
  # 全量
  python "$DZ" --input 录音.m4a --segments /path/to/xxx_raw.txt --out /path/to/xxx_diarized.txt
  # 部分：从 1:29:24 起（切段后时间戳自动加回偏移，段从 whisper _raw.txt 解析）
  python "$DZ" --input 录音.m4a --segments /path/to/xxx_raw.txt --out /path/to/xxx_diarized.txt --start 1:29:24
"""
import argparse
import os
import re
import subprocess
import tempfile

BASE = os.environ.get("AUDIO_TRANSCRIBE_BASE", "/Volumes/ExtendHD/Environment")
FFMPEG = os.environ.get("AUDIO_TRANSCRIBE_FFMPEG",
                        f"{BASE}/miniconda3/miniconda3/envs/Tools/bin/ffmpeg")
TMPDIR = os.environ.get("AUDIO_TRANSCRIBE_TMP", f"{BASE}/tmp/audio-transcribe")
# 本地偏移后的 pyannote pipeline 配置（含两个组件模型的本地 .bin 路径）
PYANNOTE_CONFIG = os.environ.get(
    "AUDIO_TRANSCRIBE_PYANNOTE_CONFIG",
    f"{BASE}/models/pyannote/diarization-3.1/config.yaml")

SEG_PAT = re.compile(
    r"\[(\d+):(\d+):([\d.]+) - (\d+):(\d+):([\d.]+)\] (.*)")


def parse_time(s):
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


def cut(input_path, start, end):
    """ffmpeg 归一化为 16kHz 单声道 wav（可选切片），返回临时文件路径。"""
    os.makedirs(TMPDIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="dz_", suffix=".wav", dir=TMPDIR)
    os.close(fd)
    os.unlink(tmp_path)

    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", input_path]
    if start is not None:
        cmd += ["-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", tmp_path]

    print(f"[ffmpeg] start={start} end={end} -> {os.path.basename(tmp_path)}", flush=True)
    subprocess.run(cmd, check=True)
    return tmp_path


def parse_segments(raw_path):
    """解析 whisper _raw.txt 的 [起-止] 文本 段，返回 [(start, end, text), ...]（绝对时间）。"""
    segs = []
    with open(raw_path, encoding="utf-8") as fp:
        for line in fp:
            m = SEG_PAT.match(line.strip())
            if not m:
                continue
            h1, m1, s1, h2, m2, s2, text = m.groups()
            start = 3600 * int(h1) + 60 * int(m1) + float(s1)
            end = 3600 * int(h2) + 60 * int(m2) + float(s2)
            segs.append((start, end, text))
    return segs


def main():
    p = argparse.ArgumentParser(description="pyannote 声纹说话人分离 + whisper 段对齐")
    p.add_argument("--input", required=True, help="音频路径（原 m4a/mp3/wav）")
    p.add_argument("--segments", required=True, help="whisper 的 <名>_raw.txt（带 [起-止] 绝对时间戳）")
    p.add_argument("--out", required=True, help="输出 <名>_diarized.txt")
    p.add_argument("--start", default=None, help="起始时间：秒或 HH:MM:SS（与转写时一致）")
    p.add_argument("--end", default=None, help="结束时间：秒或 HH:MM:SS")
    p.add_argument("--num-speakers", type=int, default=None, help="可选：指定说话人数")
    args = p.parse_args()

    start = parse_time(args.start)
    end = parse_time(args.end)
    segs = parse_segments(args.segments)
    if not segs:
        raise SystemExit(f"未从 --segments 解析到任何段: {args.segments}")
    print(f"[segments] {len(segs)} 段, 首 {fmt(segs[0][0])} 末 {fmt(segs[-1][1])}", flush=True)

    wav = cut(args.input, start, end)
    try:
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(PYANNOTE_CONFIG)
        pipeline.to(torch.device("cpu"))
        kw = {"num_speakers": args.num_speakers} if args.num_speakers else {}
        diar = pipeline(wav, **kw)
        turns = [(t.start, t.end, spk) for t, _, spk in diar.itertracks(yield_label=True)]
        print(f"[diar] {len(turns)} 段说话人片段, 识别到 {len({t[2] for t in turns})} 位", flush=True)

        offset = start if start is not None else 0.0

        def speaker_for(s, e):
            best, best_ov = None, 0.0
            for ts, te, spk in turns:
                ov = min(e, te) - max(s, ts)
                if ov > best_ov:
                    best_ov, best = ov, spk
            return best or "UNKNOWN"

        with open(args.out, "w", encoding="utf-8") as f:
            for s, e, text in segs:
                # 段时间戳已是绝对时间（_raw.txt 自转写起即含 --start 偏移），直接写出；
                # 与声纹片段（相对切段起点 0）比较时需减去偏移。
                spk = speaker_for(s - offset, e - offset)
                f.write(f"[{fmt(s)} - {fmt(e)}] 【{spk}】 {text}\n")
                f.flush()
                print(f"{fmt(s)} 【{spk}】 {text}", flush=True)
        print("DONE", flush=True)
    finally:
        try:
            os.unlink(wav)
            print(f"[ffmpeg] removed temp {os.path.basename(wav)}", flush=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()