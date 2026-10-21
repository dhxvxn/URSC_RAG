#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="$(command -v python3 || command -v python)"
if [[ -z "${python_bin:-}" ]]; then
  echo "Python 3.11 or newer is required." >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  "$python_bin" -m venv .venv
fi

if [[ "${1:-}" == "--offline" ]]; then
  bundle_path="${2:-}"
  if [[ -z "$bundle_path" || ! -d "$bundle_path/wheels" ]]; then
    echo "Usage: scripts/setup_native.sh --offline /path/to/offline-bundle" >&2
    exit 1
  fi
  .venv/bin/python -m pip install --no-index --find-links "$bundle_path/wheels" -r requirements.txt
else
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  WARM_EMBEDDING_MODEL_DIR="$repo_root/models/embeddings/all-MiniLM-L6-v2" \
    WARM_OCR_MODEL_DIR="$repo_root/models/easyocr" \
    .venv/bin/python scripts/warm_models.py
fi

mkdir -p data/documents data/images models/ollama
echo "Native setup complete. Start Ollama with scripts/run_ollama.sh, then run scripts/run_native.sh."
