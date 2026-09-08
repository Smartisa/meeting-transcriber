#!/usr/bin/env bash
# 幂等环境初始化：新建 conda 专用环境 audio-transcribe（录音转文字整装：faster-whisper + pyannote）。
# 依赖/模型/缓存全部落外置盘（AUDIO_TRANSCRIBE_BASE、AUDIO_TRANSCRIBE_PYTHON 可覆盖）。
# 用法：bash setup.sh [model]      例如 bash setup.sh medium / bash setup.sh none
set -euo pipefail

BASE="${AUDIO_TRANSCRIBE_BASE:-/Volumes/ExtendHD/Environment}"
CONDA_BIN="${AUDIO_TRANSCRIBE_CONDA:-/Volumes/ExtendHD/Environment/miniconda3/miniconda3/bin/conda}"
PY="${AUDIO_TRANSCRIBE_PYTHON:-/Volumes/ExtendHD/Environment/miniconda3/miniconda3/envs/audio-transcribe/bin/python}"
MODEL="${1:-medium}"

export CONDA_PKGS_DIRS="$BASE/conda-pkgs"
export PIP_CACHE_DIR="$BASE/caches/pip"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HOME="${HF_HOME:-$BASE/models/whisper}"
export MPLCONFIGDIR="$BASE/tmp/matplotlib"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$BASE/conda-pkgs" "$BASE/caches/pip" "$BASE/models/whisper" "$BASE/tmp/matplotlib"

echo "[setup] 1/3 conda 环境 audio-transcribe ..."
if [ ! -x "$PY" ]; then
  "$CONDA_BIN" create -n audio-transcribe -y --solver classic python=3.11
fi

echo "[setup] 2/3 依赖（torch 2.2.2 + numpy<2 固定，faster-whisper + pyannote-audio + matplotlib）..."
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q "torch==2.2.2" "torchaudio==2.2.2" "numpy<2"
"$PY" -m pip install -q faster-whisper "pyannote-audio>=3.3,<3.4" matplotlib

if [ "$MODEL" != "none" ]; then
  echo "[setup] 3/3 whisper 模型 $MODEL ..."
  "$PY" -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-${MODEL}')"
fi

echo "[setup] done。pyannote 声纹模型准备见 setup_diarize.sh（需 HF_TOKEN，模型已接受授权）"