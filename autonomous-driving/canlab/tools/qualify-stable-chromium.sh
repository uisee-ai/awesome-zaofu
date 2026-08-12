#!/usr/bin/env bash
set -euo pipefail

qualification_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node "${qualification_script_dir}/qualify-stable-chromium.mjs" "$@"
