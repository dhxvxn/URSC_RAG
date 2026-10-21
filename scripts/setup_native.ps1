param(
    [switch]$Offline,
    [string]$BundlePath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    throw "Python 3.11 or newer is required. Install Python and run this script again."
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & $Python.Source -m venv (Join-Path $RepoRoot ".venv")
}

if ($Offline) {
    if ([string]::IsNullOrWhiteSpace($BundlePath)) {
        throw "Use -BundlePath C:\path\to\offline-bundle when installing offline."
    }
    $WheelPath = (Resolve-Path (Join-Path $BundlePath "wheels")).Path
    & $VenvPython -m pip install --no-index --find-links $WheelPath -r (Join-Path $RepoRoot "requirements.txt")
} else {
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")

    $env:WARM_EMBEDDING_MODEL_DIR = Join-Path $RepoRoot "models\embeddings\all-MiniLM-L6-v2"
    $env:WARM_OCR_MODEL_DIR = Join-Path $RepoRoot "models\easyocr"
    & $VenvPython (Join-Path $RepoRoot "scripts\warm_models.py")
}

New-Item -ItemType Directory -Force (Join-Path $RepoRoot "data\documents") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $RepoRoot "data\images") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $RepoRoot "models\ollama") | Out-Null

Write-Host "Native setup complete. Start Ollama with scripts\run_ollama.ps1, then run scripts\run_native.ps1."
