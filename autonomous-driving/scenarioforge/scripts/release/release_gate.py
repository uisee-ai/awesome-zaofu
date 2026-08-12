from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release._common import (  # noqa: E402
    EvidenceError,
    artifact_descriptor,
    digest_path,
    path_size,
    read_verified_json,
    write_immutable_json,
)
from scripts.release.publish_ci_run_manifest import COMMANDS, source_tree_digest  # noqa: E402
from scripts.release.run_clean_install_offline_e2e import validate_offline_report  # noqa: E402
from scripts.release.run_production_browser_e2e import validate_browser_report  # noqa: E402


CI_PROVIDERS = {"github-actions", "codex-ci"}
REQUIRED_RELEASE_ARTIFACTS = {
    "asset-lock": "config/metadrive-assets.lock.json",
    "asset-provenance": "docs/release/asset-provenance.md",
    "browser-production": "evidence/release/browser-production",
    "capacity": "evidence/release/capacity",
    "ci-manifest": "evidence/release/ci/ci-run-manifest.json",
    "clean-install-offline": "evidence/release/clean-install-offline",
    "demo-bundle": "evidence/release/metadrive-smoke/bundle",
    "license": "LICENSE",
    "license-matrix": "sbom/license-matrix.json",
    "local-install": "docs/release/local-install.md",
    "notice": "NOTICE",
    "production-web": "web/dist",
    "python-lock": "uv.lock",
    "safety-disclaimer": "docs/release/non-production-safety.md",
    "sbom": "sbom/scenarioforge.spdx.json",
    "threat-model": "docs/release/threat-model.md",
    "tolerance": "evidence/release/tolerance",
    "web-lock": "web/package-lock.json",
}


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{name} must be an object")
    return value


def _project_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else PROJECT_ROOT / path
    try:
        candidate.resolve(strict=False).relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise EvidenceError(f"release path escapes the project root: {path}") from error
    return candidate


def validate_ci_manifest(
    manifest: dict[str, Any],
    *,
    project_root: Path,
    expected_tree_digest: str,
    required_command_ids: set[str],
) -> None:
    if manifest.get("schema_version") != "scenarioforge.ci-run-manifest.v1":
        raise EvidenceError("CI manifest schema is missing or unsupported")
    if manifest.get("status") != "passed":
        raise EvidenceError("CI manifest status is not passed")
    ci = _object(manifest.get("ci"), "ci")
    if ci.get("provider") not in CI_PROVIDERS or ci.get("non_local") is not True:
        raise EvidenceError("CI manifest does not originate from a supported non-local CI run")
    if not isinstance(ci.get("run_id"), str) or not ci["run_id"].strip():
        raise EvidenceError("CI manifest run identity is empty")
    if manifest.get("mock_provider_used") is not False:
        raise EvidenceError("CI manifest reports a mock provider")
    source = _object(manifest.get("source"), "source")
    if source.get("tree_digest") != expected_tree_digest:
        raise EvidenceError("CI manifest has the wrong revision tree digest")
    revision = source.get("revision")
    if not isinstance(revision, str) or len(revision) != 40:
        raise EvidenceError("CI manifest source revision is invalid")

    commands = manifest.get("commands")
    if not isinstance(commands, list) or not commands:
        raise EvidenceError("CI manifest command receipts are missing or empty")
    by_id: dict[str, dict[str, Any]] = {}
    for value in commands:
        receipt = _object(value, "command receipt")
        command_id = receipt.get("command_id")
        if not isinstance(command_id, str) or command_id in by_id:
            raise EvidenceError("CI manifest command ids are invalid or duplicated")
        by_id[command_id] = receipt
        if receipt.get("status") != "passed" or receipt.get("exit_code") != 0:
            raise EvidenceError(f"CI manifest contains a failed command: {command_id}")
        if not isinstance(receipt.get("command"), str) or not receipt["command"].strip():
            raise EvidenceError(f"CI manifest command is empty: {command_id}")
    if set(by_id) != required_command_ids:
        raise EvidenceError("CI manifest command set is incomplete or unexpected")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise EvidenceError("CI manifest artifact list is missing or empty")
    seen: set[str] = set()
    for value in artifacts:
        artifact = _object(value, "artifact receipt")
        relative = artifact.get("path")
        if not isinstance(relative, str) or not relative or relative in seen:
            raise EvidenceError("CI manifest artifact path is invalid or duplicated")
        path = project_root / relative
        try:
            path.resolve(strict=False).relative_to(project_root.resolve())
        except ValueError as error:
            raise EvidenceError(f"CI manifest artifact escapes the project root: {relative}") from error
        seen.add(relative)
        if not path.exists() or path.is_symlink():
            raise EvidenceError(f"CI manifest artifact is missing or unsafe: {relative}")
        if digest_path(path) != artifact.get("sha256"):
            raise EvidenceError(f"CI manifest artifact digest mismatch: {relative}")
        if path_size(path) != artifact.get("size_bytes"):
            raise EvidenceError(f"CI manifest artifact size mismatch: {relative}")


def validate_release_index(
    index: dict[str, Any], *, project_root: Path, required_artifact_ids: set[str]
) -> None:
    if index.get("schema_version") != "scenarioforge.release-evidence-index.v1":
        raise EvidenceError("release evidence index schema is missing or unsupported")
    if index.get("status") != "passed":
        raise EvidenceError("release evidence index status is not passed")
    source = _object(index.get("source"), "release index source")
    if not isinstance(source.get("revision"), str) or len(source["revision"]) != 40:
        raise EvidenceError("release evidence index source revision is invalid")
    if not isinstance(source.get("tree_digest"), str) or len(source["tree_digest"]) != 64:
        raise EvidenceError("release evidence index source tree digest is invalid")
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise EvidenceError("release evidence index artifacts are missing or empty")
    by_id: dict[str, dict[str, Any]] = {}
    for value in artifacts:
        artifact = _object(value, "release artifact")
        artifact_id = artifact.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id in by_id:
            raise EvidenceError("release artifact ids are invalid or duplicated")
        by_id[artifact_id] = artifact
        relative = artifact.get("path")
        if not isinstance(relative, str) or not relative:
            raise EvidenceError(f"release artifact path is invalid: {artifact_id}")
        candidate = project_root / relative
        try:
            candidate.resolve(strict=False).relative_to(project_root.resolve())
        except ValueError as error:
            raise EvidenceError(f"release artifact escapes the project root: {artifact_id}") from error
        if not candidate.exists() or candidate.is_symlink() or path_size(candidate) == 0:
            raise EvidenceError(f"release artifact is missing or empty: {artifact_id}")
        if digest_path(candidate) != artifact.get("sha256"):
            raise EvidenceError(f"release artifact digest mismatch: {artifact_id}")
        if path_size(candidate) != artifact.get("size_bytes"):
            raise EvidenceError(f"release artifact size mismatch: {artifact_id}")
    if set(by_id) != required_artifact_ids:
        raise EvidenceError("release evidence index artifact set is incomplete or unexpected")


def _passed_real_report(path: Path, schema_version: str) -> None:
    payload = json.loads(path.read_bytes())
    if payload.get("schema_version") != schema_version or payload.get("status") != "passed":
        raise EvidenceError(f"release report did not pass: {path}")
    if payload.get("provider") != {
        "distribution": "metadrive-simulator",
        "version": "0.4.3",
        "kind": "real",
    }:
        raise EvidenceError(f"release report lacks real-provider provenance: {path}")


def _allowed_evidence_descendant(revision: str) -> None:
    subprocess.check_call(["git", "merge-base", "--is-ancestor", revision, "HEAD"], cwd=PROJECT_ROOT)
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{revision}..HEAD"], cwd=PROJECT_ROOT, text=True
    ).splitlines()
    outside_evidence = [path for path in changed if not path.startswith("evidence/release/")]
    if outside_evidence:
        raise EvidenceError(
            f"release evidence is stale for source changes after the CI revision: {outside_evidence}"
        )


def run(ci_manifest_path: Path, output: Path) -> dict[str, Any]:
    ci_manifest_path = _project_path(ci_manifest_path)
    output = _project_path(output)
    manifest = read_verified_json(ci_manifest_path)
    source = _object(manifest.get("source"), "source")
    revision = str(source.get("revision", ""))
    _allowed_evidence_descendant(revision)
    expected_tree_digest = source_tree_digest(PROJECT_ROOT, revision)
    validate_ci_manifest(
        manifest,
        project_root=PROJECT_ROOT,
        expected_tree_digest=expected_tree_digest,
        required_command_ids={command_id for command_id, _ in COMMANDS},
    )
    validate_browser_report(PROJECT_ROOT / "evidence/release/browser-production")
    validate_offline_report(PROJECT_ROOT / "evidence/release/clean-install-offline")
    _passed_real_report(
        PROJECT_ROOT / "evidence/release/metadrive-smoke/report.json",
        "scenarioforge.metadrive-smoke-report.v1",
    )
    _passed_real_report(
        PROJECT_ROOT / "evidence/release/capacity/report.json",
        "scenarioforge.capacity-benchmark.v1",
    )
    _passed_real_report(
        PROJECT_ROOT / "evidence/release/tolerance/report.json",
        "scenarioforge.tolerance-calibration-report.v1",
    )
    artifacts = []
    for artifact_id, relative in sorted(REQUIRED_RELEASE_ARTIFACTS.items()):
        descriptor = artifact_descriptor(PROJECT_ROOT, PROJECT_ROOT / relative)
        artifacts.append({"artifact_id": artifact_id, **descriptor})
    index = {
        "schema_version": "scenarioforge.release-evidence-index.v1",
        "status": "passed",
        "source": {"revision": revision, "tree_digest": expected_tree_digest},
        "artifacts": artifacts,
    }
    index_path = output.parent / "release-index.json"
    write_immutable_json(index_path, index)
    validate_release_index(
        read_verified_json(index_path),
        project_root=PROJECT_ROOT,
        required_artifact_ids=set(REQUIRED_RELEASE_ARTIFACTS),
    )
    gate = {
        "schema_version": "scenarioforge.release-gate.v1",
        "status": "passed",
        "source": index["source"],
        "ci": manifest["ci"],
        "mock_provider_used": False,
        "release_index": artifact_descriptor(PROJECT_ROOT, index_path),
        "ci_manifest": artifact_descriptor(PROJECT_ROOT, ci_manifest_path),
        "checks": {
            "artifact_completeness": "passed",
            "artifact_digests": "passed",
            "exact_revision": "passed",
            "non_local_ci": "passed",
            "real_provider": "passed",
            "offline_network_denial": "passed",
        },
    }
    write_immutable_json(output, gate)
    return read_verified_json(output)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the ScenarioForge release evidence")
    parser.add_argument("--ci-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.ci_manifest, args.output)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        raise SystemExit(1) from error
