from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from scenarioforge.core import (
    CompilationStatus,
    canonical_bytes,
    canonical_digest,
    environment_fingerprint,
    strict_loads,
)
from scenarioforge.core.models import CompileBundle

from .contracts import PreparedRun, RunRequest
from .contracts import TraceabilityError, validate_run_traceability
from .confirmation import ConfirmationMismatch, validate_bound_confirmation


ZERO_DIGEST = "0" * 64
INPUT_FILES = (
    "assets.json",
    "compile_report.json",
    "execution_plan.json",
    "policy.json",
    "run_manifest.json",
    "run_request.json",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class SnapshotError(RuntimeError):
    pass


def _write_json(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        payload = canonical_bytes(value)
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise SnapshotError(f"short write for {path.name}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    _write_json(temporary, value)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    value = strict_loads(payload)
    if not isinstance(value, dict):
        raise SnapshotError(f"{path.name} is not a JSON object")
    return value


def _normalized_input_payload(path: Path) -> bytes:
    if path.name == "run_manifest.json":
        value = _read_json(path)
        value["input_snapshot"]["digest"] = ZERO_DIGEST
        return canonical_bytes(value)
    if path.name == "run_request.json":
        value = _read_json(path)
        value["input_snapshot_digest"] = ZERO_DIGEST
        value["run_manifest_digest"] = ZERO_DIGEST
        return canonical_bytes(value)
    return path.read_bytes()


def _input_snapshot_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for name in INPUT_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise SnapshotError(f"input snapshot member is missing or not regular: {name}")
        relative = name.encode("utf-8")
        payload = _normalized_input_payload(path)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def validate_input_snapshot(root: Path) -> str:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise SnapshotError("input snapshot is not a regular directory")
    actual_names = tuple(sorted(path.name for path in root.iterdir()))
    if actual_names != tuple(sorted(INPUT_FILES)):
        raise SnapshotError("input snapshot contains an unexpected or missing member")
    for path in root.iterdir():
        mode = path.lstat().st_mode
        if path.is_symlink() or not stat.S_ISREG(mode):
            raise SnapshotError(f"input snapshot contains a link or special file: {path.name}")
        if path.stat().st_size > 10_485_760:
            raise SnapshotError(f"input snapshot member exceeds size limit: {path.name}")

    digest = _input_snapshot_digest(root)
    manifest = _read_json(root / "run_manifest.json")
    request = _read_json(root / "run_request.json")
    plan = _read_json(root / "execution_plan.json")
    report = _read_json(root / "compile_report.json")
    if manifest["input_snapshot"]["digest"] != digest or request["input_snapshot_digest"] != digest:
        raise SnapshotError("input snapshot digest binding is invalid")
    if request["run_manifest_digest"] != canonical_digest(manifest):
        raise SnapshotError("RunRequest manifest digest binding is invalid")
    if request["execution_plan_digest"] != canonical_digest(plan):
        raise SnapshotError("RunRequest execution plan digest binding is invalid")
    if manifest["compile_report"]["digest"] != canonical_digest(report):
        raise SnapshotError("RunManifest CompileReport digest binding is invalid")
    if manifest["execution_plan"]["digest"] != canonical_digest(plan):
        raise SnapshotError("RunManifest ExecutionPlan digest binding is invalid")
    if manifest.get("schema_version") == "scenarioforge.run-manifest/v3":
        instance = manifest.get("scenario_instance")
        if not isinstance(instance, dict):
            raise SnapshotError("RunManifest ScenarioInstance is invalid")
        if manifest.get("scenario_instance_digest") != canonical_digest(instance):
            raise SnapshotError("RunManifest ScenarioInstance digest binding is invalid")
        revision = manifest.get("scenario_revision")
        if not isinstance(revision, dict):
            raise SnapshotError("RunManifest scenario revision is invalid")
        if revision.get("digest") != instance.get("source_spec_digest"):
            raise SnapshotError("RunManifest revision source digest binding is invalid")
        confirmation = manifest.get("lossy_confirmation")
        bundle_payload: dict[str, Any] = {
            "scenario_instance": instance,
            "report": report,
            "execution_plan": plan,
        }
        if confirmation is not None:
            bundle_payload["confirmation"] = confirmation
        if manifest.get("compile_bundle_digest") != canonical_digest(bundle_payload):
            raise SnapshotError("RunManifest CompileBundle digest binding is invalid")
        assets = _read_json(root / "assets.json")
        if manifest["assets"]["digest"] != canonical_digest(assets):
            raise SnapshotError("RunManifest asset digest binding is invalid")
        try:
            validate_run_traceability(manifest)
        except TraceabilityError as error:
            raise SnapshotError(str(error)) from error
    return digest


def _freeze_directory(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for path in sorted((candidate for candidate in root.rglob("*") if candidate.is_dir()), reverse=True):
        path.chmod(0o555)
    root.chmod(0o555)


def _safe_identifier(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise SnapshotError(f"invalid {label}")
    return value


def _git_commit(project_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SnapshotError("unable to bind the source code commit") from error
    commit = completed.stdout.strip()
    if len(commit) not in {40, 64} or any(character not in "0123456789abcdef" for character in commit):
        raise SnapshotError("source code commit identity is invalid")
    return commit


def prepare_run(
    bundle: CompileBundle,
    *,
    workspace: Path,
    project_root: Path,
    run_id: str,
    attempt_id: str,
) -> PreparedRun:
    if bundle.execution_plan is None:
        raise SnapshotError("only a complete CompileBundle can be executed")
    if bundle.report.overall_status is CompilationStatus.LOSSY:
        try:
            validate_bound_confirmation(bundle, run_id=run_id, attempt_id=attempt_id)
        except ConfirmationMismatch as error:
            raise SnapshotError(str(error)) from error
    elif bundle.report.overall_status is not CompilationStatus.EXACT:
        raise SnapshotError("unsupported CompileBundle cannot be executed")
    run_id = _safe_identifier(run_id, "run_id")
    attempt_id = _safe_identifier(attempt_id, "attempt_id")
    workspace = Path(workspace)
    project_root = Path(project_root)
    workspace.mkdir(parents=True, exist_ok=True)

    input_logical_id = f"input-{run_id}-{attempt_id}"
    staging_logical_id = f"staging-{run_id}-{attempt_id}"
    input_snapshot = workspace / "input" / input_logical_id
    output_staging = workspace / "staging" / staging_logical_id
    published = workspace / "published" / run_id / attempt_id
    if input_snapshot.exists() or output_staging.exists() or published.exists():
        raise SnapshotError("run evidence path already exists; immutable attempts cannot be overwritten")
    input_snapshot.mkdir(parents=True, mode=0o700)
    output_staging.mkdir(parents=True, mode=0o700)
    if os.path.commonpath([input_snapshot.resolve(), output_staging.resolve()]) in {
        str(input_snapshot.resolve()),
        str(output_staging.resolve()),
    }:
        raise SnapshotError("InputSnapshot and OutputStaging overlap")

    fingerprint = environment_fingerprint(project_root / "uv.lock")
    fingerprint_payload = fingerprint.to_dict()
    simulator = fingerprint_payload["simulator"]
    policy_config = bundle.scenario_instance.policy["config"]
    is_v2 = bundle.scenario_instance.source_schema_version == "scenarioforge.scenario/v2"
    is_revision = bundle.scenario_instance.revision_id is not None
    adapter = {
        "id": bundle.execution_plan.backend["adapter"]["id"],
        "version": bundle.execution_plan.backend["adapter"]["version"],
    }
    assets_payload = {
        "schema_version": "scenarioforge.asset-descriptor/v1",
        "assets": [
            {
                "id": "metadrive-assets",
                "distribution": simulator["distribution"],
                "version": simulator["asset_version"],
                "digest": simulator["asset_digest"],
            }
        ],
    }
    policy_payload = bundle.scenario_instance.policy
    _write_json(input_snapshot / "assets.json", assets_payload)
    _write_json(input_snapshot / "compile_report.json", bundle.report.to_dict())
    _write_json(input_snapshot / "execution_plan.json", bundle.execution_plan.to_dict())
    _write_json(input_snapshot / "policy.json", policy_payload)

    manifest: dict[str, Any] = {
        "schema_version": (
            "scenarioforge.run-manifest/v3"
            if is_revision
            else ("scenarioforge.run-manifest/v2" if is_v2 else "scenarioforge.run-manifest/v1")
        ),
        "run_id": run_id,
        "attempt_id": attempt_id,
        "source_spec_digest": bundle.scenario_instance.source_spec_digest,
        "scenario_instance": bundle.scenario_instance.to_dict(),
        "scenario_instance_digest": bundle.scenario_instance.digest,
        "seed": bundle.scenario_instance.seed,
        "resolved_parameters": bundle.scenario_instance.parameters,
        "policy": {
            "id": bundle.scenario_instance.policy["id"],
            "version": bundle.scenario_instance.policy["version"],
            "config_digest": canonical_digest(policy_config),
        },
        "adapter": {**adapter, "digest": canonical_digest(adapter)},
        "compiler": {
            "version": bundle.report.compiler_version,
            "capability_descriptor_digest": bundle.report.capability_descriptor_digest,
        },
        "compile_report": {"ref": "compile_report.json", "digest": bundle.report.digest},
        "execution_plan": {"ref": "execution_plan.json", "digest": bundle.execution_plan.digest},
        "simulator": simulator,
        "python": fingerprint_payload["python"],
        "dependencies": {
            "lockfile": "uv.lock",
            "lockfile_digest": fingerprint_payload["dependency_lock"]["digest"],
            "resolved": {
                "jsonschema": importlib.metadata.version("jsonschema"),
                "metadrive-simulator": importlib.metadata.version("metadrive-simulator"),
            },
        },
        "assets": {"ref": "assets.json", "digest": canonical_digest(assets_payload)},
        "environment": {
            "os": fingerprint_payload["os"],
            "architecture": fingerprint_payload["architecture"],
            "headless": fingerprint_payload["rendering"]["headless"],
            "gpu_required": fingerprint_payload["rendering"]["gpu_required"],
        },
        "resource_config": bundle.execution_plan.resource_config,
        "tolerances_version": bundle.execution_plan.tolerances_version,
        "input_snapshot": {
            "logical_id": input_logical_id,
            "digest": ZERO_DIGEST,
            "digest_contract": "scenarioforge.input-snapshot-digest/v1",
        },
        "output_staging": {"logical_id": staging_logical_id},
    }
    if is_v2:
        manifest["terminal_contract"] = {
            "schema_version": "scenarioforge.terminal-contract/v2",
            "execution_status_values": ["completed", "failed", "timeout", "partial"],
            "scenario_outcome_values": ["safe_pass", "near_miss", "collision_failure"],
            "target_scenario_outcome": bundle.scenario_instance.constraints[
                "target_outcome"
            ],
            "termination_reason_source": "verified_worker_metrics",
        }
    if is_revision:
        instance = bundle.scenario_instance
        if None in {instance.revision_id, instance.revision_digest, instance.revision_schema_version}:
            raise SnapshotError("revision-aware run lacks complete immutable identity")
        if instance.source_spec_digest != instance.revision_digest:
            raise SnapshotError("ScenarioInstance does not bind the immutable revision digest")
        if None in {
            bundle.report.adapter_id,
            bundle.report.adapter_version,
            bundle.report.adapter_digest,
        }:
            raise SnapshotError("CompileReport lacks versioned adapter identity")
        if bundle.report.adapter_digest != manifest["adapter"]["digest"]:
            raise SnapshotError("CompileReport and ExecutionPlan adapter identity mismatch")
        manifest["scenario_revision"] = {
            "scenario_id": instance.scenario_id,
            "revision_id": instance.revision_id,
            "digest": instance.revision_digest,
            "schema_version": instance.revision_schema_version,
        }
        manifest["compile_bundle_digest"] = bundle.digest
        manifest["environment"]["fingerprint_digest"] = canonical_digest(fingerprint_payload)
        if bundle.confirmation is not None:
            manifest["lossy_confirmation"] = bundle.confirmation
        manifest["traceability"] = {
            "scenario_revision_digest": instance.revision_digest,
            "scenario_instance_digest": instance.digest,
            "compile_bundle_digest": bundle.digest,
            "compile_report_digest": bundle.report.digest,
            "execution_plan_digest": bundle.execution_plan.digest,
            "policy_digest": canonical_digest(manifest["policy"]),
            "code_commit": _git_commit(project_root),
            "adapter_digest": manifest["adapter"]["digest"],
            "metadrive_digest": canonical_digest(simulator),
            "assets_digest": manifest["assets"]["digest"],
            "environment_digest": canonical_digest(manifest["environment"]),
            "seed": instance.seed,
        }
    request = RunRequest(
        schema_version=(
            "scenarioforge.run-request/v3"
            if is_revision
            else ("scenarioforge.run-request/v2" if is_v2 else "scenarioforge.run-request/v1")
        ),
        run_id=run_id,
        attempt_id=attempt_id,
        input_snapshot_ref=input_logical_id,
        input_snapshot_digest=ZERO_DIGEST,
        run_manifest_digest=ZERO_DIGEST,
        execution_plan_digest=bundle.execution_plan.digest,
    )
    _write_json(input_snapshot / "run_manifest.json", manifest)
    _write_json(input_snapshot / "run_request.json", request.to_dict())

    snapshot_digest = _input_snapshot_digest(input_snapshot)
    manifest["input_snapshot"]["digest"] = snapshot_digest
    _replace_json(input_snapshot / "run_manifest.json", manifest)
    request = RunRequest(
        schema_version=request.schema_version,
        run_id=request.run_id,
        attempt_id=request.attempt_id,
        input_snapshot_ref=request.input_snapshot_ref,
        input_snapshot_digest=snapshot_digest,
        run_manifest_digest=canonical_digest(manifest),
        execution_plan_digest=request.execution_plan_digest,
    )
    _replace_json(input_snapshot / "run_request.json", request.to_dict())
    if validate_input_snapshot(input_snapshot) != snapshot_digest:
        raise SnapshotError("failed to freeze a stable InputSnapshot digest")
    _freeze_directory(input_snapshot)

    return PreparedRun(
        bundle=bundle,
        input_snapshot_path=input_snapshot,
        output_staging_path=output_staging,
        published_path=published,
        run_request=request,
    )
