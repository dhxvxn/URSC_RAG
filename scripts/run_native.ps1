$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "The virtual environment is missing. Run scripts\setup_native.ps1 first."
}

$env:DATA_DIR = Join-Path $RepoRoot "data"
$env:EMBEDDING_MODEL_DIR = Join-Path $RepoRoot "models\embeddings\all-MiniLM-L6-v2"
$env:EASYOCR_MODULE_PATH = Join-Path $RepoRoot "models\easyocr"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODELS = Join-Path $RepoRoot "models\ollama"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$HostAddress = if ($env:RAG_HOST) { $env:RAG_HOST } else { "127.0.0.1" }
$Port = if ($env:RAG_PORT) { $env:RAG_PORT } else { "8000" }

& $VenvPython -m uvicorn main:app --host $HostAddress --port $Port
