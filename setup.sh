#!/usr/bin/env bash
# 幂等环境初始化：创建独立 venv、安装 faster-whisper、预下载模型（全部落外置盘）。
# 用法：bash setup.sh [model]    例如 bash setup.sh medium / bash setup.sh none
set -euo pipefail

# 依赖/模型安装根目录与建 venv 所用的 Python，可用环境变量覆盖。
BASE="${AUDIO_TRANSCRIBE_BASE:-/Volumes/ExtendHD/Environment}"
PY_TOOLS="${AUDIO_TRANSCRIBE_PYTHON:-/Volumes/ExtendHD/Environment/miniconda3/miniconda3/envs/Tools/bin/python}"
VENV="$BASE/venvs/faster-whisper"
MODEL="${1:-medium}"

export PIP_CACHE_DIR="$BASE/caches/pip"
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME="$BASE/models/whisper"

mkdir -p "$BASE/venvs" "$BASE/models/whisper" "$BASE/caches/pip"

echo "[setup] check venv ..."
if [ ! -x "$VENV/bin/python" ]; then
  echo "[setup] creating venv at $VENV"
  "$PY_TOOLS" -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip

echo "[setup] check faster-whisper ..."
if ! "$VENV/bin/python" -c "import faster_whisper" >/dev/null 2>&1; then
  echo "[setup] installing faster-whisper ..."
  "$VENV/bin/pip" install -q faster-whisper
fi

if [ "$MODEL" != "none" ]; then
  echo "[setup] downloading model Systran/faster-whisper-${MODEL} ..."
  "$VENV/bin/python" -c "from huggingface_hub import snapshot_download; print(snapshot_download('Systran/faster-whisper-${MODEL}'))"
fi

echo "[setup] done"