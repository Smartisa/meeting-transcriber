#!/usr/bin/env python
"""说话人合并脚本：把 diarize.py 产出的【SPEAKER_K】逐行转写，按人名映射合并成段。

定位：diarize（声纹切分）→ LLM 定名（确定每个簇是谁、是否要并入主簇）→ 本脚本做机械合并。
本脚本只做确定性文本操作，不做任何内容判断；定名与碎片归属判断由 LLM 给出 --map。

用法示例：
  MS=/Volumes/ExtendHD/Environment/claude-skills/audio-transcribe/merge_speakers.py
  # 指定映射（未列出的簇按 --num-speakers 自动并入主簇）
  python "$MS" --diarized xxx_diarized.txt --out xxx_带说话人.txt \
      --map "SPEAKER_00=边老师,SPEAKER_04=王老师,SPEAKER_06=学生" --num-speakers 3
  # 关闭自动并入（未映射簇原样保留并标 UNKNOWN）
  python "$MS" --diarized xxx_diarized.txt --out out.txt --map "SPEAKER_00=边老师" --no-auto-merge
"""
import argparse
import re
import sys

LINE_PAT = re.compile(r"\[(\d+):(\d+):([\d.]+) - (\d+):(\d+):([\d.]+)\] 【([^】]+)】 (.*)")
FILLERS = {"嗯", "嗯,", "嗯，", "对", "对,", "对，", "好", "好,", "好，", "是", "是的", "哎", "啊", "哦"}


def to_sec(h, m, s):
    return 3600 * int(h) + 60 * int(m) + float(s)


def fmt(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    return f"{h:02d}:{m:02d}:{sec % 60:05.2f}"


def parse_lines(path):
    rows = []
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            m = LINE_PAT.match(line.strip())
            if not m:
                continue
            h1, m1, s1, h2, m2, s2, spk, text = m.groups()
            rows.append({"s": to_sec(h1, m1, s1), "e": to_sec(h2, m2, s2),
                         "spk": spk, "text": text.strip()})
    return rows


def main():
    p = argparse.ArgumentParser(description="SPEAKER_K → 人名合并成段")
    p.add_argument("--diarized", required=True, help="diarize.py 的输出文件")
    p.add_argument("--out", required=True, help="输出文件（逐段 【人名】 正文）")
    p.add_argument("--map", default="", help="簇→人名映射，逗号分隔：SPEAKER_00=边老师,SPEAKER_04=王老师")
    p.add_argument("--num-speakers", type=int, default=None,
                   help="主簇数量：按总发言时长取前 N 簇为主簇，其余碎片自动并入时间最近的主簇")
    p.add_argument("--no-auto-merge", action="store_true", help="禁止碎片自动并入（未映射簇保留原标签）")
    p.add_argument("--mark-fragments", action="store_true", help="被并入的碎片段末尾追加 (?)")
    args = p.parse_args()

    name_of = {}
    for pair in filter(None, (x.strip() for x in args.map.split(","))):
        k, _, v = pair.partition("=")
        name_of[k.strip()] = v.strip()

    rows = parse_lines(args.diarized)
    if not rows:
        sys.exit(f"未解析到任何段: {args.diarized}")

    # 主簇：--map 里出现的簇；给了 --num-speakers 时按总时长取前 N 簇为准
    if args.num_speakers is not None:
        by_dur = {}
        for r in rows:
            by_dur[r["spk"]] = by_dur.get(r["spk"], 0) + (r["e"] - r["s"])
        mains = [k for k, _ in sorted(by_dur.items(), key=lambda kv: -kv[1])[:args.num_speakers]]
    else:
        mains = [k for k in name_of if any(r["spk"] == k for r in rows)]
    if not mains:
        sys.exit("没有可用的主簇：请提供 --map 或 --num-speakers")

    # 1) 碎片并入：时间上离哪个主簇的相邻发言最近
    for r in rows:
        if r["spk"] in mains or args.no_auto_merge:
            continue
        best, best_gap = None, None
        for m_ in mains:
            gap = min(abs(r["s"] - q["e"]) for q in rows if q["spk"] == m_ and q["e"] <= r["s"] + 1e-6) \
                if any(q["spk"] == m_ and q["e"] <= r["s"] + 1e-6 for q in rows) else None
            gap2 = min(abs(q["s"] - r["e"]) for q in rows if q["spk"] == m_ and q["s"] >= r["e"] - 1e-6) \
                if any(q["spk"] == m_ and q["s"] >= r["e"] - 1e-6 for q in rows) else None
            cands = [g for g in (gap, gap2) if g is not None]
            if cands:
                g = min(cands)
                if best_gap is None or g < best_gap:
                    best, best_gap = m_, g
        if best is not None:
            r["from"] = r["spk"]
            r["spk"] = best
            if args.mark_fragments:
                r["text"] = r["text"] + " (?)"

    # 2) UNKNOWN/超短应答并入前一段
    merged = []
    for r in rows:
        prev = merged[-1] if merged else None
        tiny = r["text"] in FILLERS or len(r["text"]) <= 2
        if prev and (r["spk"] == "UNKNOWN" or (tiny and r["spk"] != prev["spk"])):
            prev["tail"].append(r["text"] + " (?)")
            continue
        if prev and r["spk"] == prev["spk"]:
            prev["parts"].append(r["text"])
            prev["e"] = r["e"]
        else:
            merged.append({"spk": r["spk"], "s": r["s"], "e": r["e"],
                           "parts": [r["text"]], "tail": []})

    # 3) 写盘：正文一字不改，段内拼接（无标点边界用空格隔开）
    PUNC = "。，！？；：、,.!?;: "

    def join_parts(parts):
        out = ""
        for t in parts:
            if out and out[-1] not in PUNC and t and t[0] not in PUNC:
                out += " "
            out += t
        return out

    with open(args.out, "w", encoding="utf-8") as f:
        for seg in merged:
            body = join_parts(seg["parts"])
            if seg["tail"]:
                body = body + " " + " ".join(seg["tail"])
            name = name_of.get(seg["spk"], seg["spk"])
            f.write(f"【{name}】 {body}\n\n")
    print(f"DONE: {len(merged)} 段 -> {args.out}", flush=True)


if __name__ == "__main__":
    main()