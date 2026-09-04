#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
exec env PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}" python "$project_root/scripts/verify-release.py"
