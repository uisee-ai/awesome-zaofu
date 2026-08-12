# DBC compatibility corpus

This directory contains license-vetted, commit-pinned upstream DBC fixtures for
parser compatibility tests. It is test data only and is not copied into the
browser application's bundled assets.

`manifest.json` is the canonical provenance and baseline ledger. Every fixture
records its upstream repository, immutable commit, path, SHA-256, byte length,
feature markers, declaration counts, and current parser result. The two
upstream MIT license texts are retained under `licenses/`.

The baseline is descriptive, not a claim that an early rejection handles the
advertised feature correctly. At the initial baseline, five fixtures stop at
the standard `NS_` symbol declaration `CAT_DEF_` before the parser reaches the
fixture's Multiplex, CAN FD, floating-point, comment, or large-file body. This
is a measured compatibility gap. `opendbc-comma-body.dbc` is accepted with 14
messages and 60 signals.

When deliberately changing parser compatibility:

1. Keep every upstream file byte-identical and verify its SHA-256.
2. Update a baseline only after reviewing the new result against the fixture's
   feature markers and product boundary.
3. Never replace a pinned commit or license silently.
4. Keep the canonical runtime demo asset under `public/assets/` independent of
   this corpus.
