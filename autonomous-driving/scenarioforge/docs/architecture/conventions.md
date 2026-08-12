# ScenarioForge project conventions

## Package and entrypoint

- Python uses a single `src/scenarioforge/` package root.
- The installed command is `scenarioforge`, mapped to
  `scenarioforge.app:main`. The assembly slice owns `app.py`; the scaffold does
  not create a placeholder implementation.
- P0 has one execution backend: the exact MetaDrive distribution in
  `pyproject.toml` and `uv.lock`. Do not add a generic backend abstraction.

## Dependency and asset locks

- Every direct Python and npm dependency is an exact manifest pin. `uv.lock`
  and `web/package-lock.json` are committed and regenerated with their native
  package managers.
- MetaDrive 0.4.3 requires Python 3.11 (`>=3.11,<3.12` in this project).
- `config/metadrive-assets.lock.json` is the only asset allowlist. Installation
  verifies the archive size and SHA-256 before extraction. Runtime networking
  and automatic asset download are denied; missing or mismatched assets fail
  closed.
- Assets, third-party datasets, generated bundles, and binary distributions are
  never committed. Their redistribution remains blocked until release-owned
  provenance and license gates pass.

## Tests and ownership

- All tests live under the single `tests/` prefix. Python discovery is rooted
  there; `web/playwright.config.ts` points to `tests/web/`.
- Focused commands run from the repository root and are not rewritten at gate
  time.
- A task creates only its owned source and test subtrees. In particular, this
  scaffold does not pre-create later-owned backend, Web, evidence, release, or
  production-build files with `.gitkeep` placeholders.

## Local-only boundaries

- Development and preview servers bind to `127.0.0.1` with strict ports.
- MetaDrive workers use process isolation with at most one live simulator per
  process. Every owner must close its environment and terminate the affected
  process tree on failure.
- Exact replay consumes sealed artifacts without starting MetaDrive; a new
  simulation always produces a new bundle.
