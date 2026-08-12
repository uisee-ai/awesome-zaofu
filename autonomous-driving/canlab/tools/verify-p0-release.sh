#!/usr/bin/env bash
set -euo pipefail

release_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node "${release_script_dir}/verify-p0-release.mjs" "$@"
