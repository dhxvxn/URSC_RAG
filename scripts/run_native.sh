#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
[[ -x .venv/bin/python ]] || { echo "Run scripts/setup_native.sh first." >&2; exit 1; }

export DATA_DIR="$repo_root/data"
export EMBEDDING_MODEL_DIR="$repo_root/models/embeddings/all-MiniLM-L6-v2"
export EASYOCR_MODULE_PATH="$repo_root/models/easyocr"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_MODELS="$repo_root/models/ollama"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
host_address="${RAG_HOST:-127.0.0.1}"
port="${RAG_PORT:-8000}"

exec .venv/bin/python -m uvicorn main:app --host "$host_address" --port "$port"
