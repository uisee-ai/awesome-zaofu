# Release threat model

ScenarioForge is a local-first authoring and evidence tool. The supported trust
boundary contains one user, one loopback API process, isolated MetaDrive worker
processes, the exact production Web artifact, and sealed run bundles.

Threats and controls:

- Remote access and cross-origin requests: the server binds only approved
  loopback hosts; origin, capability token, and CSRF token are mandatory.
- Active-content and secret ingestion: the API rejects known active-content,
  serialization, and secret-marker patterns and caps request size.
- Bundle and asset path traversal: opaque bundle IDs, regular single-link files,
  safe archive members, and root-bound paths fail closed.
- Supply-chain drift: Python, npm, and asset inputs have exact locks; the release
  index binds those locks, the source revision, generated Web tree, SBOM, and CI
  receipts by SHA-256.
- Runtime download or telemetry: the product has no download fallback or
  telemetry path; offline E2E replaces socket access with a fail-closed guard.
- Evidence replacement: reports and sidecars are created once, canonicalized,
  made read-only, and revalidated before reuse.
- Worker failure and resource exhaustion: subprocess isolation, deadlines,
  quotas, lifecycle receipts, and partial-bundle sealing preserve diagnostics.

Residual risks include malicious local administrators, compromised OS/browser
binaries, undiscovered third-party vulnerabilities, physical vehicle mismatch,
and simulator model limitations. These are outside the P0 trust boundary.
