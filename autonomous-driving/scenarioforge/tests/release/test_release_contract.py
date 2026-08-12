from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scenarioforge.api import ApiConfig
from scenarioforge.app import create_release_app
from scripts.release._common import (
    EvidenceError,
    digest_path,
    read_digest_sidecar,
    write_immutable_json,
)
from scripts.release.install_metadrive_assets import install_asset_archive
from scripts.release.generate_compliance_artifacts import build_compliance_documents
from scripts.release.publish_ci_run_manifest import COMMANDS
from scripts.release.release_gate import (
    _project_path,
    validate_ci_manifest,
    validate_release_index,
)
from scripts.release.run_clean_install_offline_e2e import (
    _with_system_libraries as with_offline_system_libraries,
)
from scripts.release.run_clean_install_offline_e2e import validate_offline_report
from scripts.release.run_production_browser_e2e import (
    _with_system_libraries as with_browser_system_libraries,
)
from scripts.release.run_production_browser_e2e import validate_browser_report


ROOT = Path(__file__).resolve().parents[2]

SYSTEM_LIBRARY_RESOLVERS = (
    with_browser_system_libraries,
    with_offline_system_libraries,
)

EXPECTED_CI_COMMANDS = (
    (
        "source-delta",
        "python -c \"import subprocess; base='e7d4a12a0e0a878a9f607aac706f0984d2465dcb'; "
        "head=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(); "
        "assert head != base; "
        "subprocess.check_call(['git','merge-base','--is-ancestor',base,head])\"",
    ),
    ("exact-lock-install", "uv sync --frozen --all-groups --python 3.11"),
    (
        "python-version",
        "uv run --frozen --python 3.11 python -c \"import sys; "
        "assert sys.version_info[:2] == (3, 11), sys.version\"",
    ),
    (
        "focused-contract",
        "uv run --frozen --python 3.11 python -m pytest -q "
        "tests/scaffold/test_scaffold_contract.py tests/release/test_release_contract.py",
    ),
    (
        "no-host-library-fallback",
        "uv run --frozen --python 3.11 python -c \"from pathlib import Path; "
        "paths=['scripts/release/run_production_browser_e2e.py',"
        "'scripts/release/run_clean_install_offline_e2e.py']; "
        "needle='/tmp/scenarioforge-sfp0-002-libs'; "
        "assert all(needle not in Path(path).read_text(encoding='utf-8') for path in paths)\"",
    ),
    ("ruff", "uv run --frozen --python 3.11 python -m ruff check ."),
    ("pytest", "uv run --frozen --python 3.11 python -m pytest -q"),
    ("web-build", "npm --prefix web run build"),
    (
        "metadrive-smoke",
        "PYTHONPATH=src uv run --frozen --python 3.11 python "
        "scripts/backend/run_metadrive_smoke.py --profile default "
        "--output evidence/release/metadrive-smoke",
    ),
    (
        "browser-production",
        "uv run --frozen --python 3.11 python "
        "scripts/release/run_production_browser_e2e.py "
        "--output evidence/release/browser-production",
    ),
    (
        "clean-install-offline",
        "uv run --frozen --python 3.11 python "
        "scripts/release/run_clean_install_offline_e2e.py "
        "--output evidence/release/clean-install-offline",
    ),
    (
        "capacity",
        "PYTHONPATH=src uv run --frozen --python 3.11 python "
        "scripts/backend/run_capacity_benchmark.py --profile boundary "
        "--output evidence/release/capacity",
    ),
    (
        "tolerance",
        "PYTHONPATH=src uv run --frozen --python 3.11 python "
        "scripts/backend/run_tolerance_calibration.py --runs 5 "
        "--output evidence/release/tolerance",
    ),
)


def _api_config(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        bundle_root=tmp_path / "bundles",
        run_output_root=tmp_path / "runs",
        allowed_origin="http://127.0.0.1:4174",
        capability_token="release-test-capability",
        csrf_token="release-test-csrf",
    )


def test_release_app_serves_only_the_digested_production_tree(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/app-123.js"></script>',
        encoding="utf-8",
    )
    (assets / "app-123.js").write_text("document.body.dataset.release = 'exact'\n")

    client = TestClient(create_release_app(_api_config(tmp_path), dist_root=dist))
    index = client.get("/")
    asset = client.get("/assets/app-123.js")

    assert index.status_code == 200
    assert asset.status_code == 200
    assert index.headers["x-scenarioforge-dist-sha256"] == digest_path(dist)
    assert asset.headers["x-scenarioforge-dist-sha256"] == digest_path(dist)
    assert asset.text == "document.body.dataset.release = 'exact'\n"
    assert client.get("/assets/../index.html").status_code in {403, 404}


def test_release_app_fails_closed_for_missing_or_unsafe_dist(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="production Web build"):
        create_release_app(_api_config(tmp_path), dist_root=tmp_path / "missing")

    dist = tmp_path / "dist"
    dist.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    (dist / "index.html").symlink_to(outside)
    with pytest.raises(RuntimeError, match="unsafe"):
        create_release_app(_api_config(tmp_path), dist_root=dist)


def test_committed_production_web_artifact_is_complete_and_source_free() -> None:
    dist = Path(__file__).resolve().parents[2] / "web/dist"
    index = dist / "index.html"

    assert index.is_file()
    assert digest_path(dist)
    index_text = index.read_text(encoding="utf-8")
    assert "/src/" not in index_text
    assert 'type="module"' in index_text
    assert list((dist / "assets").glob("*.js"))
    assert list((dist / "assets").glob("*.css"))


def test_immutable_json_has_verified_digest_and_rejects_replacement(tmp_path: Path) -> None:
    target = tmp_path / "receipt.json"
    payload = {"schema_version": "receipt.v1", "status": "passed"}

    digest = write_immutable_json(target, payload)
    assert digest == hashlib.sha256(target.read_bytes()).hexdigest()
    assert read_digest_sidecar(target) == digest
    assert write_immutable_json(target, payload) == digest

    with pytest.raises(EvidenceError, match="immutable evidence differs"):
        write_immutable_json(target, {**payload, "status": "failed"})


def test_asset_installer_verifies_lock_and_blocks_zip_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("version.txt", "0.4.3\n")
        bundle.writestr("textures/grass1/GroundGrassGreen002_COL_1K.jpg", b"fixture")
    lock = {
        "backend": {"distribution": "metadrive-simulator", "version": "0.4.3"},
        "artifacts": [
            {
                "id": "metadrive-assets-0.4.3",
                "size_bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            }
        ],
    }
    lock_path = tmp_path / "asset-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    receipt = install_asset_archive(archive, tmp_path / "installed", lock_path=lock_path)
    assert receipt["status"] == "passed"
    assert receipt["network_access"] == "not_attempted"
    assert (tmp_path / "installed/version.txt").read_text(encoding="utf-8") == "0.4.3\n"

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as bundle:
        bundle.writestr("../escape", "bad")
    lock["artifacts"][0]["size_bytes"] = unsafe.stat().st_size
    lock["artifacts"][0]["sha256"] = hashlib.sha256(unsafe.read_bytes()).hexdigest()
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(EvidenceError, match="unsafe archive entry"):
        install_asset_archive(unsafe, tmp_path / "unsafe-install", lock_path=lock_path)


def _valid_manifest(root: Path) -> dict[str, object]:
    artifact = root / "artifact.txt"
    artifact.write_text("release artifact\n", encoding="utf-8")
    return {
        "schema_version": "scenarioforge.ci-run-manifest.v1",
        "status": "passed",
        "ci": {"provider": "codex-ci", "non_local": True, "run_id": "run-123"},
        "source": {"revision": "a" * 40, "tree_digest": "b" * 64},
        "mock_provider_used": False,
        "commands": [
            {
                "command_id": command_id,
                "command": command,
                "status": "passed",
                "exit_code": 0,
            }
            for command_id, command in EXPECTED_CI_COMMANDS
        ],
        "artifacts": [
            {
                "path": "artifact.txt",
                "kind": "file",
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "size_bytes": artifact.stat().st_size,
            }
        ],
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["ci"].update(non_local=False), "non-local CI"),
        (lambda value: value.update(mock_provider_used=True), "mock provider"),
        (lambda value: value["commands"][1].update(status="failed"), "failed command"),
        (lambda value: value["source"].update(tree_digest="0" * 64), "wrong revision"),
        (lambda value: value["artifacts"][0].update(sha256="0" * 64), "digest mismatch"),
    ],
)
def test_ci_manifest_rejects_non_ci_mock_failed_stale_and_tampered_inputs(
    tmp_path: Path, mutation: object, message: str
) -> None:
    manifest = _valid_manifest(tmp_path)
    mutation(manifest)  # type: ignore[operator]

    with pytest.raises(EvidenceError, match=message):
        validate_ci_manifest(
            manifest,
            project_root=tmp_path,
            expected_tree_digest="b" * 64,
            required_command_ids={item["command_id"] for item in _valid_manifest(tmp_path)["commands"]},
        )


def test_ci_manifest_accepts_complete_exact_receipts(tmp_path: Path) -> None:
    manifest = _valid_manifest(tmp_path)
    validate_ci_manifest(
        manifest,
        project_root=tmp_path,
        expected_tree_digest="b" * 64,
        required_command_ids={item["command_id"] for item in manifest["commands"]},
    )
    assert os.stat(tmp_path / "artifact.txt").st_nlink == 1


def test_non_local_ci_ports_the_complete_locked_release_command_set() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert COMMANDS == EXPECTED_CI_COMMANDS
    assert "SCENARIOFORGE_SYSTEM_LIBRARY_ROOT=$(dirname \"$LIBGL_PATH\")" in workflow
    assert "ldconfig -p" in workflow
    assert all(command in workflow for _, command in EXPECTED_CI_COMMANDS)


def test_browser_report_requires_the_complete_real_production_path(tmp_path: Path) -> None:
    output = tmp_path / "browser"
    trace = output / "chromium-trace.zip"
    trace.parent.mkdir(parents=True)
    trace.write_bytes(b"trace")
    trace.chmod(0o444)
    (output / "chromium-trace.sha256").write_text(
        f"{hashlib.sha256(trace.read_bytes()).hexdigest()}  chromium-trace.zip\n",
        encoding="ascii",
    )
    (output / "chromium-trace.sha256").chmod(0o444)
    payload = {
        "schema_version": "scenarioforge.production-browser-e2e.v1",
        "status": "passed",
        "provider": {
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "kind": "real",
        },
        "mock_provider_used": False,
        "external_network_attempts": [],
        "production_dist_sha256": "a" * 64,
        "trace": {
            "path": "chromium-trace.zip",
            "sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
        },
        "checks": {
            name: "passed"
            for name in (
                "import",
                "edit",
                "field_error_location",
                "canonical_preview",
                "real_run",
                "metrics",
                "exact_replay",
                "json_export",
                "yaml_export",
            )
        },
        "bundle": {"path": "runs/release-browser-run", "id": "release-browser-run"},
    }
    write_immutable_json(output / "report.json", payload)

    assert validate_browser_report(output)["status"] == "passed"

    payload["mock_provider_used"] = True
    (output / "report.json").chmod(0o600)
    (output / "report.sha256").chmod(0o600)
    (output / "report.json").unlink()
    (output / "report.sha256").unlink()
    write_immutable_json(output / "report.json", payload)
    with pytest.raises(EvidenceError, match="real provider"):
        validate_browser_report(output)


def test_offline_report_requires_clean_locks_network_denial_and_missing_asset_preflight(
    tmp_path: Path,
) -> None:
    output = tmp_path / "offline"
    payload = {
        "schema_version": "scenarioforge.clean-install-offline-e2e.v1",
        "status": "passed",
        "clean_install": True,
        "locks": {"python": "a" * 64, "web": "b" * 64, "asset": "c" * 64},
        "provider": {
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "kind": "real",
        },
        "network": {"policy": "denied", "external_attempts": []},
        "run": {"status": "completed", "bundle_id": "release-offline-run"},
        "replay": {"status": "passed", "metadrive_calls": 0},
        "missing_assets": {
            "status": "rejected_before_execution",
            "code": "assets_missing",
            "network_attempted": False,
        },
    }
    write_immutable_json(output / "report.json", payload)

    assert validate_offline_report(output)["clean_install"] is True

    payload["network"]["external_attempts"] = ["https://example.invalid"]
    (output / "report.json").chmod(0o600)
    (output / "report.sha256").chmod(0o600)
    (output / "report.json").unlink()
    (output / "report.sha256").unlink()
    write_immutable_json(output / "report.json", payload)
    with pytest.raises(EvidenceError, match="external network"):
        validate_offline_report(output)


@pytest.mark.parametrize("resolve_system_libraries", SYSTEM_LIBRARY_RESOLVERS)
def test_release_e2e_system_library_resolvers_fail_closed_when_root_is_unset(
    monkeypatch: pytest.MonkeyPatch, resolve_system_libraries: object
) -> None:
    monkeypatch.delenv("SCENARIOFORGE_SYSTEM_LIBRARY_ROOT", raising=False)

    with pytest.raises(EvidenceError, match="SCENARIOFORGE_SYSTEM_LIBRARY_ROOT must be set"):
        resolve_system_libraries({})  # type: ignore[operator]


@pytest.mark.parametrize("resolve_system_libraries", SYSTEM_LIBRARY_RESOLVERS)
def test_release_e2e_system_library_resolvers_reject_invalid_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolve_system_libraries: object,
) -> None:
    invalid_root = tmp_path / "missing-libgl"
    invalid_root.mkdir()
    monkeypatch.setenv("SCENARIOFORGE_SYSTEM_LIBRARY_ROOT", str(invalid_root))

    with pytest.raises(EvidenceError, match="must contain libGL.so.1"):
        resolve_system_libraries({})  # type: ignore[operator]


@pytest.mark.parametrize("resolve_system_libraries", SYSTEM_LIBRARY_RESOLVERS)
def test_release_e2e_system_library_resolvers_accept_explicit_valid_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolve_system_libraries: object,
) -> None:
    library_root = tmp_path / "system-libraries"
    library_root.mkdir()
    (library_root / "libGL.so.1").write_bytes(b"fixture")
    monkeypatch.setenv("SCENARIOFORGE_SYSTEM_LIBRARY_ROOT", str(library_root))
    environment = {"LD_LIBRARY_PATH": "/existing/libraries"}

    resolved = resolve_system_libraries(environment)  # type: ignore[operator]

    assert resolved is environment
    assert resolved["LD_LIBRARY_PATH"] == f"{library_root}:/existing/libraries"


def test_compliance_documents_cover_every_exact_lock_entry() -> None:
    root = Path(__file__).resolve().parents[2]
    sbom, matrix = build_compliance_documents(root)
    python_names = {
        package["name"]
        for package in __import__("tomllib").load((root / "uv.lock").open("rb"))["package"]
    }
    web_names = {
        path.removeprefix("node_modules/")
        for path in json.loads((root / "web/package-lock.json").read_bytes())["packages"]
        if path.startswith("node_modules/")
    }

    matrix_names = {(entry["ecosystem"], entry["name"]) for entry in matrix["components"]}
    assert {("python", name) for name in python_names} <= matrix_names
    assert {("npm", name) for name in web_names} <= matrix_names
    assert len(sbom["packages"]) == len(matrix["components"]) + 1
    assert matrix["asset_redistribution"] == "prohibited_until_release_license_review"


def test_release_index_rejects_missing_empty_and_tampered_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("bound\n", encoding="utf-8")
    descriptor = {
        "path": "artifact.txt",
        "kind": "file",
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "size_bytes": artifact.stat().st_size,
    }
    index = {
        "schema_version": "scenarioforge.release-evidence-index.v1",
        "status": "passed",
        "source": {"revision": "a" * 40, "tree_digest": "b" * 64},
        "artifacts": [{"artifact_id": "required", **descriptor}],
    }
    validate_release_index(index, project_root=tmp_path, required_artifact_ids={"required"})

    artifact.write_bytes(b"")
    with pytest.raises(EvidenceError, match="empty|digest mismatch"):
        validate_release_index(index, project_root=tmp_path, required_artifact_ids={"required"})


def test_release_gate_resolves_cli_paths_against_the_project_root() -> None:
    relative = Path("evidence/release/release-gate.json")
    absolute = ROOT / relative

    assert _project_path(relative) == absolute
    assert _project_path(absolute) == absolute
    with pytest.raises(EvidenceError, match="escapes the project root"):
        _project_path(Path("../outside.json"))
