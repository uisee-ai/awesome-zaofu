from __future__ import annotations

import json
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from pydantic import TypeAdapter, ValidationError

from scenarioforge.bundle import BundleIntegrityError, BundleManifest, verify_bundle
from scenarioforge.runtime.models import RunRecord

from .models import (
    ReplayBundle,
    ReplayCase,
    ReplayEvent,
    ReplayExecution,
    ReplayFrame,
    ReplayMetrics,
    ReplayProvider,
    ReplaySafetyEvidence,
)


class ReplayLoadError(ValueError):
    """Public, path-free error raised before an unsafe bundle is consumed."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _reject(code: str, message: str) -> NoReturn:
    raise ReplayLoadError(code, message)


def _scan_tree(bundle_path: Path) -> set[str]:
    try:
        root_stat = bundle_path.lstat()
    except OSError:
        _reject("bundle_not_found", "bundle is unavailable")
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        _reject("unsafe_filesystem_entry", "bundle directory is not a regular directory")

    files: set[str] = set()
    pending: list[tuple[Path, PurePosixPath]] = [(bundle_path, PurePosixPath())]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            _reject("bundle_unreadable", "bundle cannot be inspected")
        for entry in entries:
            relative = relative_directory / entry.name
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                _reject("bundle_unreadable", "bundle entry cannot be inspected")
            if entry.is_symlink():
                _reject("unsafe_filesystem_entry", "symbolic links are forbidden in bundles")
            if stat.S_ISDIR(entry_stat.st_mode):
                pending.append((Path(entry.path), relative))
            elif stat.S_ISREG(entry_stat.st_mode):
                if entry_stat.st_nlink != 1:
                    _reject("unsafe_filesystem_entry", "hard-linked files are forbidden in bundles")
                files.add(relative.as_posix())
            else:
                _reject("unsafe_filesystem_entry", "special filesystem entries are forbidden in bundles")
    return files


def _verified_manifest(bundle_path: Path, files: set[str]) -> BundleManifest:
    try:
        manifest = verify_bundle(bundle_path)
    except BundleIntegrityError:
        _reject("bundle_integrity", "sealed bundle integrity verification failed")
    expected = {"manifest.json", "bundle.sha256", *(item.path for item in manifest.artifacts)}
    if files != expected:
        _reject("unexpected_artifact", "bundle contains files outside its sealed manifest")
    return manifest


def _load_json(bundle_path: Path, artifact_name: str, artifacts: set[str]) -> Any:
    if artifact_name not in artifacts:
        _reject("bundle_schema", "sealed bundle is missing a required replay artifact")
    try:
        return json.loads(bundle_path.joinpath(*PurePosixPath(artifact_name).parts).read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _reject("bundle_schema", "replay artifact is not valid JSON")


def _events(frames: tuple[ReplayFrame, ...], record: RunRecord) -> tuple[ReplayEvent, ...]:
    events: list[ReplayEvent] = []
    for frame in frames:
        if frame.collision:
            events.append(ReplayEvent(tick=frame.step, kind="collision", label="Collision"))
        if frame.off_road:
            events.append(ReplayEvent(tick=frame.step, kind="off_road", label="Off road"))
    events.append(
        ReplayEvent(
            tick=frames[-1].step if frames else record.steps,
            kind="termination",
            label=record.termination_reason,
        )
    )
    return tuple(events)


def _parse_cases(bundle_path: Path, artifacts: set[str]) -> tuple[ReplayCase, ...]:
    try:
        records = TypeAdapter(list[RunRecord]).validate_python(
            _load_json(bundle_path, "run_records.json", artifacts), strict=True
        )
    except ValidationError:
        _reject("bundle_schema", "run records do not match the replay schema")
    if tuple(record.case_index for record in records) != tuple(range(len(records))):
        _reject("bundle_schema", "run record case indexes are not contiguous")

    cases: list[ReplayCase] = []
    frame_adapter = TypeAdapter(list[ReplayFrame])
    for record in records:
        artifact_name = f"traces/case-{record.case_index:03d}.json"
        try:
            parsed_frames = frame_adapter.validate_python(
                _load_json(bundle_path, artifact_name, artifacts), strict=True
            )
        except ValidationError:
            _reject("bundle_schema", "trace frames do not match the replay schema")
        frames = tuple(parsed_frames)
        if any(next_frame.step <= frame.step for frame, next_frame in zip(frames, frames[1:])):
            _reject("bundle_schema", "trace frame ticks are not strictly ordered")
        if frames and frames[-1].step != record.steps:
            _reject("bundle_schema", "trace terminal tick does not match the run record")
        cases.append(
            ReplayCase(
                case_index=record.case_index,
                seed=record.seed,
                status=record.status,
                scenario_verdict=record.scenario_verdict,
                termination_reason=record.termination_reason,
                steps=record.steps,
                simulated_seconds=record.simulated_seconds,
                collision=record.collision,
                off_road=record.off_road,
                route_progress=record.route_progress,
                frames=frames,
                events=_events(frames, record),
            )
        )
    return tuple(cases)


def _parse_metrics(bundle_path: Path, artifacts: set[str], cases: tuple[ReplayCase, ...]) -> ReplayMetrics:
    payload = _load_json(bundle_path, "metrics.json", artifacts)
    try:
        metrics = ReplayMetrics.model_validate(
            {
                key: payload[key]
                for key in (
                    "case_count",
                    "completed_count",
                    "failed_count",
                    "total_steps",
                    "total_case_wall_seconds",
                    "total_cpu_seconds",
                    "peak_worker_rss_bytes",
                )
            }
        )
    except (KeyError, TypeError, ValidationError):
        _reject("bundle_schema", "run metrics do not match the replay schema")
    if metrics.case_count != len(cases) or metrics.total_steps != sum(case.steps for case in cases):
        _reject("bundle_schema", "run metrics disagree with recorded cases")
    return metrics


def _parse_provider(bundle_path: Path, artifacts: set[str], case_count: int) -> ReplayProvider:
    payload = _load_json(bundle_path, "provenance.json", artifacts)
    try:
        case_provenance = payload["cases"]
        if len(case_provenance) != case_count or not case_provenance:
            raise ValueError
        public = {
            "backend": payload["backend"],
            "backend_version": payload["backend_version"],
            "execution_kind": case_provenance[0]["execution_kind"],
            "network_policy": case_provenance[0]["network_policy"],
            "auto_download": case_provenance[0]["auto_download"],
        }
        if any(
            any(item.get(key) != public[key] for key in ("execution_kind", "network_policy", "auto_download"))
            for item in case_provenance
        ):
            raise ValueError
        return ReplayProvider.model_validate(public)
    except (KeyError, TypeError, ValueError, ValidationError):
        _reject("bundle_schema", "provider provenance is not eligible for exact offline replay")


def _parse_safety_evidence(
    bundle_path: Path, artifacts: set[str], cases: tuple[ReplayCase, ...]
) -> ReplaySafetyEvidence | None:
    if "safety_evidence.json" not in artifacts:
        return None
    try:
        evidence = ReplaySafetyEvidence.model_validate(
            _load_json(bundle_path, "safety_evidence.json", artifacts)
        )
    except ValidationError:
        _reject("bundle_schema", "safety evidence does not match the replay schema")
    if tuple(item.case_index for item in evidence.cases) != tuple(case.case_index for case in cases):
        _reject("bundle_schema", "safety evidence case indexes disagree with replay cases")
    for safety_case, replay_case in zip(evidence.cases, cases, strict=True):
        if (
            safety_case.metrics.collision != replay_case.collision
            or safety_case.metrics.off_road != replay_case.off_road
            or safety_case.metrics.route_progress != replay_case.route_progress
        ):
            _reject("bundle_schema", "safety evidence disagrees with canonical replay state")
    return evidence


def load_replay_bundle(bundle_path: Path) -> ReplayBundle:
    """Verify and project a sealed real-provider bundle without importing MetaDrive."""

    files = _scan_tree(bundle_path)
    manifest = _verified_manifest(bundle_path, files)
    artifacts = {item.path for item in manifest.artifacts}
    cases = _parse_cases(bundle_path, artifacts)
    metrics = _parse_metrics(bundle_path, artifacts, cases)
    safety_evidence = _parse_safety_evidence(bundle_path, artifacts, cases)
    provider = _parse_provider(bundle_path, artifacts, len(cases))
    return ReplayBundle(
        schema_version="scenarioforge.replay.v1",
        bundle_id=manifest.bundle_id,
        status=manifest.status,
        scenario_digest=manifest.scenario_digest,
        cases=cases,
        metrics=metrics,
        safety_evidence=safety_evidence,
        provider=provider,
        execution=ReplayExecution(
            runner_state="stopped",
            metadrive_calls=0,
            external_network="denied",
        ),
    )
