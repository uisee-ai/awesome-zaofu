from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from scenarioforge.core.canonical import (
    CanonicalModel,
    JSONValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)


REQUIRED_SNAPSHOT_FIELDS = (
    "schema_version",
    "execution_snapshot_id",
    "normalized_scenario_spec",
    "normalized_scenario_spec_digest",
    "resolved_defaults",
    "resolved_defaults_digest",
    "code",
    "adapter",
    "simulator",
    "assets",
    "policy",
    "seed",
    "run_parameters",
    "run_parameters_digest",
    "environment",
    "environment_digest",
)

REQUIRED_IDENTITY_FIELDS = {
    "normalized_scenario_spec": ("schema_version", "scenario_id"),
    "code": ("commit", "digest"),
    "adapter": ("id", "version", "digest"),
    "simulator": ("distribution", "version", "digest"),
    "asset": ("id", "version", "digest"),
    "policy": ("id", "version", "digest"),
    "environment": ("schema_version",),
}

CHAIN_LINK_FIELDS = {
    "run_manifest": (
        "execution_snapshot_id",
        "execution_snapshot_digest",
        "compile_report_digest",
    ),
    "compile_report": ("execution_snapshot_id", "execution_snapshot_digest"),
    "worker_receipt": (
        "execution_snapshot_id",
        "execution_snapshot_digest",
        "run_manifest_digest",
        "compile_report_digest",
    ),
    "artifact_index": (
        "execution_snapshot_id",
        "execution_snapshot_digest",
        "run_manifest_digest",
        "compile_report_digest",
        "worker_receipt_digest",
    ),
    "terminal_state": (
        "execution_snapshot_id",
        "execution_snapshot_digest",
        "artifact_index_digest",
    ),
    "trajectory": (
        "execution_snapshot_id",
        "execution_snapshot_digest",
        "artifact_index_digest",
    ),
    "replay": (
        "execution_snapshot_id",
        "execution_snapshot_digest",
        "artifact_index_digest",
    ),
}

_CHAIN_FIELDS = ("execution_snapshot", *CHAIN_LINK_FIELDS)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


class ExecutionSnapshotError(RuntimeError):
    pass


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionSnapshotError(f"{label} is missing or not an object")
    return value


def _freeze_object(value: Mapping[str, Any], label: str) -> Mapping[str, JSONValue]:
    frozen = freeze_json(value)
    if not isinstance(frozen, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return frozen


def _require_fields(value: Mapping[str, Any], fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if field not in value]
    if missing:
        raise ExecutionSnapshotError(f"{label} required fields are missing: {', '.join(missing)}")


def _require_identity(value: Mapping[str, Any], kind: str) -> None:
    fields = REQUIRED_IDENTITY_FIELDS[kind]
    _require_fields(value, fields, f"{kind} identity")
    for field in fields:
        if not isinstance(value[field], str) or not value[field]:
            raise ExecutionSnapshotError(f"{kind} identity field is invalid: {field}")
    if "digest" in fields and not _DIGEST.fullmatch(str(value["digest"])):
        raise ExecutionSnapshotError(f"{kind} digest is invalid")


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ExecutionSnapshotError(f"{label} is invalid")
    return value


@dataclass(frozen=True)
class ExecutionSnapshot(CanonicalModel):
    schema_version: str
    execution_snapshot_id: str
    normalized_scenario_spec: Mapping[str, JSONValue]
    normalized_scenario_spec_digest: str
    resolved_defaults: Mapping[str, JSONValue]
    resolved_defaults_digest: str
    code: Mapping[str, JSONValue]
    adapter: Mapping[str, JSONValue]
    simulator: Mapping[str, JSONValue]
    assets: tuple[Mapping[str, JSONValue], ...]
    policy: Mapping[str, JSONValue]
    seed: int
    run_parameters: Mapping[str, JSONValue]
    run_parameters_digest: str
    environment: Mapping[str, JSONValue]
    environment_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "normalized_scenario_spec",
            _freeze_object(self.normalized_scenario_spec, "normalized_scenario_spec"),
        )
        object.__setattr__(
            self, "resolved_defaults", _freeze_object(self.resolved_defaults, "resolved_defaults")
        )
        object.__setattr__(self, "code", _freeze_object(self.code, "code"))
        object.__setattr__(self, "adapter", _freeze_object(self.adapter, "adapter"))
        object.__setattr__(self, "simulator", _freeze_object(self.simulator, "simulator"))
        object.__setattr__(
            self,
            "assets",
            tuple(_freeze_object(asset, "asset") for asset in self.assets),
        )
        object.__setattr__(self, "policy", _freeze_object(self.policy, "policy"))
        object.__setattr__(
            self, "run_parameters", _freeze_object(self.run_parameters, "run_parameters")
        )
        object.__setattr__(
            self, "environment", _freeze_object(self.environment, "environment")
        )


@dataclass(frozen=True)
class ProvenanceChain(CanonicalModel):
    execution_snapshot: ExecutionSnapshot
    run_manifest: Mapping[str, JSONValue]
    compile_report: Mapping[str, JSONValue]
    worker_receipt: Mapping[str, JSONValue]
    artifact_index: Mapping[str, JSONValue]
    terminal_state: Mapping[str, JSONValue]
    trajectory: Mapping[str, JSONValue]
    replay: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        for field in CHAIN_LINK_FIELDS:
            object.__setattr__(self, field, _freeze_object(getattr(self, field), field))


def build_execution_snapshot(
    *,
    execution_snapshot_id: str,
    normalized_scenario_spec: Mapping[str, Any],
    resolved_defaults: Mapping[str, Any],
    code: Mapping[str, Any],
    adapter: Mapping[str, Any],
    simulator: Mapping[str, Any],
    assets: tuple[Mapping[str, Any], ...],
    policy: Mapping[str, Any],
    seed: int,
    run_parameters: Mapping[str, Any],
    environment: Mapping[str, Any],
) -> ExecutionSnapshot:
    snapshot = ExecutionSnapshot(
        schema_version="scenarioforge.execution-snapshot/v1",
        execution_snapshot_id=execution_snapshot_id,
        normalized_scenario_spec=normalized_scenario_spec,
        normalized_scenario_spec_digest=canonical_digest(normalized_scenario_spec),
        resolved_defaults=resolved_defaults,
        resolved_defaults_digest=canonical_digest(resolved_defaults),
        code=code,
        adapter=adapter,
        simulator=simulator,
        assets=assets,
        policy=policy,
        seed=seed,
        run_parameters=run_parameters,
        run_parameters_digest=canonical_digest(run_parameters),
        environment=environment,
        environment_digest=canonical_digest(environment),
    )
    validate_execution_snapshot(snapshot)
    return snapshot


def _snapshot_value(snapshot: ExecutionSnapshot | Mapping[str, Any]) -> Mapping[str, Any]:
    return snapshot.to_dict() if isinstance(snapshot, ExecutionSnapshot) else snapshot


def validate_execution_snapshot(
    snapshot: ExecutionSnapshot | Mapping[str, Any],
    *,
    expected_code_digest: str | None = None,
    expected_adapter: Mapping[str, Any] | None = None,
    expected_simulator: Mapping[str, Any] | None = None,
) -> str:
    value = _object(_snapshot_value(snapshot), "ExecutionSnapshot")
    if set(value) != set(REQUIRED_SNAPSHOT_FIELDS):
        raise ExecutionSnapshotError("ExecutionSnapshot required fields are missing or unexpected")
    if value.get("schema_version") != "scenarioforge.execution-snapshot/v1":
        raise ExecutionSnapshotError("ExecutionSnapshot schema version is unsupported")
    snapshot_id = value.get("execution_snapshot_id")
    if not isinstance(snapshot_id, str) or not _SNAPSHOT_ID.fullmatch(snapshot_id):
        raise ExecutionSnapshotError("execution snapshot identity is invalid")

    normalized_spec = _object(value.get("normalized_scenario_spec"), "normalized ScenarioSpec")
    defaults = _object(value.get("resolved_defaults"), "resolved defaults")
    code = _object(value.get("code"), "code identity")
    adapter = _object(value.get("adapter"), "adapter identity")
    simulator = _object(value.get("simulator"), "simulator identity")
    policy = _object(value.get("policy"), "policy identity")
    parameters = _object(value.get("run_parameters"), "run parameters")
    environment = _object(value.get("environment"), "environment identity")
    _require_identity(normalized_spec, "normalized_scenario_spec")
    _require_identity(code, "code")
    _require_identity(adapter, "adapter")
    _require_identity(simulator, "simulator")
    _require_identity(policy, "policy")
    _require_identity(environment, "environment")
    if not _COMMIT.fullmatch(str(code["commit"])):
        raise ExecutionSnapshotError("code commit identity is invalid")

    assets = value.get("assets")
    if not isinstance(assets, (list, tuple)) or not assets:
        raise ExecutionSnapshotError("at least one asset identity is required")
    asset_ids: list[str] = []
    for item in assets:
        asset = _object(item, "asset identity")
        _require_identity(asset, "asset")
        asset_ids.append(str(asset["id"]))
    if len(asset_ids) != len(set(asset_ids)):
        raise ExecutionSnapshotError("asset identities must be unique")

    digest_checks = (
        ("normalized_scenario_spec_digest", normalized_spec, "normalized ScenarioSpec digest"),
        ("resolved_defaults_digest", defaults, "resolved defaults digest"),
        ("run_parameters_digest", parameters, "run parameters digest"),
        ("environment_digest", environment, "environment digest"),
    )
    for field, payload, label in digest_checks:
        recorded = _require_digest(value.get(field), label)
        if recorded != canonical_digest(payload):
            raise ExecutionSnapshotError(f"{label} mismatch")
    if isinstance(value.get("seed"), bool) or not isinstance(value.get("seed"), int):
        raise ExecutionSnapshotError("seed must be an integer")

    if expected_code_digest is not None and code["digest"] != expected_code_digest:
        raise ExecutionSnapshotError("code digest drift detected")
    if expected_adapter is not None and thaw_json(adapter) != thaw_json(expected_adapter):
        raise ExecutionSnapshotError("adapter identity drift detected")
    if expected_simulator is not None and thaw_json(simulator) != thaw_json(expected_simulator):
        raise ExecutionSnapshotError("simulator identity drift detected")
    return canonical_digest(value)


def _bound_payload(
    payload: Mapping[str, Any],
    *,
    label: str,
    run_id: str,
    attempt_id: str,
    snapshot: ExecutionSnapshot,
) -> dict[str, Any]:
    value = thaw_json(payload)
    if not isinstance(value, dict):
        raise ExecutionSnapshotError(f"{label} must be an object")
    required = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "execution_snapshot_id": snapshot.execution_snapshot_id,
        "execution_snapshot_digest": snapshot.digest,
    }
    for key, expected in required.items():
        if key in value and value[key] != expected:
            raise ExecutionSnapshotError(f"{label} {key} conflicts with the execution snapshot")
        value[key] = expected
    if not isinstance(value.get("schema_version"), str) or not value["schema_version"]:
        raise ExecutionSnapshotError(f"{label} schema_version is required")
    return value


def _bind_identity(value: dict[str, Any], key: str, expected: Mapping[str, Any], label: str) -> None:
    identity = thaw_json(expected)
    if key in value and value[key] != identity:
        raise ExecutionSnapshotError(f"{label} {key} identity mismatch")
    value[key] = identity


def build_provenance_chain(
    execution_snapshot: ExecutionSnapshot,
    *,
    run_id: str,
    attempt_id: str,
    run_manifest: Mapping[str, Any],
    compile_report: Mapping[str, Any],
    worker_receipt: Mapping[str, Any],
    artifact_index: Mapping[str, Any],
    terminal_state: Mapping[str, Any],
    trajectory: Mapping[str, Any],
    replay: Mapping[str, Any],
) -> ProvenanceChain:
    validate_execution_snapshot(execution_snapshot)
    common = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "snapshot": execution_snapshot,
    }
    report = _bound_payload(compile_report, label="compile_report", **common)
    _bind_identity(report, "adapter", execution_snapshot.adapter, "compile_report")
    _bind_identity(report, "simulator", execution_snapshot.simulator, "compile_report")

    manifest = _bound_payload(run_manifest, label="run_manifest", **common)
    manifest["execution_snapshot"] = execution_snapshot.to_dict()
    manifest["compile_report_digest"] = canonical_digest(report)

    receipt = _bound_payload(worker_receipt, label="worker_receipt", **common)
    _bind_identity(receipt, "adapter", execution_snapshot.adapter, "worker_receipt")
    _bind_identity(receipt, "simulator", execution_snapshot.simulator, "worker_receipt")
    receipt["run_manifest_digest"] = canonical_digest(manifest)
    receipt["compile_report_digest"] = canonical_digest(report)

    index = _bound_payload(artifact_index, label="artifact_index", **common)
    index["run_manifest_digest"] = canonical_digest(manifest)
    index["compile_report_digest"] = canonical_digest(report)
    index["worker_receipt_digest"] = canonical_digest(receipt)
    index_digest = canonical_digest(index)

    terminal = _bound_payload(terminal_state, label="terminal_state", **common)
    terminal["artifact_index_digest"] = index_digest
    trajectory_value = _bound_payload(trajectory, label="trajectory", **common)
    trajectory_value["artifact_index_digest"] = index_digest
    replay_value = _bound_payload(replay, label="replay", **common)
    replay_value["artifact_index_digest"] = index_digest

    chain = ProvenanceChain(
        execution_snapshot=execution_snapshot,
        run_manifest=manifest,
        compile_report=report,
        worker_receipt=receipt,
        artifact_index=index,
        terminal_state=terminal,
        trajectory=trajectory_value,
        replay=replay_value,
    )
    validate_provenance_chain(chain)
    return chain


def _chain_value(chain: ProvenanceChain | Mapping[str, Any]) -> Mapping[str, Any]:
    return chain.to_dict() if isinstance(chain, ProvenanceChain) else chain


def _validate_binding(
    value: Mapping[str, Any],
    *,
    label: str,
    run_id: str,
    attempt_id: str,
    snapshot_id: str,
    snapshot_digest: str,
) -> None:
    _require_fields(value, CHAIN_LINK_FIELDS[label], label)
    if value.get("run_id") != run_id or value.get("attempt_id") != attempt_id:
        raise ExecutionSnapshotError(f"{label} run identity mismatch")
    if (
        value.get("execution_snapshot_id") != snapshot_id
        or value.get("execution_snapshot_digest") != snapshot_digest
    ):
        raise ExecutionSnapshotError(f"{label} snapshot binding mismatch")
    if not isinstance(value.get("schema_version"), str) or not value["schema_version"]:
        raise ExecutionSnapshotError(f"{label} schema_version is required")


def validate_provenance_chain(
    chain: ProvenanceChain | Mapping[str, Any],
    *,
    expected_code_digest: str | None = None,
    expected_adapter: Mapping[str, Any] | None = None,
    expected_simulator: Mapping[str, Any] | None = None,
) -> str:
    value = _object(_chain_value(chain), "provenance chain")
    if set(value) != set(_CHAIN_FIELDS):
        raise ExecutionSnapshotError("provenance chain required fields are missing or unexpected")
    snapshot = _object(value.get("execution_snapshot"), "ExecutionSnapshot")
    snapshot_digest = validate_execution_snapshot(
        snapshot,
        expected_code_digest=expected_code_digest,
        expected_adapter=expected_adapter,
        expected_simulator=expected_simulator,
    )
    snapshot_id = str(snapshot["execution_snapshot_id"])

    records = {
        label: _object(value.get(label), label) for label in CHAIN_LINK_FIELDS
    }
    run_id = records["run_manifest"].get("run_id")
    attempt_id = records["run_manifest"].get("attempt_id")
    if not isinstance(run_id, str) or not run_id or not isinstance(attempt_id, str) or not attempt_id:
        raise ExecutionSnapshotError("run manifest identity is missing")
    for label, record in records.items():
        _validate_binding(
            record,
            label=label,
            run_id=run_id,
            attempt_id=attempt_id,
            snapshot_id=snapshot_id,
            snapshot_digest=snapshot_digest,
        )

    manifest = records["run_manifest"]
    report = records["compile_report"]
    receipt = records["worker_receipt"]
    index = records["artifact_index"]
    terminal = records["terminal_state"]
    trajectory = records["trajectory"]
    replay = records["replay"]

    if manifest.get("execution_snapshot") != thaw_json(snapshot):
        raise ExecutionSnapshotError("RunManifest embedded execution snapshot mismatch")
    for label, record in (("compile_report", report), ("worker_receipt", receipt)):
        if record.get("adapter") != thaw_json(snapshot["adapter"]):
            raise ExecutionSnapshotError(f"{label} adapter identity mismatch")
        if record.get("simulator") != thaw_json(snapshot["simulator"]):
            raise ExecutionSnapshotError(f"{label} simulator identity mismatch")

    report_digest = canonical_digest(report)
    manifest_digest = canonical_digest(manifest)
    receipt_digest = canonical_digest(receipt)
    if manifest.get("compile_report_digest") != report_digest:
        raise ExecutionSnapshotError("RunManifest CompileReport digest mismatch")
    if receipt.get("run_manifest_digest") != manifest_digest:
        raise ExecutionSnapshotError("Worker receipt RunManifest digest mismatch")
    if receipt.get("compile_report_digest") != report_digest:
        raise ExecutionSnapshotError("Worker receipt CompileReport digest mismatch")
    if receipt.get("execution_status") != "completed":
        raise ExecutionSnapshotError("Worker receipt is partial or incomplete")

    if index.get("run_manifest_digest") != manifest_digest:
        raise ExecutionSnapshotError("ArtifactIndex RunManifest digest mismatch")
    if index.get("compile_report_digest") != report_digest:
        raise ExecutionSnapshotError("ArtifactIndex CompileReport digest mismatch")
    if index.get("worker_receipt_digest") != receipt_digest:
        raise ExecutionSnapshotError("ArtifactIndex Worker receipt digest mismatch")
    if index.get("execution_status") != "completed":
        raise ExecutionSnapshotError("ArtifactIndex is partial or incomplete")
    artifacts = index.get("artifacts")
    if not isinstance(artifacts, (list, tuple)) or not artifacts:
        raise ExecutionSnapshotError("ArtifactIndex requires fully verified artifacts")
    for artifact_value in artifacts:
        artifact = _object(artifact_value, "artifact entry")
        if artifact.get("status") != "present" or artifact.get("validation") != "verified":
            raise ExecutionSnapshotError("ArtifactIndex requires fully verified artifacts")
        _require_digest(artifact.get("digest"), "artifact digest")

    if terminal.get("execution_status") != "completed":
        raise ExecutionSnapshotError("terminal state is partial or incomplete")
    artifact_index_digest = canonical_digest(index)
    for label, record in (
        ("terminal_state", terminal),
        ("trajectory", trajectory),
        ("replay", replay),
    ):
        if record.get("artifact_index_digest") != artifact_index_digest:
            display = "ArtifactIndex" if label == "replay" else "artifact index"
            raise ExecutionSnapshotError(f"{label} {display} digest mismatch")
    if replay.get("eligible") is not True:
        raise ExecutionSnapshotError("replay is not eligible for the verified snapshot")
    return snapshot_digest


__all__ = [
    "CHAIN_LINK_FIELDS",
    "ExecutionSnapshot",
    "ExecutionSnapshotError",
    "ProvenanceChain",
    "REQUIRED_IDENTITY_FIELDS",
    "REQUIRED_SNAPSHOT_FIELDS",
    "build_execution_snapshot",
    "build_provenance_chain",
    "validate_execution_snapshot",
    "validate_provenance_chain",
]
