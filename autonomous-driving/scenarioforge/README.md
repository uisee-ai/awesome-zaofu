# ScenarioForge

ScenarioForge is a MetaDrive-only P0 for authoring versioned scenarios, running
them in isolated worker processes, and replaying sealed run bundles in a local
Web application. The repository is intentionally source-only: simulator assets
and generated Web bundles are installed or built locally and are not committed.

- [使用教程](docs/manual/user-guide.md)
- [ZaoFu 交付案例](CASE.md)
- [支持的本地安装方式](docs/release/local-install.md)

## Locked toolchains

- Python 3.11 (MetaDrive 0.4.3 declares Python `<3.12`)
- uv 0.11.3
- Node.js 24.14.1 and npm 11.11.0

Install the exact Python and Web dependency graphs from the repository root:

```bash
uv sync --frozen --all-groups
npm --prefix web ci
```

On Debian/Ubuntu headless hosts, install the OpenCV runtime library before the
Python import/smoke gate:

```bash
sudo apt-get install --no-install-recommends libgl1
```

Without `libgl1`, the locked OpenCV wheel installs successfully but importing
MetaDrive fails at dynamic-link time. System-package installation belongs in
the clean-environment/CI setup and is never attempted by application runtime.

The authoritative dependency graphs are `uv.lock` and
`web/package-lock.json`. Direct dependencies are exact pins in their respective
manifests; do not update a manifest without regenerating its lockfile.

## MetaDrive assets

MetaDrive's upstream launcher can download assets during first use. ScenarioForge
does not permit that runtime behavior. Installation tooling must consume only
the artifact allowlisted in `config/metadrive-assets.lock.json`, verify its byte
length and SHA-256 before extraction, and install it before network access is
disabled. A missing or mismatched asset set is a hard startup error.

The allowlist pins the official MetaDrive 0.4.3 `assets.zip`; neither that
archive nor its extracted contents may be redistributed until the release
license review is complete.

## Development

The Python package uses the `src/scenarioforge/` layout. The installed entry
point is `scenarioforge`, backed by `scenarioforge.app:main`. Product tests live
under the single root `tests/`; Playwright resolves its tests from
`tests/web/` even though its configuration lives in `web/`.

Run the scaffold contract from the repository root:

```bash
python -m pytest tests/scaffold/test_scaffold_contract.py -q
```

Additional focused and real-provider commands are introduced by their owning
vertical slices. See `docs/architecture/conventions.md` for ownership and
offline/runtime constraints.
