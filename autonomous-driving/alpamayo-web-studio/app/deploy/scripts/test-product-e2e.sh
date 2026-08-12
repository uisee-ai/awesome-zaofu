#!/usr/bin/env bash
set -euo pipefail

app_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
studio_url="${ALPAMAYO_STUDIO_URL:-http://127.0.0.1:3000}"
evidence_dir="${ALPAMAYO_EVIDENCE_DIR:-/tmp/alpamayo-studio-evidence}"

mkdir -p "$evidence_dir"
chmod ugo+rwx "$evidence_dir"

docker run --rm --network host \
  -v "$app_root:/work/app:ro" \
  -v "$evidence_dir:/work/artifacts" \
  -e "ALPAMAYO_STUDIO_URL=$studio_url" \
  -e ALPAMAYO_EVIDENCE_DIR=/work/artifacts \
  --entrypoint sh \
  mcp/playwright:latest \
  -c 'export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH="$(find /ms-playwright -type f -path "*/chrome-linux*/chrome" | head -n 1)"; test -n "$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"; node /work/app/e2e/product-smoke.cjs'
