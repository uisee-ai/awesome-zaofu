# Supported local installation

This release supports Python 3.11, uv 0.11.3, Node.js 24.14.1, npm 11.11.0,
and a Chromium version installed by Playwright 1.62.1. On Debian/Ubuntu,
install `libgl1` before importing MetaDrive.

Install the exact dependency graphs from a clean checkout:

```bash
uv sync --frozen --all-groups
npm --prefix web ci
npm --prefix web run build
```

Obtain the upstream MetaDrive 0.4.3 `assets.zip` outside the runtime boundary.
Install only an archive accepted by the repository allowlist:

```bash
ASSET_ROOT="$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")/metadrive/assets"
.venv/bin/python scripts/release/install_metadrive_assets.py \
  --archive /absolute/path/to/assets.zip \
  --target "$ASSET_ROOT"
```

The installer verifies exact byte length and SHA-256 before extraction, blocks
path traversal and links, never downloads, and fails if the target exists.
After installation, run on loopback only:

```bash
SCENARIOFORGE_CAPABILITY_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
SCENARIOFORGE_CSRF_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
PYTHONPATH=src .venv/bin/python -m scenarioforge.app --host 127.0.0.1 --port 4174
```

Open `http://127.0.0.1:4174`. Keep both tokens private and enter them in the
local connection panel. Runtime asset download and external network are not
supported. A missing or mismatched asset tree is a pre-execution hard error.
