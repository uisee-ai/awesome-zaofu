from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from scenarioforge.core import canonical_bytes, canonical_digest, strict_loads

from .catalog import registered_scenario_for_instance

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_REASON = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SAFE_NODE = re.compile(r"^[A-Za-z0-9_<>.$:-]{1,96}$")
_SAFE_BLOCK = re.compile(r"^[A-Za-z0-9]{1,32}$")
_SAFE_DEFINITION_ID = re.compile(r"^[a-z0-9./-]{1,96}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ZERO_DIGEST = "0" * 64
_CONTROL_LIMIT = 1_048_576
_ARTIFACT_LIMIT = 10_485_760
_TERMINAL_STATUSES = {"success", "failed", "timeout"}
_V2_EXECUTION_STATUSES = {"completed", "failed", "timeout", "partial"}
_V2_SCENARIO_OUTCOMES = {"safe_pass", "near_miss", "collision_failure"}
_V2_TOPOLOGIES = {
    "straight",
    "lane_closure",
    "corridor_merge",
    "ramp_merge",
    "intersection",
}
_V2_METRIC_FIELDS = {
    "collision": "collision",
    "hard_braking": "minimum_acceleration_mps2",
    "minimum_ttc": "min_ttc_s",
    "completion_time": "completion_time_s",
    "termination_reason": "termination_reason",
}
_V2_METRIC_EXPLANATIONS = {
    "collision": "Whether a collision occurred for the applicable participants.",
    "hard_braking": "The minimum acceleration observed for the applicable participants.",
    "minimum_ttc": "The minimum time to collision observed for the applicable participants.",
    "completion_time": "The time at which the applicable routes completed.",
    "termination_reason": "The verified reason the execution terminated.",
}
_ARTIFACT_PATHS = {
    "input/assets.json",
    "input/compile_report.json",
    "input/execution_plan.json",
    "input/policy.json",
    "input/run_manifest.json",
    "input/run_request.json",
    "output/actions.json",
    "output/events.json",
    "output/metrics.json",
    "output/trajectory.json",
    "output/worker_result.json",
    "failure_evidence.json",
}
_ARTIFACT_KEYS = {
    "manifest": "input/run_manifest.json",
    "events": "output/events.json",
    "metrics": "output/metrics.json",
    "trajectory": "output/trajectory.json",
    "worker_result": "output/worker_result.json",
    "failure": "failure_evidence.json",
}


class EvidenceError(RuntimeError):
    pass


class InvalidEvidenceIdentifierError(EvidenceError):
    pass


class UnknownPublishedRunError(EvidenceError):
    pass


class UnknownArtifactError(EvidenceError):
    pass


class EvidenceValidationError(EvidenceError):
    pass


class NonPlayableRunError(EvidenceError):
    pass


@dataclass(frozen=True)
class _ArtifactEntry:
    path: str
    status: str
    size_bytes: int
    digest: str
    validation: str


@dataclass(frozen=True)
class _OpenedRun:
    root: Path
    logical_ref: str
    status: str
    marker: Mapping[str, Any]
    result: Mapping[str, Any]
    index: Mapping[str, Any]
    artifacts: Mapping[str, _ArtifactEntry]
    protocol_version: int


def _validated_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise InvalidEvidenceIdentifierError(f"invalid {label}")
    return value


def validate_artifact_key(value: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise UnknownArtifactError("unknown artifact key")
    if value != "trajectory":
        raise UnknownArtifactError("unknown artifact key")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_regular(
    path: Path,
    *,
    byte_limit: int,
    expected_size: int | None = None,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise EvidenceValidationError(
            "published evidence file is unavailable"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceValidationError(
                "published evidence member is not a regular file"
            )
        if expected_size is not None and metadata.st_size != expected_size:
            raise EvidenceValidationError(
                "published artifact size does not match its index"
            )
        if metadata.st_size > byte_limit:
            raise EvidenceValidationError("published artifact exceeds the size limit")
        remaining = metadata.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65_536))
            if not chunk:
                raise EvidenceValidationError("published artifact changed during read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise EvidenceValidationError("published artifact changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _strict_json(payload: bytes, label: str) -> Any:
    try:
        value = strict_loads(payload)
        if canonical_bytes(value) != payload:
            raise EvidenceValidationError(f"{label} is not canonical strict JSON")
        return value
    except EvidenceValidationError:
        raise
    except (TypeError, ValueError) as error:
        raise EvidenceValidationError(f"{label} is not valid strict JSON") from error


def _object(payload: bytes, label: str) -> dict[str, Any]:
    value = _strict_json(payload, label)
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"{label} is not a JSON object")
    return value


def _safe_reason(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_REASON.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} is invalid")
    return value


def _safe_digest(value: object, label: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise EvidenceValidationError(f"{label} is invalid")
    if not allow_zero and value == _ZERO_DIGEST:
        raise EvidenceValidationError(f"{label} is invalid")
    return value


class PublishedEvidenceReader:
    """Read immutable publications through marker, index, digest, and schema gates."""

    def __init__(self, *, publish_root: Path) -> None:
        self.publish_root = Path(publish_root)

    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]:
        opened = self._open(run_id, attempt_id)
        manifest = self._manifest(opened)
        participants = self._participants(manifest)
        scenario_id = self._scenario_id(manifest)

        if opened.protocol_version == 2:
            metrics = self._metrics_v2(opened, manifest, participants)
            events = self._events_v2(opened, manifest, participants)
            trajectory_value, _ = self._indexed_json(
                opened,
                "trajectory",
                require_verified=True,
            )
            trajectory = self._trajectory_v2(
                trajectory_value,
                manifest,
                participants,
                terminal_tick=metrics["terminal_tick"],
            )
            self._worker_result_v2(opened, metrics, self._road_v2(manifest))
            self._validate_v2_evidence_binding(metrics, trajectory, events)
            return {
                "schema_version": "scenarioforge.terminal-evidence/v2",
                "scenario_id": scenario_id,
                "run_id": opened.result["run_id"],
                "attempt_id": opened.result["attempt_id"],
                "execution_status": opened.result["execution_status"],
                "scenario_outcome": opened.result["scenario_outcome"],
                "termination_reason": opened.result["termination_reason"],
                "terminal": True,
                "failure_stage": None,
                "playable": True,
                "playback_reason": None,
                "seed": manifest["seed"],
                "policy": {
                    "id": manifest["policy"]["id"],
                    "version": manifest["policy"]["version"],
                },
                "digests": {
                    "run_manifest": opened.result["run_manifest_digest"],
                    "artifact_index": opened.result["artifact_index_digest"],
                },
                "logical_ref": opened.logical_ref,
                "evidence": self._evidence_summary(opened),
                "metrics": {
                    key: metrics[key]
                    for key in (
                        "collision",
                        "collision_participants",
                        "min_ttc_s",
                        "minimum_acceleration_mps2",
                        "completion_time_s",
                        "terminal_tick",
                    )
                },
                "metric_projections": metrics["metric_projections"],
                "participants": participants,
                "events": events,
            }

        if opened.status == "success":
            complete_metrics = self._metrics(opened, participants)
            metrics = {
                key: complete_metrics[key]
                for key in (
                    "collision",
                    "collision_participants",
                    "min_ttc_s",
                    "completion_time_s",
                    "terminal_tick",
                )
            }
            events = self._events(opened, participants)
            trajectory = opened.artifacts.get(_ARTIFACT_KEYS["trajectory"])
            playable = bool(
                trajectory is not None
                and trajectory.status == "present"
                and trajectory.validation == "verified"
            )
            playback_reason = None if playable else "trajectory_not_fully_verified"
            failure_stage = None
        else:
            failure = self._failure(opened)
            metrics = {
                "collision": None,
                "collision_participants": [],
                "min_ttc_s": None,
                "completion_time_s": None,
                "terminal_tick": None,
            }
            events = []
            playable = False
            playback_reason = "terminal_not_success"
            failure_stage = failure["failure_stage"]

        return {
            "schema_version": "scenarioforge.terminal-evidence/v1",
            "scenario_id": scenario_id,
            "run_id": opened.result["run_id"],
            "attempt_id": opened.result["attempt_id"],
            "state": opened.status,
            "terminal": True,
            "status": opened.status,
            "reason": opened.result["reason"],
            "failure_stage": failure_stage,
            "playable": playable,
            "playback_reason": playback_reason,
            "seed": manifest["seed"],
            "policy": {
                "id": manifest["policy"]["id"],
                "version": manifest["policy"]["version"],
            },
            "digests": {
                "run_manifest": opened.result["run_manifest_digest"],
                "artifact_index": opened.result["artifact_index_digest"],
            },
            "logical_ref": opened.logical_ref,
            "evidence": self._evidence_summary(opened),
            "metrics": metrics,
            "participants": participants,
            "events": events,
        }

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        opened = self._open(run_id, attempt_id)
        if opened.status != "success":
            raise NonPlayableRunError("terminal run is not playable")
        manifest = self._manifest(opened)
        participants = self._participants(manifest)
        if opened.protocol_version == 2:
            metrics = self._metrics_v2(opened, manifest, participants)
            events = self._events_v2(opened, manifest, participants)
            trajectory_value, trajectory_entry = self._indexed_json(
                opened,
                "trajectory",
                require_verified=True,
            )
            trajectory = self._trajectory_v2(
                trajectory_value,
                manifest,
                participants,
                terminal_tick=metrics["terminal_tick"],
            )
            road = self._road_v2(manifest)
            road["geometry"] = self._worker_result_v2(opened, metrics, road)
            self._validate_v2_evidence_binding(metrics, trajectory, events)
            return {
                "schema_version": "scenarioforge.playback/v2",
                "scenario_id": self._scenario_id(manifest),
                "run_id": opened.result["run_id"],
                "attempt_id": opened.result["attempt_id"],
                "execution_status": opened.result["execution_status"],
                "scenario_outcome": opened.result["scenario_outcome"],
                "termination_reason": opened.result["termination_reason"],
                "logical_ref": f"{opened.logical_ref}/{trajectory_entry.path}",
                "trajectory_digest": trajectory_entry.digest,
                "road": road,
                "participants": participants,
                "sample_interval_s": metrics["sample_interval_s"],
                "terminal_tick": metrics["terminal_tick"],
                "events": events,
                "trajectory": trajectory,
            }
        metrics = self._metrics(opened, participants)
        events = self._events(opened, participants)
        trajectory_value, trajectory_entry = self._indexed_json(
            opened,
            "trajectory",
            require_verified=True,
        )
        trajectory = self._trajectory(
            trajectory_value,
            participants,
            terminal_tick=metrics["terminal_tick"],
        )
        return {
            "schema_version": "scenarioforge.playback/v1",
            "scenario_id": self._scenario_id(manifest),
            "run_id": opened.result["run_id"],
            "attempt_id": opened.result["attempt_id"],
            "logical_ref": f"{opened.logical_ref}/{trajectory_entry.path}",
            "trajectory_digest": trajectory_entry.digest,
            "road": self._road(manifest),
            "participants": participants,
            "sample_interval_s": metrics["sample_interval_s"],
            "terminal_tick": metrics["terminal_tick"],
            "events": events,
            "trajectory": trajectory,
        }

    def replay_scene(self, run_id: str, attempt_id: str) -> dict[str, object]:
        """Project verified playback for display without changing source evidence."""

        from scenarioforge.replay import project_replay_scene

        return project_replay_scene(self.playback(run_id, attempt_id))

    def _published_directory(self, run_id: str, attempt_id: str) -> Path:
        _validated_identifier(run_id, "run_id")
        _validated_identifier(attempt_id, "attempt_id")
        try:
            if self.publish_root.is_symlink():
                raise EvidenceValidationError(
                    "publish-root containment validation failed"
                )
            root = self.publish_root.resolve(strict=True)
            if not root.is_dir():
                raise UnknownPublishedRunError("unknown published run")
        except FileNotFoundError as error:
            raise UnknownPublishedRunError("unknown published run") from error

        run_root = self.publish_root / run_id
        if run_root.is_symlink():
            raise EvidenceValidationError("publish-root containment validation failed")
        attempt_root = run_root / attempt_id
        if attempt_root.is_symlink():
            raise EvidenceValidationError("publish-root containment validation failed")
        try:
            resolved = attempt_root.resolve(strict=True)
        except FileNotFoundError as error:
            raise UnknownPublishedRunError("unknown published run") from error
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise EvidenceValidationError(
                "publish-root containment validation failed"
            ) from error
        if not resolved.is_dir():
            raise UnknownPublishedRunError("unknown published run")
        return resolved

    def _open(self, run_id: str, attempt_id: str) -> _OpenedRun:
        root = self._published_directory(run_id, attempt_id)
        markers = [
            name for name in ("SUCCESS", "FAILED", "TIMEOUT") if (root / name).exists()
        ]
        if len(markers) != 1:
            raise EvidenceValidationError(
                "published run has no unique completion marker"
            )
        marker_name = markers[0]
        status = marker_name.lower()
        marker_payload = _read_regular(root / marker_name, byte_limit=_CONTROL_LIMIT)
        marker = _object(marker_payload, "completion marker")
        marker_schema = marker.get("schema_version")
        protocol_version = (
            2 if marker_schema == "scenarioforge.completion-marker/v2" else 1
        )
        if protocol_version == 2:
            marker_fields = {
                "schema_version",
                "execution_status",
                "scenario_outcome",
                "termination_reason",
                "run_result_digest",
                "artifact_index_digest",
            }
            if marker_name != "SUCCESS" or set(marker) != marker_fields:
                raise EvidenceValidationError("completion marker fields are invalid")
            if marker["execution_status"] != "completed":
                raise EvidenceValidationError(
                    "completion marker execution status is invalid"
                )
            if (
                not isinstance(marker["scenario_outcome"], str)
                or marker["scenario_outcome"] not in _V2_SCENARIO_OUTCOMES
            ):
                raise EvidenceValidationError(
                    "completion marker scenario outcome is invalid"
                )
            _safe_reason(
                marker["termination_reason"], "completion marker termination reason"
            )
        else:
            marker_fields = {
                "schema_version",
                "status",
                "run_result_digest",
                "artifact_index_digest",
            }
            if status != "success":
                marker_fields.add("failure_evidence_digest")
            if set(marker) != marker_fields:
                raise EvidenceValidationError("completion marker fields are invalid")
            if marker_schema != "scenarioforge.completion-marker/v1":
                raise EvidenceValidationError("completion marker schema is invalid")
            if marker.get("status") != status:
                raise EvidenceValidationError("completion marker status is invalid")
        if marker_schema not in {
            "scenarioforge.completion-marker/v1",
            "scenarioforge.completion-marker/v2",
        }:
            raise EvidenceValidationError("completion marker schema is invalid")
        for field in {"run_result_digest", "artifact_index_digest"} | (
            {"failure_evidence_digest"} if status != "success" else set()
        ):
            _safe_digest(marker[field], f"completion marker {field}")

        result_payload = _read_regular(
            root / "run_result.json", byte_limit=_CONTROL_LIMIT
        )
        index_payload = _read_regular(
            root / "artifact_index.json", byte_limit=_CONTROL_LIMIT
        )
        if _digest_bytes(result_payload) != marker["run_result_digest"]:
            raise EvidenceValidationError(
                "RunResult digest does not match completion marker"
            )
        if _digest_bytes(index_payload) != marker["artifact_index_digest"]:
            raise EvidenceValidationError(
                "ArtifactIndex digest does not match completion marker"
            )
        result = _object(result_payload, "RunResult")
        index = _object(index_payload, "ArtifactIndex")
        self._validate_result(result, run_id, attempt_id, status, protocol_version)
        artifacts = self._validate_index(index, run_id, attempt_id, protocol_version)
        if result["artifact_index_digest"] != canonical_digest(index):
            raise EvidenceValidationError("RunResult ArtifactIndex digest is invalid")
        if result["artifact_index_digest"] != marker["artifact_index_digest"]:
            raise EvidenceValidationError(
                "completion marker ArtifactIndex binding is invalid"
            )
        if protocol_version == 2:
            axes = ("execution_status", "scenario_outcome", "termination_reason")
            if any(
                marker[field] != result[field] or result[field] != index[field]
                for field in axes
            ):
                raise EvidenceValidationError(
                    "v2 terminal axes are not consistently bound"
                )
            if result["run_manifest_digest"] != index["run_manifest_digest"]:
                raise EvidenceValidationError("v2 RunManifest binding is invalid")
        self._validate_required_entries(status, artifacts, protocol_version)
        if protocol_version == 2:
            expected_paths = _ARTIFACT_PATHS - {"failure_evidence.json"}
            if set(artifacts) != expected_paths or any(
                entry.status != "present" or entry.validation != "verified"
                for entry in artifacts.values()
            ):
                raise EvidenceValidationError(
                    "v2 success publication is not complete and fully verified"
                )
        return _OpenedRun(
            root=root,
            logical_ref=f"published/{run_id}/{attempt_id}",
            status=status,
            marker=marker,
            result=result,
            index=index,
            artifacts=artifacts,
            protocol_version=protocol_version,
        )

    @staticmethod
    def _validate_result(
        result: Mapping[str, Any],
        run_id: str,
        attempt_id: str,
        status: str,
        protocol_version: int,
    ) -> None:
        common = {
            "schema_version",
            "run_id",
            "attempt_id",
            "worker_exit_code",
            "run_manifest_digest",
            "compile_report_digest",
            "execution_plan_digest",
            "artifact_index_digest",
        }
        expected = common | (
            {"execution_status", "scenario_outcome", "termination_reason"}
            if protocol_version == 2
            else {"status", "reason"}
        )
        if set(result) != expected:
            raise EvidenceValidationError("RunResult fields are invalid")
        if result["schema_version"] != f"scenarioforge.run-result/v{protocol_version}":
            raise EvidenceValidationError("RunResult schema is invalid")
        if result["run_id"] != run_id or result["attempt_id"] != attempt_id:
            raise EvidenceValidationError("RunResult identity binding is invalid")
        if protocol_version == 2:
            if status != "success" or result["execution_status"] != "completed":
                raise EvidenceValidationError("RunResult execution status is invalid")
            if (
                not isinstance(result["scenario_outcome"], str)
                or result["scenario_outcome"] not in _V2_SCENARIO_OUTCOMES
            ):
                raise EvidenceValidationError("RunResult scenario outcome is invalid")
            _safe_reason(result["termination_reason"], "RunResult termination reason")
        else:
            if result["status"] != status or status not in _TERMINAL_STATUSES:
                raise EvidenceValidationError("RunResult terminal status is invalid")
            _safe_reason(result["reason"], "RunResult reason")
        if not _is_int(result["worker_exit_code"]):
            raise EvidenceValidationError("RunResult exit code is invalid")
        for field in (
            "run_manifest_digest",
            "compile_report_digest",
            "execution_plan_digest",
            "artifact_index_digest",
        ):
            _safe_digest(result[field], f"RunResult {field}")

    @staticmethod
    def _validate_index(
        index: Mapping[str, Any],
        run_id: str,
        attempt_id: str,
        protocol_version: int,
    ) -> dict[str, _ArtifactEntry]:
        expected = {"schema_version", "run_id", "attempt_id", "artifacts"}
        if protocol_version == 2:
            expected |= {
                "run_manifest_digest",
                "execution_status",
                "scenario_outcome",
                "termination_reason",
            }
        if set(index) != expected:
            raise EvidenceValidationError("ArtifactIndex fields are invalid")
        if (
            index["schema_version"]
            != f"scenarioforge.artifact-index/v{protocol_version}"
        ):
            raise EvidenceValidationError("ArtifactIndex schema is invalid")
        if index["run_id"] != run_id or index["attempt_id"] != attempt_id:
            raise EvidenceValidationError("ArtifactIndex identity binding is invalid")
        if protocol_version == 2:
            _safe_digest(
                index["run_manifest_digest"], "ArtifactIndex RunManifest digest"
            )
            if (
                not isinstance(index["execution_status"], str)
                or index["execution_status"] not in _V2_EXECUTION_STATUSES
            ):
                raise EvidenceValidationError(
                    "ArtifactIndex execution status is invalid"
                )
            if (
                not isinstance(index["scenario_outcome"], str)
                or index["scenario_outcome"] not in _V2_SCENARIO_OUTCOMES
            ):
                raise EvidenceValidationError(
                    "ArtifactIndex scenario outcome is invalid"
                )
            _safe_reason(
                index["termination_reason"], "ArtifactIndex termination reason"
            )
        items = index["artifacts"]
        if not isinstance(items, list):
            raise EvidenceValidationError("ArtifactIndex artifacts are invalid")
        artifacts: dict[str, _ArtifactEntry] = {}
        listed_paths: list[str] = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "path",
                "status",
                "size_bytes",
                "digest",
                "validation",
            }:
                raise EvidenceValidationError("ArtifactIndex entry fields are invalid")
            path = item["path"]
            if not isinstance(path, str) or path not in _ARTIFACT_PATHS:
                raise EvidenceValidationError(
                    "ArtifactIndex contains an unknown logical path"
                )
            pure = PurePosixPath(path)
            if pure.is_absolute() or ".." in pure.parts or "\\" in path:
                raise EvidenceValidationError("ArtifactIndex logical path is unsafe")
            if path in artifacts:
                raise EvidenceValidationError(
                    "ArtifactIndex contains a duplicate entry"
                )
            size = item["size_bytes"]
            if not _is_int(size) or size < 0 or size > _ARTIFACT_LIMIT:
                raise EvidenceValidationError("ArtifactIndex entry size is invalid")
            digest = _safe_digest(
                item["digest"], "ArtifactIndex entry digest", allow_zero=True
            )
            status = item["status"]
            validation = item["validation"]
            allowed = {
                "present": {"verified", "verified_partial"},
                "missing": {"declared_missing"},
                "invalid": {
                    "invalid_json",
                    "link_or_special_file",
                    "size_limit_exceeded",
                },
            }
            if (
                not isinstance(status, str)
                or not isinstance(validation, str)
                or status not in allowed
                or validation not in allowed[status]
            ):
                raise EvidenceValidationError("ArtifactIndex entry state is invalid")
            if status == "missing" and (size != 0 or digest != _ZERO_DIGEST):
                raise EvidenceValidationError("missing ArtifactIndex entry is invalid")
            if status == "present" and digest == _ZERO_DIGEST:
                raise EvidenceValidationError(
                    "present ArtifactIndex entry digest is invalid"
                )
            artifacts[path] = _ArtifactEntry(path, status, size, digest, validation)
            listed_paths.append(path)
        if listed_paths != sorted(listed_paths):
            raise EvidenceValidationError("ArtifactIndex entries are not ordered")
        return artifacts

    @staticmethod
    def _validate_required_entries(
        status: str,
        artifacts: Mapping[str, _ArtifactEntry],
        protocol_version: int,
    ) -> None:
        required = ["input/run_manifest.json"]
        if status == "success":
            required.extend(
                ("output/events.json", "output/metrics.json", "output/trajectory.json")
            )
            if protocol_version == 2:
                required.append("output/worker_result.json")
        else:
            required.append("failure_evidence.json")
        for path in required:
            entry = artifacts.get(path)
            if entry is None:
                raise EvidenceValidationError(
                    "ArtifactIndex omits required terminal evidence"
                )
            if entry.status != "present" or entry.validation != "verified":
                raise EvidenceValidationError(
                    "required terminal evidence is not fully verified"
                )

    def _indexed_json(
        self,
        opened: _OpenedRun,
        key: str,
        *,
        require_verified: bool,
    ) -> tuple[Any, _ArtifactEntry]:
        relative = _ARTIFACT_KEYS[key]
        entry = opened.artifacts.get(relative)
        if entry is None:
            raise EvidenceValidationError("requested artifact is not enumerated")
        if entry.status != "present":
            raise EvidenceValidationError("requested artifact is not present")
        if require_verified and entry.validation != "verified":
            raise NonPlayableRunError("terminal run is not playable")
        path = opened.root.joinpath(*PurePosixPath(relative).parts)
        try:
            path.parent.resolve(strict=True).relative_to(opened.root)
        except (FileNotFoundError, ValueError) as error:
            raise EvidenceValidationError(
                "artifact containment validation failed"
            ) from error
        payload = _read_regular(
            path,
            byte_limit=_ARTIFACT_LIMIT,
            expected_size=entry.size_bytes,
        )
        if _digest_bytes(payload) != entry.digest:
            raise EvidenceValidationError(
                "published artifact digest does not match its index"
            )
        if (
            key == "failure"
            and _digest_bytes(payload) != opened.marker["failure_evidence_digest"]
        ):
            raise EvidenceValidationError(
                "failure evidence digest does not match completion marker"
            )
        return _strict_json(payload, f"{key} artifact"), entry

    def _manifest(self, opened: _OpenedRun) -> dict[str, Any]:
        value, entry = self._indexed_json(opened, "manifest", require_verified=True)
        if not isinstance(value, dict):
            raise EvidenceValidationError("RunManifest is invalid")
        if entry.digest != opened.result["run_manifest_digest"]:
            raise EvidenceValidationError("RunManifest digest does not match RunResult")
        required = {
            "schema_version",
            "run_id",
            "attempt_id",
            "scenario_instance",
            "seed",
            "policy",
        }
        if not required.issubset(value):
            raise EvidenceValidationError("RunManifest fields are invalid")
        if (
            value["schema_version"]
            != f"scenarioforge.run-manifest/v{opened.protocol_version}"
        ):
            raise EvidenceValidationError("RunManifest schema is invalid")
        if (
            value["run_id"] != opened.result["run_id"]
            or value["attempt_id"] != opened.result["attempt_id"]
        ):
            raise EvidenceValidationError("RunManifest identity binding is invalid")
        if not _is_int(value["seed"]):
            raise EvidenceValidationError("RunManifest Seed is invalid")
        policy = value["policy"]
        if not isinstance(policy, dict) or not {"id", "version"}.issubset(policy):
            raise EvidenceValidationError("RunManifest policy identity is invalid")
        _safe_reason(policy["id"], "RunManifest policy id")
        if (
            not isinstance(policy["version"], str)
            or _SAFE_ID.fullmatch(policy["version"]) is None
        ):
            raise EvidenceValidationError("RunManifest policy version is invalid")
        if opened.protocol_version == 2:
            self._validate_manifest_v2(opened, value)
        return value

    @staticmethod
    def _validate_manifest_v2(
        opened: _OpenedRun,
        manifest: Mapping[str, Any],
    ) -> None:
        expected = {
            "schema_version",
            "run_id",
            "attempt_id",
            "source_spec_digest",
            "scenario_instance",
            "scenario_instance_digest",
            "seed",
            "resolved_parameters",
            "policy",
            "adapter",
            "compiler",
            "compile_report",
            "execution_plan",
            "simulator",
            "python",
            "dependencies",
            "assets",
            "environment",
            "resource_config",
            "tolerances_version",
            "input_snapshot",
            "output_staging",
            "terminal_contract",
        }
        if set(manifest) != expected:
            raise EvidenceValidationError("v2 RunManifest fields are invalid")
        instance = manifest["scenario_instance"]
        if not isinstance(instance, dict) or set(instance) != {
            "schema_version",
            "scenario_id",
            "source_schema_version",
            "source_spec_digest",
            "seed",
            "road",
            "participants",
            "parameters",
            "events",
            "constraints",
            "policy",
            "required_capabilities",
            "backend_extensions",
        }:
            raise EvidenceValidationError("v2 scenario instance fields are invalid")
        if (
            instance["schema_version"] != "scenarioforge.scenario-instance/v2"
            or instance["source_schema_version"] != "scenarioforge.scenario/v2"
            or instance["seed"] != manifest["seed"]
            or instance["source_spec_digest"] != manifest["source_spec_digest"]
            or canonical_digest(instance) != manifest["scenario_instance_digest"]
        ):
            raise EvidenceValidationError("v2 scenario instance binding is invalid")
        instance_policy = instance["policy"]
        policy = manifest["policy"]
        if (
            not isinstance(instance_policy, dict)
            or not isinstance(policy, dict)
            or set(policy) != {"id", "version", "config_digest"}
            or policy["id"] != instance_policy.get("id")
            or policy["version"] != instance_policy.get("version")
            or not isinstance(instance_policy.get("config"), dict)
            or policy["config_digest"] != canonical_digest(instance_policy["config"])
            or manifest["resolved_parameters"] != instance["parameters"]
        ):
            raise EvidenceValidationError("v2 policy or parameter binding is invalid")
        _safe_digest(policy["config_digest"], "RunManifest policy config digest")
        for field in (
            "source_spec_digest",
            "scenario_instance_digest",
        ):
            _safe_digest(manifest[field], f"RunManifest {field}")

        constraints = instance["constraints"]
        if not isinstance(constraints, dict):
            raise EvidenceValidationError("v2 outcome contract is invalid")
        terminal = manifest["terminal_contract"]
        expected_terminal = {
            "schema_version": "scenarioforge.terminal-contract/v2",
            "execution_status_values": ["completed", "failed", "timeout", "partial"],
            "scenario_outcome_values": [
                "safe_pass",
                "near_miss",
                "collision_failure",
            ],
            "target_scenario_outcome": constraints.get("target_outcome"),
            "termination_reason_source": "verified_worker_metrics",
        }
        if terminal != expected_terminal:
            raise EvidenceValidationError("v2 terminal contract is invalid")

        bindings = (
            (
                "compile_report",
                "input/compile_report.json",
                opened.result["compile_report_digest"],
            ),
            (
                "execution_plan",
                "input/execution_plan.json",
                opened.result["execution_plan_digest"],
            ),
        )
        for manifest_key, artifact_path, result_digest in bindings:
            reference = manifest[manifest_key]
            entry = opened.artifacts.get(artifact_path)
            if (
                not isinstance(reference, dict)
                or set(reference) != {"ref", "digest"}
                or reference["ref"] != artifact_path.removeprefix("input/")
                or entry is None
                or entry.digest != reference["digest"]
                or entry.digest != result_digest
            ):
                raise EvidenceValidationError("v2 frozen artifact binding is invalid")

    @staticmethod
    def _scenario_instance(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        instance = manifest["scenario_instance"]
        if not isinstance(instance, dict):
            raise EvidenceValidationError("RunManifest scenario instance is invalid")
        return instance

    def _scenario_id(self, manifest: Mapping[str, Any]) -> str:
        instance = self._scenario_instance(manifest)
        instance_id = instance.get("scenario_id")
        if not isinstance(instance_id, str) or _SAFE_ID.fullmatch(instance_id) is None:
            raise EvidenceValidationError("RunManifest scenario identity is invalid")
        if manifest["schema_version"] == "scenarioforge.run-manifest/v2":
            return instance_id
        try:
            return registered_scenario_for_instance(instance_id)
        except RuntimeError as error:
            raise EvidenceValidationError(
                "RunManifest scenario identity is invalid"
            ) from error

    def _participants(self, manifest: Mapping[str, Any]) -> list[dict[str, str]]:
        raw = self._scenario_instance(manifest).get("participants")
        if not isinstance(raw, list):
            raise EvidenceValidationError("RunManifest participants are invalid")
        participants: list[dict[str, str]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise EvidenceValidationError("RunManifest participant is invalid")
            participant_id = item.get("id")
            role = item.get("role")
            if (
                not isinstance(participant_id, str)
                or _SAFE_ID.fullmatch(participant_id) is None
            ):
                raise EvidenceValidationError("RunManifest participant ID is invalid")
            if role not in {"ego", "social"}:
                raise EvidenceValidationError("RunManifest participant role is invalid")
            participants.append({"id": participant_id, "role": role})
        if manifest["schema_version"] == "scenarioforge.run-manifest/v2":
            ids = [item["id"] for item in participants]
            if (
                not participants
                or len(participants) > 16
                or len(ids) != len(set(ids))
                or sum(item["role"] == "ego" for item in participants) != 1
            ):
                raise EvidenceValidationError(
                    "RunManifest stable participant set is invalid"
                )
            return participants
        if participants != [
            {"id": "ego", "role": "ego"},
            {"id": "lead", "role": "social"},
        ]:
            raise EvidenceValidationError(
                "RunManifest stable participant set is invalid"
            )
        return participants

    def _road(self, manifest: Mapping[str, Any]) -> dict[str, object]:
        road = self._scenario_instance(manifest).get("road")
        if not isinstance(road, dict):
            raise EvidenceValidationError("RunManifest road is invalid")
        if road.get("template") != "straight" or not _is_int(road.get("lane_count")):
            raise EvidenceValidationError("RunManifest road is invalid")
        if road["lane_count"] <= 0:
            raise EvidenceValidationError("RunManifest road is invalid")
        for field in ("lane_width_m", "length_m"):
            if not _finite_number(road.get(field)) or road[field] <= 0:
                raise EvidenceValidationError("RunManifest road is invalid")
        return {
            "template": "straight",
            "lane_count": road["lane_count"],
            "lane_width_m": road["lane_width_m"],
            "length_m": road["length_m"],
        }

    def _road_v2(self, manifest: Mapping[str, Any]) -> dict[str, object]:
        road = self._scenario_instance(manifest).get("road")
        fields = {
            "schema_version",
            "topology_kind",
            "map_block_sequence",
            "lane_width_m",
            "coordinate_system",
            "units",
            "lanes",
            "conflict_zones",
        }
        if not isinstance(road, dict) or set(road) != fields:
            raise EvidenceValidationError("v2 RunManifest road is invalid")
        block = road["map_block_sequence"]
        if (
            road["schema_version"] != "scenarioforge.topology/v2"
            or not isinstance(road["topology_kind"], str)
            or road["topology_kind"] not in _V2_TOPOLOGIES
            or not isinstance(block, str)
            or _SAFE_BLOCK.fullmatch(block) is None
            or not _finite_number(road["lane_width_m"])
            or not 2.0 < road["lane_width_m"] <= 5.0
            or road["coordinate_system"] != "right-handed-x-forward-y-left"
            or road["units"]
            != {"distance": "m", "speed": "m/s", "heading": "deg", "time": "tick"}
        ):
            raise EvidenceValidationError("v2 RunManifest road is invalid")

        lanes = road["lanes"]
        if not isinstance(lanes, list) or not 1 <= len(lanes) <= 16:
            raise EvidenceValidationError("v2 RunManifest lanes are invalid")
        projected_lanes: list[dict[str, object]] = []
        lane_ids: list[str] = []
        lane_fields = {
            "id",
            "road_id",
            "engine_lane_index",
            "kind",
            "length_m",
            "predecessor_lane_ids",
            "successor_lane_ids",
        }
        for lane in lanes:
            if not isinstance(lane, dict) or set(lane) != lane_fields:
                raise EvidenceValidationError("v2 RunManifest lane is invalid")
            lane_id = lane["id"]
            engine = lane["engine_lane_index"]
            if (
                not isinstance(lane_id, str)
                or _SAFE_ID.fullmatch(lane_id) is None
                or not isinstance(lane["road_id"], str)
                or _SAFE_ID.fullmatch(lane["road_id"]) is None
                or not isinstance(lane["kind"], str)
                or lane["kind"]
                not in {"travel", "merge", "ramp", "turn", "closing", "closed"}
                or not _finite_number(lane["length_m"])
                or not 20.0 <= lane["length_m"] <= 10_000.0
                or not self._engine_lane_index_valid(engine, allow_none=False)
            ):
                raise EvidenceValidationError("v2 RunManifest lane is invalid")
            for relation in ("predecessor_lane_ids", "successor_lane_ids"):
                related = lane[relation]
                if (
                    not isinstance(related, list)
                    or len(related) > 8
                    or any(not isinstance(item, str) for item in related)
                    or len(related) != len(set(related))
                    or any(
                        not isinstance(item, str) or _SAFE_ID.fullmatch(item) is None
                        for item in related
                    )
                ):
                    raise EvidenceValidationError(
                        "v2 RunManifest lane relation is invalid"
                    )
            lane_ids.append(lane_id)
            projected_lanes.append(
                {
                    "id": lane_id,
                    "road_id": lane["road_id"],
                    "engine_lane_index": dict(engine),
                    "kind": lane["kind"],
                    "length_m": lane["length_m"],
                    "predecessor_lane_ids": list(lane["predecessor_lane_ids"]),
                    "successor_lane_ids": list(lane["successor_lane_ids"]),
                }
            )
        if len(lane_ids) != len(set(lane_ids)):
            raise EvidenceValidationError("v2 RunManifest lane IDs are invalid")
        known_lanes = set(lane_ids)
        if any(
            related not in known_lanes
            for lane in projected_lanes
            for relation in ("predecessor_lane_ids", "successor_lane_ids")
            for related in lane[relation]
        ):
            raise EvidenceValidationError("v2 RunManifest lane relation is invalid")

        zones = road["conflict_zones"]
        if not isinstance(zones, list) or len(zones) > 16:
            raise EvidenceValidationError("v2 RunManifest conflict zones are invalid")
        projected_zones: list[dict[str, object]] = []
        zone_ids: list[str] = []
        for zone in zones:
            if not isinstance(zone, dict) or set(zone) != {
                "id",
                "lane_ids",
                "start_m",
                "end_m",
            }:
                raise EvidenceValidationError("v2 RunManifest conflict zone is invalid")
            zone_lanes = zone["lane_ids"]
            if (
                not isinstance(zone["id"], str)
                or _SAFE_ID.fullmatch(zone["id"]) is None
                or not isinstance(zone_lanes, list)
                or not 2 <= len(zone_lanes) <= 8
                or any(not isinstance(item, str) for item in zone_lanes)
                or len(zone_lanes) != len(set(zone_lanes))
                or any(item not in known_lanes for item in zone_lanes)
                or not _finite_number(zone["start_m"])
                or not _finite_number(zone["end_m"])
                or not 0 <= zone["start_m"] < zone["end_m"] <= 10_000
            ):
                raise EvidenceValidationError("v2 RunManifest conflict zone is invalid")
            zone_ids.append(zone["id"])
            projected_zones.append(
                {
                    "id": zone["id"],
                    "lane_ids": list(zone_lanes),
                    "start_m": zone["start_m"],
                    "end_m": zone["end_m"],
                }
            )
        if len(zone_ids) != len(set(zone_ids)):
            raise EvidenceValidationError(
                "v2 RunManifest conflict zone IDs are invalid"
            )
        return {
            "schema_version": road["schema_version"],
            "topology_kind": road["topology_kind"],
            "map_block_sequence": block,
            "lane_width_m": road["lane_width_m"],
            "coordinate_system": road["coordinate_system"],
            "units": dict(road["units"]),
            "lanes": projected_lanes,
            "conflict_zones": projected_zones,
        }

    @staticmethod
    def _engine_lane_index_valid(value: object, *, allow_none: bool) -> bool:
        if value is None:
            return allow_none
        if isinstance(value, dict):
            if set(value) != {"start_node", "end_node", "lane_index"}:
                return False
            values = (value["start_node"], value["end_node"], value["lane_index"])
        elif isinstance(value, list) and len(value) == 3:
            values = tuple(value)
        else:
            return False
        return (
            isinstance(values[0], str)
            and _SAFE_NODE.fullmatch(values[0]) is not None
            and isinstance(values[1], str)
            and _SAFE_NODE.fullmatch(values[1]) is not None
            and _is_int(values[2])
            and 0 <= values[2] <= 15
        )

    def _metrics(
        self,
        opened: _OpenedRun,
        participants: list[dict[str, str]],
    ) -> dict[str, object]:
        value, _ = self._indexed_json(opened, "metrics", require_verified=True)
        fields = {
            "schema_version",
            "collision",
            "collision_participants",
            "termination_reason",
            "terminal_status",
            "min_ttc_s",
            "completed_steps",
            "sample_interval_s",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise EvidenceValidationError("metrics artifact is invalid")
        if value["schema_version"] != "scenarioforge.metrics/v1":
            raise EvidenceValidationError("metrics artifact is invalid")
        if (
            value["terminal_status"] != "success"
            or value["termination_reason"] != opened.result["reason"]
        ):
            raise EvidenceValidationError("metrics terminal binding is invalid")
        if not isinstance(value["collision"], bool):
            raise EvidenceValidationError("metrics collision is invalid")
        participant_ids = {item["id"] for item in participants}
        collisions = value["collision_participants"]
        if (
            not isinstance(collisions, list)
            or any(item not in participant_ids for item in collisions)
            or collisions != sorted(set(collisions))
        ):
            raise EvidenceValidationError("metrics collision participants are invalid")
        if value["collision"] != bool(collisions):
            raise EvidenceValidationError("metrics collision binding is invalid")
        minimum_ttc = value["min_ttc_s"]
        if minimum_ttc is not None and (
            not _finite_number(minimum_ttc) or minimum_ttc < 0
        ):
            raise EvidenceValidationError("metrics minimum TTC is invalid")
        completed = value["completed_steps"]
        interval = value["sample_interval_s"]
        if not _is_int(completed) or completed < 0:
            raise EvidenceValidationError("metrics terminal tick is invalid")
        if not _finite_number(interval) or interval <= 0:
            raise EvidenceValidationError("metrics sample interval is invalid")
        return {
            "collision": value["collision"],
            "collision_participants": list(collisions),
            "min_ttc_s": minimum_ttc,
            "completion_time_s": completed * interval,
            "terminal_tick": completed,
            "sample_interval_s": interval,
        }

    def _metrics_v2(
        self,
        opened: _OpenedRun,
        manifest: Mapping[str, Any],
        participants: list[dict[str, str]],
    ) -> dict[str, object]:
        value, _ = self._indexed_json(opened, "metrics", require_verified=True)
        fields = {
            "schema_version",
            "execution_status",
            "scenario_outcome",
            "target_scenario_outcome",
            "target_outcome_match",
            "termination_reason",
            "collision",
            "collision_participants",
            "min_ttc_s",
            "minimum_acceleration_mps2",
            "completion_time_s",
            "completed_steps",
            "sample_interval_s",
            "predicate_results",
            "metric_definitions",
            "metric_values",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise EvidenceValidationError("v2 metrics artifact is invalid")
        if value["schema_version"] != "scenarioforge.metrics/v2":
            raise EvidenceValidationError("v2 metrics artifact is invalid")
        axes = ("execution_status", "scenario_outcome", "termination_reason")
        if any(value[field] != opened.result[field] for field in axes):
            raise EvidenceValidationError("v2 metrics terminal binding is invalid")
        if value["execution_status"] != "completed":
            raise EvidenceValidationError("v2 metrics execution status is invalid")
        _safe_reason(value["termination_reason"], "v2 metrics termination reason")

        instance = self._scenario_instance(manifest)
        constraints = instance.get("constraints")
        if not isinstance(constraints, dict):
            raise EvidenceValidationError("v2 outcome contract is invalid")
        target = constraints.get("target_outcome")
        if (
            not isinstance(target, str)
            or target not in _V2_SCENARIO_OUTCOMES
            or value["target_scenario_outcome"] != target
            or not isinstance(value["target_outcome_match"], bool)
            or value["target_outcome_match"] != (value["scenario_outcome"] == target)
        ):
            raise EvidenceValidationError(
                "v2 metrics target outcome binding is invalid"
            )

        participant_ids = {item["id"] for item in participants}
        collisions = value["collision_participants"]
        if (
            not isinstance(value["collision"], bool)
            or not isinstance(collisions, list)
            or any(not isinstance(item, str) for item in collisions)
            or collisions != sorted(set(collisions))
            or any(item not in participant_ids for item in collisions)
            or value["collision"] != bool(collisions)
            or value["collision"] != (value["scenario_outcome"] == "collision_failure")
        ):
            raise EvidenceValidationError("v2 metrics collision binding is invalid")
        for field, minimum in (
            ("min_ttc_s", 0.0),
            ("completion_time_s", 0.0),
        ):
            item = value[field]
            if item is not None and (not _finite_number(item) or item < minimum):
                raise EvidenceValidationError(f"v2 metrics {field} is invalid")
        acceleration = value["minimum_acceleration_mps2"]
        if acceleration is not None and not _finite_number(acceleration):
            raise EvidenceValidationError("v2 metrics acceleration is invalid")
        completed = value["completed_steps"]
        interval = value["sample_interval_s"]
        if not _is_int(completed) or completed < 0:
            raise EvidenceValidationError("v2 metrics terminal tick is invalid")
        if not _finite_number(interval) or interval <= 0:
            raise EvidenceValidationError("v2 metrics sample interval is invalid")

        definitions = value["metric_definitions"]
        declared_definitions = constraints.get("metric_definitions")
        if definitions != declared_definitions or not isinstance(definitions, list):
            raise EvidenceValidationError(
                "v2 metric definitions are not manifest-bound"
            )
        values = value["metric_values"]
        if not isinstance(values, list) or len(values) != len(definitions):
            raise EvidenceValidationError("v2 metric values are invalid")
        projections: list[dict[str, object]] = []
        names: list[str] = []
        definition_ids: list[str] = []
        road = self._scenario_instance(manifest).get("road")
        if not isinstance(road, dict):
            raise EvidenceValidationError("v2 metric topology binding is invalid")
        topology_kind = road.get("topology_kind")
        for definition, metric_value in zip(definitions, values, strict=True):
            projected = self._metric_projection_v2(
                definition,
                metric_value,
                value,
                participant_ids,
                topology_kind,
            )
            names.append(str(projected["metric"]))
            definition_ids.append(str(projected["definition_id"]))
            projections.append(projected)
        if set(names) != set(_V2_METRIC_FIELDS) or len(names) != len(set(names)):
            raise EvidenceValidationError("v2 metric set is invalid")
        if len(definition_ids) != len(set(definition_ids)):
            raise EvidenceValidationError("v2 metric definition IDs are invalid")
        self._predicate_results_v2(value["predicate_results"], constraints)
        return {
            "collision": value["collision"],
            "collision_participants": list(collisions),
            "min_ttc_s": value["min_ttc_s"],
            "minimum_acceleration_mps2": acceleration,
            "completion_time_s": value["completion_time_s"],
            "terminal_tick": completed,
            "sample_interval_s": interval,
            "metric_projections": projections,
            "execution_status": value["execution_status"],
            "scenario_outcome": value["scenario_outcome"],
            "termination_reason": value["termination_reason"],
        }

    @staticmethod
    def _metric_projection_v2(
        definition: object,
        metric_value: object,
        metrics: Mapping[str, Any],
        participant_ids: set[str],
        topology_kind: object,
    ) -> dict[str, object]:
        definition_fields = {
            "definition_id",
            "metric",
            "unit",
            "applies_to",
            "threshold",
            "null_semantics",
            "evidence_field",
        }
        value_fields = definition_fields | {
            "value",
            "raw_evidence_value",
            "threshold_met",
        }
        if (
            not isinstance(definition, dict)
            or set(definition) != definition_fields
            or not isinstance(metric_value, dict)
            or set(metric_value) != value_fields
            or any(
                metric_value[field] != definition[field] for field in definition_fields
            )
        ):
            raise EvidenceValidationError("v2 metric projection fields are invalid")
        definition_id = definition["definition_id"]
        metric = definition["metric"]
        if (
            not isinstance(definition_id, str)
            or _SAFE_DEFINITION_ID.fullmatch(definition_id) is None
            or not isinstance(metric, str)
            or metric not in _V2_METRIC_FIELDS
        ):
            raise EvidenceValidationError("v2 metric definition identity is invalid")
        expected_units = {
            "collision": "boolean",
            "hard_braking": "m/s^2",
            "minimum_ttc": "s",
            "completion_time": "s",
            "termination_reason": "category",
        }
        evidence_field = definition["evidence_field"]
        if (
            definition["unit"] != expected_units[metric]
            or evidence_field != _V2_METRIC_FIELDS[metric]
        ):
            raise EvidenceValidationError("v2 metric definition semantics are invalid")
        applies_to = definition["applies_to"]
        if not isinstance(applies_to, dict) or set(applies_to) != {
            "participant_ids",
            "topology_kinds",
        }:
            raise EvidenceValidationError("v2 metric applicability is invalid")
        applicable_participants = applies_to["participant_ids"]
        topologies = applies_to["topology_kinds"]
        if (
            not isinstance(applicable_participants, list)
            or len(applicable_participants) > 16
            or any(not isinstance(item, str) for item in applicable_participants)
            or len(applicable_participants) != len(set(applicable_participants))
            or any(item not in participant_ids for item in applicable_participants)
            or not isinstance(topologies, list)
            or not 1 <= len(topologies) <= 5
            or any(not isinstance(item, str) for item in topologies)
            or len(topologies) != len(set(topologies))
            or any(item not in _V2_TOPOLOGIES for item in topologies)
            or topology_kind not in topologies
        ):
            raise EvidenceValidationError("v2 metric applicability is invalid")
        threshold = definition["threshold"]
        if threshold is not None and (
            not isinstance(threshold, dict)
            or set(threshold) != {"operator", "value"}
            or threshold["operator"] not in {"lt", "lte", "gt", "gte", "eq"}
            or not _finite_number(threshold["value"])
        ):
            raise EvidenceValidationError("v2 metric threshold is invalid")
        _safe_reason(definition["null_semantics"], "v2 metric null semantics")
        raw = metric_value["raw_evidence_value"]
        projected_value = metric_value["value"]
        if raw != projected_value or raw != metrics[evidence_field]:
            raise EvidenceValidationError("v2 metric raw evidence binding is invalid")
        if metric == "collision" and not isinstance(projected_value, bool):
            raise EvidenceValidationError("v2 collision metric value is invalid")
        if metric in {"hard_braking", "minimum_ttc", "completion_time"} and (
            projected_value is not None and not _finite_number(projected_value)
        ):
            raise EvidenceValidationError("v2 numeric metric value is invalid")
        if metric == "termination_reason":
            _safe_reason(projected_value, "v2 termination reason metric")
        expected_threshold = PublishedEvidenceReader._threshold_met_v2(
            projected_value,
            threshold,
        )
        if metric_value["threshold_met"] != expected_threshold:
            raise EvidenceValidationError("v2 metric threshold result is invalid")
        return {
            "definition_id": definition_id,
            "metric": metric,
            "unit": definition["unit"],
            "participant_ids": list(applicable_participants),
            "topology_kinds": list(topologies),
            "value": projected_value,
            "threshold": threshold,
            "threshold_met": metric_value["threshold_met"],
            "null_semantics": definition["null_semantics"],
            "explanation": _V2_METRIC_EXPLANATIONS[metric],
            "raw_evidence_value": raw,
            "evidence_field": evidence_field,
        }

    @staticmethod
    def _threshold_met_v2(value: object, threshold: object) -> bool | None:
        if value is None or threshold is None:
            return None
        if isinstance(value, bool):
            actual: int | float = int(value)
        elif _finite_number(value):
            actual = value
        else:
            return None
        if not isinstance(threshold, dict):
            return None
        target = threshold["value"]
        return {
            "lt": actual < target,
            "lte": actual <= target,
            "gt": actual > target,
            "gte": actual >= target,
            "eq": actual == target,
        }[threshold["operator"]]

    @staticmethod
    def _predicate_results_v2(value: object, constraints: Mapping[str, Any]) -> None:
        if not isinstance(value, dict) or set(value) != {"success", "failure"}:
            raise EvidenceValidationError("v2 predicate results are invalid")
        for axis in ("success", "failure"):
            results = value[axis]
            declared = constraints.get(f"{axis}_predicates")
            if not isinstance(results, list) or not isinstance(declared, list):
                raise EvidenceValidationError("v2 predicate results are invalid")
            expected = [
                {"predicate_id": item.get("id"), "kind": item.get("kind")}
                for item in declared
                if isinstance(item, dict)
            ]
            if len(expected) != len(declared) or len(results) != len(expected):
                raise EvidenceValidationError("v2 predicate results are invalid")
            for item, identity in zip(results, expected, strict=True):
                if (
                    not isinstance(item, dict)
                    or set(item) != {"predicate_id", "kind", "satisfied"}
                    or {key: item[key] for key in ("predicate_id", "kind")} != identity
                    or not isinstance(item["satisfied"], bool)
                ):
                    raise EvidenceValidationError("v2 predicate results are invalid")

    def _events(
        self,
        opened: _OpenedRun,
        participants: list[dict[str, str]],
    ) -> list[dict[str, object]]:
        value, _ = self._indexed_json(opened, "events", require_verified=True)
        if not isinstance(value, list):
            raise EvidenceValidationError("events artifact is invalid")
        participant_ids = {item["id"] for item in participants}
        projected: list[dict[str, object]] = []
        ordering: list[tuple[int, int, str]] = []
        fields = {
            "schema_version",
            "event_id",
            "type",
            "participant_id",
            "trigger_tick",
            "effect_state_tick",
            "priority_contract",
            "action",
        }
        for event in value:
            if not isinstance(event, dict) or set(event) != fields:
                raise EvidenceValidationError("events artifact is invalid")
            if event["schema_version"] != "scenarioforge.event/v1":
                raise EvidenceValidationError("events artifact is invalid")
            for field in ("event_id", "type"):
                _safe_reason(event[field], f"event {field}")
            if event["participant_id"] not in participant_ids:
                raise EvidenceValidationError("event participant is invalid")
            trigger = event["trigger_tick"]
            effect = event["effect_state_tick"]
            if (
                not _is_int(trigger)
                or not _is_int(effect)
                or trigger < 0
                or effect < trigger
            ):
                raise EvidenceValidationError("event tick is invalid")
            if event["priority_contract"] != "scenarioforge.trigger-priority/v1":
                raise EvidenceValidationError("event priority contract is invalid")
            action = event["action"]
            if (
                not isinstance(action, dict)
                or set(action) != {"steering", "throttle_brake"}
                or not all(_finite_number(item) for item in action.values())
            ):
                raise EvidenceValidationError("event action is invalid")
            ordering.append((trigger, effect, event["event_id"]))
            projected.append(
                {
                    "event_id": event["event_id"],
                    "type": event["type"],
                    "participant_id": event["participant_id"],
                    "trigger_tick": trigger,
                    "effect_state_tick": effect,
                }
            )
        if ordering != sorted(ordering):
            raise EvidenceValidationError("events artifact is not ordered")
        return projected

    def _events_v2(
        self,
        opened: _OpenedRun,
        manifest: Mapping[str, Any],
        participants: list[dict[str, str]],
    ) -> list[dict[str, object]]:
        value, _ = self._indexed_json(opened, "events", require_verified=True)
        if not isinstance(value, list):
            raise EvidenceValidationError("v2 events artifact is invalid")
        participant_ids = {item["id"] for item in participants}
        declared_events = self._scenario_instance(manifest).get("events")
        if not isinstance(declared_events, list):
            raise EvidenceValidationError("v2 declared events are invalid")
        declared_by_id: dict[str, Mapping[str, Any]] = {}
        for declared in declared_events:
            if not isinstance(declared, dict):
                raise EvidenceValidationError("v2 declared event is invalid")
            event_id = declared.get("id")
            if (
                not isinstance(event_id, str)
                or _SAFE_ID.fullmatch(event_id) is None
                or event_id in declared_by_id
            ):
                raise EvidenceValidationError("v2 declared event identity is invalid")
            declared_by_id[event_id] = declared
        projected: list[dict[str, object]] = []
        ordering: list[tuple[int, int, int, str]] = []
        event_ids: list[str] = []
        fields = {
            "schema_version",
            "event_id",
            "sequence",
            "type",
            "participant_id",
            "trigger_tick",
            "effect_state_tick",
            "priority_contract",
            "action",
        }
        for event in value:
            if not isinstance(event, dict) or set(event) != fields:
                raise EvidenceValidationError("v2 events artifact is invalid")
            if event["schema_version"] != "scenarioforge.event/v2":
                raise EvidenceValidationError("v2 event schema is invalid")
            for field in ("event_id", "type"):
                _safe_reason(event[field], f"v2 event {field}")
            sequence = event["sequence"]
            trigger = event["trigger_tick"]
            effect = event["effect_state_tick"]
            participant_id = event["participant_id"]
            if (
                not isinstance(participant_id, str)
                or participant_id not in participant_ids
                or not _is_int(sequence)
                or sequence < 0
                or not _is_int(trigger)
                or not _is_int(effect)
                or trigger < 0
                or effect < trigger
                or event["priority_contract"] != "scenarioforge.trigger-priority/v2"
            ):
                raise EvidenceValidationError("v2 event binding is invalid")
            action = event["action"]
            if (
                not isinstance(action, dict)
                or set(action) != {"steering", "throttle_brake"}
                or not all(_finite_number(item) for item in action.values())
            ):
                raise EvidenceValidationError("v2 event action is invalid")
            declared = declared_by_id.get(event["event_id"])
            if not self._v2_event_matches_declaration(event, declared):
                raise EvidenceValidationError("v2 event is not manifest-bound")
            assert declared is not None
            ordering.append((trigger, effect, sequence, event["event_id"]))
            event_ids.append(event["event_id"])
            projected.append(
                {
                    "event_id": event["event_id"],
                    "sequence": sequence,
                    "type": event["type"],
                    "participant_id": event["participant_id"],
                    "trigger_tick": trigger,
                    "effect_state_tick": effect,
                    "duration_ticks": int(declared.get("duration_ticks", 1)),
                    "action": dict(event["action"]),
                }
            )
        if (
            ordering != sorted(ordering)
            or len(event_ids) != len(set(event_ids))
            or [item["sequence"] for item in projected] != list(range(len(projected)))
        ):
            raise EvidenceValidationError("v2 events artifact is not ordered")
        return projected

    @staticmethod
    def _v2_event_matches_declaration(
        event: Mapping[str, Any],
        declared: Mapping[str, Any] | None,
    ) -> bool:
        if declared is None:
            return False
        trigger = declared.get("trigger")
        action = declared.get("action")
        if not isinstance(trigger, dict) or not isinstance(action, dict):
            return False
        return (
            declared.get("sequence") == event["sequence"]
            and declared.get("type") == "control_override"
            and event["type"] == "trigger_fired"
            and declared.get("participant_id") == event["participant_id"]
            and trigger
            == {
                "schema_version": "scenarioforge.trigger/v2",
                "kind": "tick",
                "tick": event["trigger_tick"],
            }
            and event["effect_state_tick"] == event["trigger_tick"] + 1
            and action
            == {
                "schema_version": "scenarioforge.control-action/v2",
                "steering": event["action"]["steering"],
                "throttle_brake": event["action"]["throttle_brake"],
            }
        )

    def _worker_result_v2(
        self,
        opened: _OpenedRun,
        metrics: Mapping[str, object],
        road: Mapping[str, object],
    ) -> dict[str, object]:
        value, _ = self._indexed_json(opened, "worker_result", require_verified=True)
        fields = {
            "schema_version",
            "run_id",
            "attempt_id",
            "worker_pid",
            "backend",
            "execution_plan_digest",
            "completed_steps",
            "collision",
            "termination_reason",
            "execution_status",
            "scenario_outcome",
            "road_geometry",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise EvidenceValidationError("v2 Worker result is invalid")
        axes = ("execution_status", "scenario_outcome", "termination_reason")
        if (
            value["schema_version"] != "scenarioforge.worker-result/v2"
            or value["run_id"] != opened.result["run_id"]
            or value["attempt_id"] != opened.result["attempt_id"]
            or any(value[field] != opened.result[field] for field in axes)
            or value["execution_plan_digest"] != opened.result["execution_plan_digest"]
            or value["completed_steps"] != metrics["terminal_tick"]
            or value["collision"] != metrics["collision"]
            or not _is_int(value["worker_pid"])
            or value["worker_pid"] <= 0
            or opened.result["worker_exit_code"] != 0
        ):
            raise EvidenceValidationError("v2 Worker terminal binding is invalid")
        backend = value["backend"]
        if not isinstance(backend, dict) or set(backend) != {
            "distribution",
            "version",
            "asset_version",
            "engine_class",
        }:
            raise EvidenceValidationError("v2 Worker backend evidence is invalid")
        for field in backend:
            item = backend[field]
            if not isinstance(item, str) or not item or len(item) > 128:
                raise EvidenceValidationError("v2 Worker backend evidence is invalid")
        return self._road_geometry_v2(value["road_geometry"], road)

    @staticmethod
    def _road_geometry_v2(
        value: object,
        road: Mapping[str, object],
    ) -> dict[str, object]:
        fields = {
            "schema_version",
            "coordinate_system",
            "source",
            "lanes",
            "conflict_zones",
        }
        if (
            not isinstance(value, dict)
            or set(value) != fields
            or value["schema_version"] != "scenarioforge.road-geometry/v1"
            or value["coordinate_system"] != road["coordinate_system"]
            or value["source"] != "metadrive-road-network"
        ):
            raise EvidenceValidationError("v2 road geometry is invalid")

        declared_lanes = road["lanes"]
        if not isinstance(declared_lanes, list):
            raise EvidenceValidationError("v2 road geometry is invalid")
        declared_lane_by_id = {str(item["id"]): item for item in declared_lanes}
        lanes = value["lanes"]
        if not isinstance(lanes, list) or [item.get("lane_id") for item in lanes if isinstance(item, dict)] != list(declared_lane_by_id):
            raise EvidenceValidationError("v2 road geometry lanes are invalid")

        def validated_points(points: object) -> list[list[float]]:
            if (
                not isinstance(points, list)
                or not 2 <= len(points) <= 512
                or any(
                    not isinstance(point, list)
                    or len(point) != 2
                    or not all(_finite_number(coordinate) for coordinate in point)
                    for point in points
                )
            ):
                raise EvidenceValidationError("v2 road geometry points are invalid")
            return [[float(point[0]), float(point[1])] for point in points]

        projected_lanes: list[dict[str, object]] = []
        for lane in lanes:
            if not isinstance(lane, dict) or set(lane) != {
                "lane_id",
                "kind",
                "centerline_m",
                "left_boundary_m",
                "right_boundary_m",
            }:
                raise EvidenceValidationError("v2 road geometry lane is invalid")
            lane_id = str(lane["lane_id"])
            declared = declared_lane_by_id.get(lane_id)
            if declared is None or lane["kind"] != declared["kind"]:
                raise EvidenceValidationError("v2 road geometry lane binding is invalid")
            centerline = validated_points(lane["centerline_m"])
            left = validated_points(lane["left_boundary_m"])
            right = validated_points(lane["right_boundary_m"])
            if len({len(centerline), len(left), len(right)}) != 1:
                raise EvidenceValidationError("v2 road geometry lane points are invalid")
            projected_lanes.append(
                {
                    "lane_id": lane_id,
                    "kind": lane["kind"],
                    "centerline_m": centerline,
                    "left_boundary_m": left,
                    "right_boundary_m": right,
                }
            )

        declared_zones = road["conflict_zones"]
        if not isinstance(declared_zones, list):
            raise EvidenceValidationError("v2 conflict geometry is invalid")
        declared_zone_by_id = {str(item["id"]): item for item in declared_zones}
        zones = value["conflict_zones"]
        if not isinstance(zones, list) or [item.get("zone_id") for item in zones if isinstance(item, dict)] != list(declared_zone_by_id):
            raise EvidenceValidationError("v2 conflict geometry is invalid")
        projected_zones: list[dict[str, object]] = []
        for zone in zones:
            if not isinstance(zone, dict) or set(zone) != {
                "zone_id",
                "start_m",
                "end_m",
                "lane_regions",
            }:
                raise EvidenceValidationError("v2 conflict geometry is invalid")
            zone_id = str(zone["zone_id"])
            declared = declared_zone_by_id.get(zone_id)
            if (
                declared is None
                or zone["start_m"] != declared["start_m"]
                or zone["end_m"] != declared["end_m"]
            ):
                raise EvidenceValidationError("v2 conflict geometry binding is invalid")
            regions = zone["lane_regions"]
            if not isinstance(regions, list) or [item.get("lane_id") for item in regions if isinstance(item, dict)] != declared["lane_ids"]:
                raise EvidenceValidationError("v2 conflict geometry regions are invalid")
            projected_regions: list[dict[str, object]] = []
            for region in regions:
                if not isinstance(region, dict) or set(region) != {
                    "lane_id",
                    "left_boundary_m",
                    "right_boundary_m",
                }:
                    raise EvidenceValidationError("v2 conflict geometry region is invalid")
                left = validated_points(region["left_boundary_m"])
                right = validated_points(region["right_boundary_m"])
                if len(left) != len(right):
                    raise EvidenceValidationError("v2 conflict geometry points are invalid")
                projected_regions.append(
                    {
                        "lane_id": region["lane_id"],
                        "left_boundary_m": left,
                        "right_boundary_m": right,
                    }
                )
            projected_zones.append(
                {
                    "zone_id": zone_id,
                    "start_m": zone["start_m"],
                    "end_m": zone["end_m"],
                    "lane_regions": projected_regions,
                }
            )
        return {
            "schema_version": value["schema_version"],
            "coordinate_system": value["coordinate_system"],
            "source": value["source"],
            "lanes": projected_lanes,
            "conflict_zones": projected_zones,
        }

    @staticmethod
    def _validate_v2_evidence_binding(
        metrics: Mapping[str, object],
        trajectory: list[dict[str, object]],
        events: list[dict[str, object]],
    ) -> None:
        collision_participants = sorted(
            {
                str(point["participant_id"])
                for point in trajectory
                if point["collision"] is True
            }
        )
        if collision_participants != metrics["collision_participants"]:
            raise EvidenceValidationError(
                "v2 trajectory collision evidence does not match metrics"
            )
        terminal_tick = metrics["terminal_tick"]
        if any(event["effect_state_tick"] > terminal_tick for event in events):
            raise EvidenceValidationError("v2 event extends beyond terminal trajectory")

    def _failure(self, opened: _OpenedRun) -> Mapping[str, Any]:
        value, _ = self._indexed_json(opened, "failure", require_verified=True)
        required = {
            "schema_version",
            "run_id",
            "attempt_id",
            "failure_kind",
            "failure_stage",
            "reason",
            "worker_exit_code",
            "termination",
        }
        if not isinstance(value, dict) or not required.issubset(value):
            raise EvidenceValidationError("failure evidence is invalid")
        if value["schema_version"] != "scenarioforge.failure-evidence/v1":
            raise EvidenceValidationError("failure evidence schema is invalid")
        if (
            value["run_id"] != opened.result["run_id"]
            or value["attempt_id"] != opened.result["attempt_id"]
        ):
            raise EvidenceValidationError("failure evidence identity is invalid")
        for field in ("failure_kind", "failure_stage", "reason"):
            _safe_reason(value[field], f"failure evidence {field}")
        if (
            value["reason"] != opened.result["reason"]
            or value["worker_exit_code"] != opened.result["worker_exit_code"]
        ):
            raise EvidenceValidationError(
                "failure evidence terminal binding is invalid"
            )
        termination = value["termination"]
        if (
            not isinstance(termination, dict)
            or termination.get("trigger") != value["failure_kind"]
            or termination.get("complete") is not True
            or termination.get("remaining_pids") != []
        ):
            raise EvidenceValidationError("failure process-tree evidence is invalid")
        return value

    @staticmethod
    def _trajectory(
        value: Any,
        participants: list[dict[str, str]],
        *,
        terminal_tick: object,
    ) -> list[dict[str, object]]:
        if not isinstance(value, list) or not value:
            raise EvidenceValidationError("trajectory artifact is invalid")
        participant_ids = tuple(item["id"] for item in participants)
        fields = {
            "schema_version",
            "tick",
            "participant_id",
            "position_m",
            "speed_mps",
            "heading_deg",
            "collision",
        }
        current_tick = -1
        current_participants: list[str] = []
        for point in value:
            if not isinstance(point, dict) or set(point) != fields:
                raise EvidenceValidationError("trajectory point schema is invalid")
            if point["schema_version"] != "scenarioforge.trajectory-point/v1":
                raise EvidenceValidationError("trajectory point schema is invalid")
            tick = point["tick"]
            participant_id = point["participant_id"]
            if not _is_int(tick) or tick < 0:
                raise EvidenceValidationError("trajectory tick is invalid")
            if participant_id not in participant_ids:
                raise EvidenceValidationError("trajectory participant is invalid")
            if tick != current_tick:
                if current_tick >= 0 and tuple(current_participants) != participant_ids:
                    raise EvidenceValidationError(
                        "trajectory stable participant set is invalid"
                    )
                if tick != current_tick + 1:
                    raise EvidenceValidationError("trajectory ticks are not ordered")
                current_tick = tick
                current_participants = []
            current_participants.append(participant_id)
            if len(set(current_participants)) != len(current_participants):
                raise EvidenceValidationError("trajectory participant is duplicated")
            position = point["position_m"]
            if (
                not isinstance(position, list)
                or len(position) != 2
                or not all(_finite_number(item) for item in position)
                or not _finite_number(point["speed_mps"])
                or not _finite_number(point["heading_deg"])
                or not isinstance(point["collision"], bool)
            ):
                raise EvidenceValidationError("trajectory numeric fields are invalid")
        if tuple(current_participants) != participant_ids:
            raise EvidenceValidationError(
                "trajectory stable participant set is invalid"
            )
        if current_tick != terminal_tick:
            raise EvidenceValidationError("trajectory terminal tick is invalid")
        return value

    def _trajectory_v2(
        self,
        value: Any,
        manifest: Mapping[str, Any],
        participants: list[dict[str, str]],
        *,
        terminal_tick: object,
    ) -> list[dict[str, object]]:
        if not isinstance(value, list) or not value:
            raise EvidenceValidationError("v2 trajectory artifact is invalid")
        participant_order = tuple(item["id"] for item in participants)
        participant_positions = {
            participant_id: index
            for index, participant_id in enumerate(participant_order)
        }
        road = self._road_v2(manifest)
        lanes = {str(item["id"]): item for item in road["lanes"]}
        raw_participants = self._scenario_instance(manifest).get("participants")
        if not isinstance(raw_participants, list):
            raise EvidenceValidationError("v2 participant routes are invalid")
        route_by_participant: dict[str, dict[str, object]] = {}
        for raw in raw_participants:
            raw_id = raw.get("id") if isinstance(raw, dict) else None
            if not isinstance(raw_id, str) or raw_id not in participant_positions:
                raise EvidenceValidationError("v2 participant route is invalid")
            route = raw.get("route")
            if not isinstance(route, dict) or set(route) != {
                "schema_version",
                "id",
                "lane_ids",
                "goal",
            }:
                raise EvidenceValidationError("v2 participant route is invalid")
            goal = route["goal"]
            route_lanes = route["lane_ids"]
            if (
                route["schema_version"] != "scenarioforge.route/v2"
                or not isinstance(route["id"], str)
                or _SAFE_ID.fullmatch(route["id"]) is None
                or not isinstance(route_lanes, list)
                or not route_lanes
                or any(not isinstance(item, str) for item in route_lanes)
                or len(route_lanes) != len(set(route_lanes))
                or any(item not in lanes for item in route_lanes)
                or not isinstance(goal, dict)
                or set(goal) != {"lane_id", "longitudinal_m"}
                or not isinstance(goal["lane_id"], str)
                or goal["lane_id"] not in route_lanes
                or not _finite_number(goal["longitudinal_m"])
            ):
                raise EvidenceValidationError("v2 participant route is invalid")
            nodes: list[str] = []
            for lane_id in route_lanes:
                engine = lanes[lane_id]["engine_lane_index"]
                start_node = str(engine["start_node"])
                end_node = str(engine["end_node"])
                if not nodes:
                    nodes.extend((start_node, end_node))
                elif nodes[-1] == start_node:
                    nodes.append(end_node)
                elif len(nodes) >= 2 and nodes[-2:] == [start_node, end_node]:
                    continue
                else:
                    raise EvidenceValidationError(
                        "v2 participant route is disconnected"
                    )
            destination = lanes[goal["lane_id"]]["engine_lane_index"]
            route_by_participant[raw_id] = {
                "id": route["id"],
                "goal_lane_id": goal["lane_id"],
                "destination": [
                    destination["start_node"],
                    destination["end_node"],
                    destination["lane_index"],
                ],
                "checkpoints": nodes,
            }

        fields = {
            "schema_version",
            "tick",
            "participant_id",
            "position_m",
            "speed_mps",
            "heading_deg",
            "collision",
            "lane_id",
            "engine_lane_index",
            "lane_longitudinal_m",
            "route_id",
            "route_destination_lane_id",
            "route_destination_engine_lane_index",
            "route_destination_matches",
            "route_checkpoints",
            "route_completed",
            "boundary_violation",
            "wrong_route",
        }
        current_tick = -1
        current_participants: list[str] = []
        for point in value:
            if not isinstance(point, dict) or set(point) != fields:
                raise EvidenceValidationError("v2 trajectory point schema is invalid")
            tick = point["tick"]
            participant_id = point["participant_id"]
            if (
                point["schema_version"] != "scenarioforge.trajectory-point/v2"
                or not _is_int(tick)
                or tick < 0
                or not isinstance(participant_id, str)
                or participant_id not in participant_positions
            ):
                raise EvidenceValidationError("v2 trajectory identity is invalid")
            if tick != current_tick:
                if current_tick >= 0:
                    self._validate_v2_tick_participants(
                        current_participants,
                        participant_positions,
                        require_complete=current_tick == 0,
                    )
                if tick != current_tick + 1:
                    raise EvidenceValidationError("v2 trajectory ticks are not ordered")
                current_tick = tick
                current_participants = []
            current_participants.append(participant_id)

            position = point["position_m"]
            lane_id = point["lane_id"]
            route = route_by_participant[participant_id]
            expected_engine = (
                lanes.get(lane_id, {}).get("engine_lane_index")
                if isinstance(lane_id, str)
                else None
            )
            expected_engine_list = (
                [
                    expected_engine["start_node"],
                    expected_engine["end_node"],
                    expected_engine["lane_index"],
                ]
                if isinstance(expected_engine, dict)
                else None
            )
            destination = point["route_destination_engine_lane_index"]
            if (
                not isinstance(position, list)
                or len(position) != 2
                or not all(_finite_number(item) for item in position)
                or not _finite_number(point["speed_mps"])
                or not _finite_number(point["heading_deg"])
                or not isinstance(point["collision"], bool)
                or lane_id not in lanes
                or not self._engine_lane_index_valid(
                    point["engine_lane_index"],
                    allow_none=False,
                )
                or point["engine_lane_index"] != expected_engine_list
                or not _finite_number(point["lane_longitudinal_m"])
                or point["route_id"] != route["id"]
                or point["route_destination_lane_id"] != route["goal_lane_id"]
                or not self._engine_lane_index_valid(destination, allow_none=True)
                or not isinstance(point["route_destination_matches"], bool)
                or point["route_destination_matches"]
                != (destination == route["destination"])
                or point["route_checkpoints"] != route["checkpoints"]
                or not all(
                    isinstance(point[field], bool)
                    for field in (
                        "route_completed",
                        "boundary_violation",
                        "wrong_route",
                    )
                )
            ):
                raise EvidenceValidationError("v2 trajectory state is invalid")
        self._validate_v2_tick_participants(
            current_participants,
            participant_positions,
            require_complete=current_tick == 0,
        )
        if current_tick != terminal_tick:
            raise EvidenceValidationError("v2 trajectory terminal tick is invalid")
        return value

    @staticmethod
    def _validate_v2_tick_participants(
        current: list[str],
        participant_positions: Mapping[str, int],
        *,
        require_complete: bool,
    ) -> None:
        if (
            not current
            or len(current) != len(set(current))
            or [participant_positions[item] for item in current]
            != sorted(participant_positions[item] for item in current)
            or (require_complete and len(current) != len(participant_positions))
        ):
            raise EvidenceValidationError("v2 trajectory participant set is invalid")

    @staticmethod
    def _evidence_summary(opened: _OpenedRun) -> list[dict[str, object]]:
        return [
            {
                "ref": f"{opened.logical_ref}/{entry.path}",
                "status": entry.status,
                "size_bytes": entry.size_bytes,
                "digest": entry.digest,
                "validation": entry.validation,
            }
            for entry in opened.artifacts.values()
        ]


EvidenceReader = PublishedEvidenceReader

__all__ = [
    "EvidenceError",
    "EvidenceReader",
    "EvidenceValidationError",
    "InvalidEvidenceIdentifierError",
    "NonPlayableRunError",
    "PublishedEvidenceReader",
    "UnknownArtifactError",
    "UnknownPublishedRunError",
    "validate_artifact_key",
]
