#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rc_web="$project_root/dist/release-candidates/v1-rc1/runtime/web"
demo_port="${HIGHWAYPILOT_PORT:-${PORT:-8000}}"

needs_assembly=0
if [[ ! -f "$rc_web/index.html" ]]; then
  needs_assembly=1
elif find "$project_root/web/src" "$project_root/web/public" "$project_root/scripts/assemble-release.py" \
    -type f -newer "$rc_web/index.html" -print -quit | grep -q .; then
  needs_assembly=1
fi

if [[ "$needs_assembly" == "1" ]]; then
  PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}" python "$project_root/scripts/assemble-release.py"
fi

cd "$project_root"
echo "HighwayPilot Lab: http://127.0.0.1:${demo_port}"
echo "PID: $$"
echo "Stop: Ctrl-C (graceful shutdown)"
exec env PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  python -m highwaypilot_lab --host 127.0.0.1 --port "$demo_port" --static-root "$rc_web"
