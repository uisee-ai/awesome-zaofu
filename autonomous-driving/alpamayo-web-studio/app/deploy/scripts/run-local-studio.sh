#!/usr/bin/env bash
set -euo pipefail

app_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
api_port="${ALPAMAYO_STUDIO_API_PORT:-8000}"
web_port="${ALPAMAYO_STUDIO_WEB_PORT:-3000}"

cd "$app_root"
export ALPAMAYO_STUDIO_PROVIDER_MODE="${ALPAMAYO_STUDIO_PROVIDER_MODE:-mock}"
export ALPAMAYO_STUDIO_STATE_PATH="${ALPAMAYO_STUDIO_STATE_PATH:-$app_root/data/studio-state.json}"
export ALPAMAYO_STUDIO_PROVIDER_ARTIFACT_DIR="${ALPAMAYO_STUDIO_PROVIDER_ARTIFACT_DIR:-$app_root/data/provider-responses}"
export ALPAMAYO_STUDIO_API_ORIGIN="http://127.0.0.1:$api_port"
export PYTHONPATH="$app_root/backend${PYTHONPATH:+:$PYTHONPATH}"

python -m uvicorn studio.app.main:app --host 0.0.0.0 --port "$api_port" &
api_pid=$!
cleanup() {
  kill "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

npm run dev -- --port "$web_port"
