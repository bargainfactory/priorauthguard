#!/usr/bin/env bash
# Fetch a quantized whisper.cpp GGML model into the Tauri app data dir.
# Usage:
#   bash scripts/download-whisper-model.sh small.en-q8_0
#
# Models live at:
#   https://huggingface.co/ggerganov/whisper.cpp
#
# Recommended for clinician dictation:
#   - small.en-q8_0  (~170 MB; 1.5x RT on Apple Silicon)
#   - base.en-q5_1   (~60 MB;  3x RT on CPU; lower accuracy)
#   - medium.en-q5_0 (~530 MB; 0.7x RT; highest accuracy under quantization)

set -euo pipefail
MODEL="${1:-small.en-q8_0}"

case "$(uname -s)" in
  Darwin*)
    APP_DATA="$HOME/Library/Application Support/com.priorauthguard.desktop"
    ;;
  Linux*)
    APP_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/com.priorauthguard.desktop"
    ;;
  MINGW*|MSYS*|CYGWIN*)
    APP_DATA="$APPDATA/com.priorauthguard.desktop"
    ;;
  *)
    echo "Unsupported platform" >&2
    exit 1
    ;;
esac

mkdir -p "$APP_DATA/models"
DEST="$APP_DATA/models/ggml-$MODEL.bin"
URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$MODEL.bin"

if [ -f "$DEST" ]; then
  echo "Model already exists at $DEST"
  exit 0
fi

echo "Downloading $URL"
echo "        →  $DEST"
curl -L --fail -o "$DEST" "$URL"
echo "Done."
