#!/usr/bin/env bash
# pyannote 声纹模型准备（免 hub 下载路径，curl 走 hf-mirror + token，完全离线）。
# 前提：已在 huggingface.co 网页接受两个门控模型授权，并持有 HF_TOKEN。
# 用法：HF_TOKEN=hf_xxx bash setup_diarize.sh
set -euo pipefail

BASE="${AUDIO_TRANSCRIBE_BASE:-/Volumes/ExtendHD/Environment}"
ROOT="$BASE/models/pyannote"
TOK="${HF_TOKEN:?需要设置 HF_TOKEN（先到 huggingface.co/settings/tokens 生成，并接受 pyannote 两个模型授权）}"
MIRROR=https://hf-mirror.com/pyannote

mkdir -p "$ROOT/diarization-3.1" "$ROOT/segmentation-3.0" "$ROOT/wespeaker"

dl() {
  curl -sS -m 300 -L -H "Authorization: Bearer $TOK" -o "$2" "$1" \
    || { echo "下载失败: $1"; exit 1; }
}

echo "[setup_diarize] 下载三个模型仓库（hf-mirror + token）..."
dl "$MIRROR/speaker-diarization-3.1/resolve/main/config.yaml"   "$ROOT/diarization-3.1/config.yaml"
dl "$MIRROR/speaker-diarization-3.1/resolve/main/handler.py"     "$ROOT/diarization-3.1/handler.py"
dl "$MIRROR/segmentation-3.0/resolve/main/config.yaml"           "$ROOT/segmentation-3.0/config.yaml"
dl "$MIRROR/segmentation-3.0/resolve/main/pytorch_model.bin"     "$ROOT/segmentation-3.0/pytorch_model.bin"
dl "$MIRROR/wespeaker-voxceleb-resnet34-LM/resolve/main/config.yaml" "$ROOT/wespeaker/config.yaml"
dl "$MIRROR/wespeaker-voxceleb-resnet34-LM/resolve/main/pytorch_model.bin" "$ROOT/wespeaker/pytorch_model.bin"

echo "[setup_diarize] 重写 pipeline 配置指向本地权重（离线加载）..."
cat > "$ROOT/diarization-3.1/config.yaml" <<YAML
version: 3.1.0

pipeline:
  name: pyannote.audio.pipelines.SpeakerDiarization
  params:
    clustering: AgglomerativeClustering
    embedding: $ROOT/wespeaker/pytorch_model.bin
    embedding_batch_size: 32
    embedding_exclude_overlap: true
    segmentation: $ROOT/segmentation-3.0/pytorch_model.bin
    segmentation_batch_size: 32

params:
  clustering:
    method: centroid
    min_cluster_size: 12
    threshold: 0.7045654963945799
  segmentation:
    min_duration_off: 0.0
YAML
echo "[setup_diarize] done：pipeline 已可离线加载（diarize.py 会用该配置）"