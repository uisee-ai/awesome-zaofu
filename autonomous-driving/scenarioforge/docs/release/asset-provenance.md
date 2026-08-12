# MetaDrive asset provenance

The only eligible simulator asset input is the MetaDrive 0.4.3 release archive
identified by `config/metadrive-assets.lock.json`:

- Artifact ID: `metadrive-assets-0.4.3`
- Size: `134074203` bytes
- SHA-256: `4f0da9f5143a1258131c5b55f77bdf170c0f9bce8a9f18dd41b3678df779eac9`
- Upstream release: MetaDrive 0.4.3
- Runtime network: denied
- Automatic download: disabled
- Redistribution: prohibited until release-license review completes

Installation verifies the archive before extraction. Runtime preflight verifies
the installed version marker and a required asset. The clean-install evidence
retains independent asset, network, missing-asset, run, and replay receipts.
No MetaDrive asset archive or extracted asset is committed to this repository.
