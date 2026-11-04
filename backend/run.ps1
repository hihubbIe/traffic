# Backend API (Windows). Listens on all interfaces so a phone on the same Wi-Fi can reach it.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    .venv/Scripts/python -m pip install -r requirements.txt
}
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }
$port = if ($env:PORT) { $env:PORT } else { 8000 }
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port $port
