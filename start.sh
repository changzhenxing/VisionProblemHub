#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed
VISION_PORT="${VISION_PORT:-8765}"
echo "Open in browser: http://127.0.0.1:${VISION_PORT}/"
uvicorn app.main:app --host 0.0.0.0 --port "$VISION_PORT"
