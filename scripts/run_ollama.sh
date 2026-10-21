#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
command -v ollama >/dev/null || { echo "Ollama is not installed or is not on PATH." >&2; exit 1; }
export OLLAMA_MODELS="$repo_root/models/ollama"
echo "Ollama model directory: $OLLAMA_MODELS"
exec ollama serve
