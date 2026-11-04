# Frontend (static app). Builds and serves on all interfaces, port 4173.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path "node_modules")) { npm install }
npm run build
npx vite preview --host --port 4173
