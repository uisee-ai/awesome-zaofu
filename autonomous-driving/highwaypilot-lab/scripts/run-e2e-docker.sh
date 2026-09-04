#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
evidence_root="$project_root/evidence/release/e2e"
e2e_port="${HIGHWAYPILOT_E2E_PORT:-4318}"
server_pid=""

mkdir -p "$evidence_root"

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

PORT="$e2e_port" "$project_root/scripts/start-demo.sh" >"$evidence_root/docker-server.stdout.log" 2>"$evidence_root/docker-server.stderr.log" &
server_pid="$!"

for _ in $(seq 1 150); do
  if curl --fail --silent --show-error "http://127.0.0.1:$e2e_port/api/health" >/dev/null; then
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "demo server exited before Docker E2E" >&2
    exit 1
  fi
  sleep 0.2
done
curl --fail --silent --show-error "http://127.0.0.1:$e2e_port/api/health" >/dev/null

docker run --rm --network host \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/highwaypilot-playwright \
  --env "HIGHWAYPILOT_BASE_URL=http://127.0.0.1:$e2e_port" \
  --volume "$project_root:/workspace" \
  --workdir /workspace \
  mcp/playwright:latest \
  npx playwright test tests/e2e/assembly --workers=1
