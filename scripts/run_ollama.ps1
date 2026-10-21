$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama is not installed or is not on PATH."
}

$env:OLLAMA_MODELS = Join-Path $RepoRoot "models\ollama"
Write-Host "Ollama model directory: $env:OLLAMA_MODELS"
& ollama serve
