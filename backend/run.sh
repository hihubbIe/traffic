#!/usr/bin/env bash
# Backend API (Linux). Listens on all interfaces, port $PORT (default 8000).
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
