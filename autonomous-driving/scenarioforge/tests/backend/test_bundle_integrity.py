from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.bundle import BundleIntegrityError, seal_bundle, verify_bundle


def _bundle_files() -> dict[str, bytes]:
    return {
        "compiled_bundle.json": b'{"schema_version":"scenarioforge.compiled-bundle.v1"}\n',
        "run_records.json": b'[{"seed":17,"status":"completed"}]\n',
        "traces/case-000.json": b'[{"step":0,"position":[0.0,0.0]}]\n',
        "metrics.json": b'{"route_progress":0.25}\n',
        "provenance.json": b'{"backend":"metadrive-simulator","version":"0.4.3"}\n',
    }


def test_sealed_bundle_manifest_is_complete_and_cannot_be_overwritten(tmp_path: Path) -> None:
    bundle = seal_bundle(
        tmp_path,
        bundle_id="bundle-fixed",
        status="completed",
        scenario_digest="1" * 64,
        files=_bundle_files(),
    )

    verified = verify_bundle(bundle.path)
    assert verified.model_dump(mode="json") == {
        "schema_version": "scenarioforge.run-bundle-manifest.v1",
        "bundle_id": "bundle-fixed",
        "status": "completed",
        "scenario_digest": "1" * 64,
        "artifacts": [
            {
                "path": "compiled_bundle.json",
                "sha256": verified.artifacts[0].sha256,
                "size_bytes": 54,
            },
            {
                "path": "metrics.json",
                "sha256": verified.artifacts[1].sha256,
                "size_bytes": 24,
            },
            {
                "path": "provenance.json",
                "sha256": verified.artifacts[2].sha256,
                "size_bytes": 52,
            },
            {
                "path": "run_records.json",
                "sha256": verified.artifacts[3].sha256,
                "size_bytes": 35,
            },
            {
                "path": "traces/case-000.json",
                "sha256": verified.artifacts[4].sha256,
                "size_bytes": 34,
            },
        ],
    }
    assert all(not (path.stat().st_mode & 0o222) for path in bundle.path.rglob("*") if path.is_file())
    with pytest.raises(FileExistsError):
        seal_bundle(
            tmp_path,
            bundle_id="bundle-fixed",
            status="completed",
            scenario_digest="1" * 64,
            files=_bundle_files(),
        )


@pytest.mark.parametrize(
    ("target", "expected_invariant"),
    [
        ("manifest.json", "manifest_digest"),
        ("bundle.sha256", "bundle_digest"),
        ("traces/case-000.json", "artifact_digest:traces/case-000.json"),
        ("metrics.json", "artifact_digest:metrics.json"),
    ],
)
def test_all_digest_mutations_fail_before_json_parse(
    tmp_path: Path, target: str, expected_invariant: str
) -> None:
    bundle = seal_bundle(
        tmp_path,
        bundle_id=f"bundle-{target.replace('/', '-')}",
        status="completed",
        scenario_digest="2" * 64,
        files=_bundle_files(),
    )
    target_path = bundle.path / target
    target_path.chmod(0o644)
    target_path.write_bytes(b"not-json-and-not-the-original")

    with pytest.raises(BundleIntegrityError) as raised:
        verify_bundle(bundle.path)

    assert raised.value.invariant == expected_invariant
    assert "before parse/use" in str(raised.value)
