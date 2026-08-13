# CAN Lab

CAN Lab is a browser-based CAN protocol exploration lab. The P0 application
uses only bundled synthetic DBC and deterministic NDJSON data; the project has
no hardware transmit or live vehicle input path.

- [中文使用教程](docs/manual/user-guide.md)
- [ZaoFu 交付案例](CASE.md)

## Why CAN Lab

CAN Lab was developed to make raw CAN frames and DBC definitions inspectable
without requiring a vehicle, CAN hardware, or proprietary logs. It combines
deterministic replay, bit-level decode traces, message-health metrics, and a
virtual vehicle view in one offline, receive-only browser workspace. It also
demonstrates how ZaoFu turns a discussed requirement into an executable PRD,
parallel implementation slices, browser verification, and release evidence.
The product contract is recorded in
[`docs/prd/can-lab-p0-mvp-prd.md`](docs/prd/can-lab-p0-mvp-prd.md) and
[`docs/prd/can-lab-p0-delivery-prd.md`](docs/prd/can-lab-p0-delivery-prd.md);
[`CASE.md`](CASE.md) summarizes the delivery path.

## Upstream and provenance

- The runtime demo DBC, validation vectors, and drive-cycle log are
  project-authored synthetic fixtures. Their versions, digests, seed, and
  license are declared in
  [`public/assets/canlab-demo-v1.0.0.metadata.json`](public/assets/canlab-demo-v1.0.0.metadata.json).
- [openDBC](https://github.com/commaai/opendbc) and
  [cantools](https://github.com/cantools/cantools) provide license-vetted,
  commit-pinned DBC files used only for parser compatibility tests. They are
  not bundled as the product demo dataset.
- Exact upstream commits, paths, SHA-256 values, measured parser results, and
  retained MIT license texts are listed under
  [`tests/fixtures/dbc-corpus/`](tests/fixtures/dbc-corpus/README.md).
- CAN Lab's application code and synthetic runtime assets were implemented for
  this project. The project is neither an openDBC nor a cantools fork, and it
  does not claim complete DBC dialect compatibility.

## Requirements

- Node.js `^20.19.0` or `>=22.12.0`
- npm with lockfile support

Install the exact dependency graph with:

```sh
npm ci
```

## Commands

- `npm run dev` starts the local Vite development server.
- `npm run lint` checks JavaScript and TypeScript sources.
- `npm run typecheck` runs TypeScript without emitting files.
- `npm test` runs the Vitest suite once.
- `npm run build` type-checks and builds the static application.
- `npm run test:e2e -- --project=chromium` runs the candidate Chromium journey.
- `npm run boundary:check` runs the passive-only boundary scanner supplied by
  the application assembly slice.

All commands run from the repository root. The development and preview servers
bind to loopback by default.

## DBC compatibility corpus

The commit-pinned, MIT-licensed upstream compatibility fixtures live in
`tests/fixtures/dbc-corpus/`. They are test-only and are not included in the
browser bundle. Run the parser baseline with:

```sh
npx vitest run tests/domain/dbc/corpus.test.ts
```

See the corpus `README.md` and `manifest.json` for provenance, SHA-256 values,
feature markers, and the measured parser result for every fixture.

## P0 integrity and passive boundary

The browser fetches four bundled files: provenance metadata, the DBC, validation
vectors, and deterministic NDJSON. It recomputes SHA-256 from the response bytes
for the DBC, vectors, and log before parsing them. A digest, schema, version, or
cross-file identity mismatch renders the fail-closed error surface instead of the
lab. Known trace IDs bind both the verified log and DBC digests. Unknown frames
retain frame sequence, microsecond timestamp, CAN ID, standard/extended format,
DLC, and raw bytes without creating a signal or conversion chain.

The versioned policies live in `config/passive-boundary-policy.json` and
`config/csp-policy.json`. `tools/serve-p0-preview.mjs` is loopback-only and sends
the CSP as an HTTP response header. The P0 browser gate proves that CSP—not a
Playwright route—blocks a second loopback origin, and checks cookies, service
workers, local/session storage, IndexedDB, and Cache Storage before and after a
refresh.

## P0 closeout gates

Run the contract gates in this order:

```sh
npm ci && npm run lint && npm test && npm run build \
  && node tools/verify-assets.mjs --output artifacts/verification/p0/static/assets.json \
  && node tools/check-passive-boundary.mjs --policy config/passive-boundary-policy.json --fixtures tests/fixtures/passive-boundary --output artifacts/verification/p0/static/boundary-matrix.json \
  && node tools/check-csp-delivery.mjs --policy config/csp-policy.json --server tools/serve-p0-preview.mjs --output artifacts/verification/p0/static/csp.json

./tools/qualify-stable-chromium.sh --channel stable --platform linux64 \
  --output artifacts/verification/p0/browser/qualification.json

docker run --rm --network=none --read-only --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,nodev,size=512m \
  -e P0_EVIDENCE_DIR=/evidence/browser \
  -e P0_QUALIFICATION_RECEIPT=/evidence/browser/qualification.json \
  -v "$PWD/artifacts/verification/p0:/evidence" \
  canlab-p0-chromium:qualified npx --no-install playwright test \
  tests/e2e/p0-closeout.spec.ts --config=playwright.p0.config.ts --project=chromium
```

Qualification dynamically consumes the official Chrome for Testing Stable
snapshot, verifies the downloaded archive and executable, builds
`canlab-p0-chromium:qualified`, and binds the image digest to the candidate
commit/tree. The Docker browser run is the release evidence; a host browser run
is diagnostic only.

`tools/verify-p0-release.sh` is a read-only verifier. At candidate stage it
checks an explicitly unissued CAS intent, snapshots all Git refs before and
after verification, and reruns the static gates from a clean ephemeral export.
Only the separately authorized Owner token-gated control-plane action may
advance `main` and issue the immutable CAS receipt; repository verification
scripts never update a ref.

The public showcase intentionally excludes generated release evidence and the
original private repository's Git objects. Five lineage tests that require
those sealed inputs are therefore reported as skipped by `npm test`; they run
automatically when both the pinned promotion commit and release evidence are
available. Product, domain, UI, passive-boundary, and portable release-tool
tests remain active in this repository.
