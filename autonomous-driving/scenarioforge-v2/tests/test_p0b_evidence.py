from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import canonical_bytes, canonical_digest
from scenarioforge.web.evidence import (
    EvidenceValidationError,
    InvalidEvidenceIdentifierError,
    NonPlayableRunError,
    PublishedEvidenceReader,
    UnknownPublishedRunError,
)


RUN_ID = "run-evidence-0001"
ATTEMPT_ID = "attempt-0001"
ZERO_DIGEST = "0" * 64


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(status: str) -> dict[str, Any]:
    return {
        "schema_version": "scenarioforge.run-manifest/v1",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "scenario_instance": {
            "schema_version": "scenarioforge.scenario-instance/v1",
            "scenario_id": "brake-lead-happy",
            "road": {
                "template": "straight",
                "lane_count": 2,
                "lane_width_m": 3.5,
                "length_m": 120.0,
                "coordinate_system": "right-handed-x-forward-y-left",
                "units": {
                    "distance": "m",
                    "speed": "m/s",
                    "heading": "deg",
                    "time": "tick",
                },
            },
            "participants": [
                {"id": "ego", "role": "ego", "initial": {}, "target": {}},
                {"id": "lead", "role": "social", "initial": {}, "target": {}},
            ],
        },
        "seed": 7,
        "policy": {
            "id": "scenarioforge.constant-lane",
            "version": "1.0.0",
            "config_digest": "1" * 64,
        },
        "output_staging": {
            "logical_id": "staging-run-evidence-0001-attempt-0001",
            "host_secret": "/do/not/project",
        },
        "terminal_hint": status,
    }


def _events() -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "scenarioforge.event/v1",
            "event_id": "lead-brake",
            "type": "trigger_fired",
            "participant_id": "lead",
            "trigger_tick": 1,
            "effect_state_tick": 2,
            "priority_contract": "scenarioforge.trigger-priority/v1",
            "action": {"steering": 0.0, "throttle_brake": -1.0},
        }
    ]


def _trajectory() -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "scenarioforge.trajectory-point/v1",
            "tick": tick,
            "participant_id": participant_id,
            "position_m": [float(tick + offset), float(offset)],
            "speed_mps": float(8 - tick),
            "heading_deg": 0.0,
            "collision": False,
        }
        for tick in range(3)
        for offset, participant_id in enumerate(("ego", "lead"))
    ]


def _metrics() -> dict[str, Any]:
    return {
        "schema_version": "scenarioforge.metrics/v1",
        "collision": False,
        "collision_participants": [],
        "termination_reason": "horizon_completed",
        "terminal_status": "success",
        "min_ttc_s": 1.25,
        "completed_steps": 2,
        "sample_interval_s": 0.1,
    }


def _publish(
    workspace: Path,
    *,
    status: str = "success",
    trajectory: Any | None = None,
    trajectory_validation: str | None = None,
) -> Path:
    root = workspace / "published" / RUN_ID / ATTEMPT_ID
    manifest = _manifest(status)
    _write_json(root / "input" / "run_manifest.json", manifest)

    if status == "success":
        _write_json(root / "output" / "metrics.json", _metrics())
        _write_json(root / "output" / "events.json", _events())
        trajectory_path = root / "output" / "trajectory.json"
        trajectory_value = _trajectory() if trajectory is None else trajectory
        if isinstance(trajectory_value, bytes):
            trajectory_path.parent.mkdir(parents=True, exist_ok=True)
            trajectory_path.write_bytes(trajectory_value)
        else:
            _write_json(trajectory_path, trajectory_value)
    else:
        _write_json(root / "output" / "trajectory.json", [{"host_path": "/secret"}])
        _write_json(
            root / "failure_evidence.json",
            {
                "schema_version": "scenarioforge.failure-evidence/v1",
                "run_id": RUN_ID,
                "attempt_id": ATTEMPT_ID,
                "failure_kind": "timeout" if status == "timeout" else "worker_crashed",
                "failure_stage": "worker_execution",
                "reason": "timeout" if status == "timeout" else "worker_crashed",
                "worker_exit_code": -15 if status == "timeout" else 17,
                "termination": {
                    "schema_version": "scenarioforge.process-tree-termination/v1",
                    "trigger": "timeout" if status == "timeout" else "worker_crashed",
                    "process_group_id": 4321,
                    "observed_pids": [4321, 4322],
                    "signals_sent": ["SIGTERM"],
                    "remaining_pids": [],
                    "complete": True,
                },
                "logs": {
                    "stdout": "must not leave the projection",
                    "stderr": "token=must-not-leak /private/path",
                    "truncated": False,
                },
                "frozen_evidence": {},
                "partial_artifacts": [],
                "missing_artifacts": [],
            },
        )

    entries: list[dict[str, Any]] = []
    paths = ["input/run_manifest.json", "output/trajectory.json"]
    if status == "success":
        paths.extend(("output/events.json", "output/metrics.json"))
    else:
        paths.append("failure_evidence.json")
    for relative in sorted(paths):
        path = root / relative
        validation = "verified"
        if relative == "output/trajectory.json" and status != "success":
            validation = trajectory_validation or "verified_partial"
        entries.append(
            {
                "path": relative,
                "status": "present",
                "size_bytes": path.stat().st_size,
                "digest": _digest(path),
                "validation": validation,
            }
        )
    index = {
        "schema_version": "scenarioforge.artifact-index/v1",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "artifacts": entries,
    }
    result = {
        "schema_version": "scenarioforge.run-result/v1",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "status": status,
        "reason": (
            "horizon_completed"
            if status == "success"
            else "timeout"
            if status == "timeout"
            else "worker_crashed"
        ),
        "worker_exit_code": 0 if status == "success" else -15 if status == "timeout" else 17,
        "run_manifest_digest": canonical_digest(manifest),
        "compile_report_digest": "2" * 64,
        "execution_plan_digest": "3" * 64,
        "artifact_index_digest": canonical_digest(index),
    }
    _write_json(root / "artifact_index.json", index)
    _write_json(root / "run_result.json", result)
    marker = {
        "schema_version": "scenarioforge.completion-marker/v1",
        "status": status,
        "run_result_digest": _digest(root / "run_result.json"),
        "artifact_index_digest": _digest(root / "artifact_index.json"),
    }
    if status != "success":
        marker["failure_evidence_digest"] = _digest(root / "failure_evidence.json")
    _write_json(root / status.upper(), marker)
    return root


def _reader(workspace: Path) -> PublishedEvidenceReader:
    return PublishedEvidenceReader(publish_root=workspace / "published")


def test_success_terminal_projection_is_complete_exact_and_allow_listed(
    tmp_path: Path,
) -> None:
    root = _publish(tmp_path)

    projection = _reader(tmp_path).terminal(RUN_ID, ATTEMPT_ID)
    evidence = [
        {
            "ref": f"published/{RUN_ID}/{ATTEMPT_ID}/{relative}",
            "status": "present",
            "size_bytes": (root / relative).stat().st_size,
            "digest": _digest(root / relative),
            "validation": "verified",
        }
        for relative in (
            "input/run_manifest.json",
            "output/events.json",
            "output/metrics.json",
            "output/trajectory.json",
        )
    ]

    assert projection == {
        "schema_version": "scenarioforge.terminal-evidence/v1",
        "scenario_id": "brake_lead",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "state": "success",
        "terminal": True,
        "status": "success",
        "reason": "horizon_completed",
        "failure_stage": None,
        "playable": True,
        "playback_reason": None,
        "seed": 7,
        "policy": {"id": "scenarioforge.constant-lane", "version": "1.0.0"},
        "digests": {
            "run_manifest": _digest(root / "input" / "run_manifest.json"),
            "artifact_index": _digest(root / "artifact_index.json"),
        },
        "logical_ref": f"published/{RUN_ID}/{ATTEMPT_ID}",
        "evidence": evidence,
        "metrics": {
            "collision": False,
            "collision_participants": [],
            "min_ttc_s": 1.25,
            "completion_time_s": 0.2,
            "terminal_tick": 2,
        },
        "participants": [
            {"id": "ego", "role": "ego"},
            {"id": "lead", "role": "social"},
        ],
        "events": [
            {
                "event_id": "lead-brake",
                "type": "trigger_fired",
                "participant_id": "lead",
                "trigger_tick": 1,
                "effect_state_tick": 2,
            }
        ],
    }
    assert projection["digests"] == {
        "run_manifest": canonical_digest(_manifest("success")),
        "artifact_index": _digest(root / "artifact_index.json"),
    }
    assert [entry["ref"] for entry in projection["evidence"]] == [
        f"published/{RUN_ID}/{ATTEMPT_ID}/input/run_manifest.json",
        f"published/{RUN_ID}/{ATTEMPT_ID}/output/events.json",
        f"published/{RUN_ID}/{ATTEMPT_ID}/output/metrics.json",
        f"published/{RUN_ID}/{ATTEMPT_ID}/output/trajectory.json",
    ]
    public = repr(projection)
    assert "/private" not in public
    assert "output_staging" not in public
    assert "host_secret" not in public
    assert "config_digest" not in public


def test_success_playback_returns_only_validated_replay_fields(tmp_path: Path) -> None:
    root = _publish(tmp_path)

    playback = _reader(tmp_path).playback(RUN_ID, ATTEMPT_ID)

    assert playback == {
        "schema_version": "scenarioforge.playback/v1",
        "scenario_id": "brake_lead",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "logical_ref": f"published/{RUN_ID}/{ATTEMPT_ID}/output/trajectory.json",
        "trajectory_digest": _digest(root / "output" / "trajectory.json"),
        "road": {
            "template": "straight",
            "lane_count": 2,
            "lane_width_m": 3.5,
            "length_m": 120.0,
        },
        "participants": [
            {"id": "ego", "role": "ego"},
            {"id": "lead", "role": "social"},
        ],
        "sample_interval_s": 0.1,
        "terminal_tick": 2,
        "events": [
            {
                "event_id": "lead-brake",
                "type": "trigger_fired",
                "participant_id": "lead",
                "trigger_tick": 1,
                "effect_state_tick": 2,
            }
        ],
        "trajectory": _trajectory(),
    }


@pytest.mark.parametrize("status", ("failed", "timeout"))
def test_failure_and_timeout_are_structured_and_never_return_partial_trajectory(
    tmp_path: Path,
    status: str,
) -> None:
    root = _publish(tmp_path, status=status)
    reader = _reader(tmp_path)

    terminal = reader.terminal(RUN_ID, ATTEMPT_ID)
    reason = "timeout" if status == "timeout" else "worker_crashed"
    evidence = [
        {
            "ref": f"published/{RUN_ID}/{ATTEMPT_ID}/{relative}",
            "status": "present",
            "size_bytes": (root / relative).stat().st_size,
            "digest": _digest(root / relative),
            "validation": (
                "verified_partial"
                if relative == "output/trajectory.json"
                else "verified"
            ),
        }
        for relative in (
            "failure_evidence.json",
            "input/run_manifest.json",
            "output/trajectory.json",
        )
    ]

    assert terminal == {
        "schema_version": "scenarioforge.terminal-evidence/v1",
        "scenario_id": "brake_lead",
        "run_id": RUN_ID,
        "attempt_id": ATTEMPT_ID,
        "state": status,
        "terminal": True,
        "status": status,
        "reason": reason,
        "failure_stage": "worker_execution",
        "playable": False,
        "playback_reason": "terminal_not_success",
        "seed": 7,
        "policy": {"id": "scenarioforge.constant-lane", "version": "1.0.0"},
        "digests": {
            "run_manifest": _digest(root / "input" / "run_manifest.json"),
            "artifact_index": _digest(root / "artifact_index.json"),
        },
        "logical_ref": f"published/{RUN_ID}/{ATTEMPT_ID}",
        "evidence": evidence,
        "metrics": {
            "collision": None,
            "collision_participants": [],
            "min_ttc_s": None,
            "completion_time_s": None,
            "terminal_tick": None,
        },
        "participants": [
            {"id": "ego", "role": "ego"},
            {"id": "lead", "role": "social"},
        ],
        "events": [],
    }
    assert "logs" not in repr(terminal)
    assert "must-not-leak" not in repr(terminal)
    assert "/private/path" not in repr(terminal)

    with pytest.raises(NonPlayableRunError, match="not playable"):
        reader.playback(RUN_ID, ATTEMPT_ID)


@pytest.mark.parametrize(
    ("run_id", "attempt_id"),
    (
        ("../escape", ATTEMPT_ID),
        ("/absolute", ATTEMPT_ID),
        (RUN_ID, "../../escape"),
        (RUN_ID, "attempt/child"),
    ),
)
def test_malformed_run_identifiers_fail_before_filesystem_resolution(
    tmp_path: Path,
    run_id: str,
    attempt_id: str,
) -> None:
    with pytest.raises(InvalidEvidenceIdentifierError, match="invalid") as raised:
        _reader(tmp_path).terminal(run_id, attempt_id)
    assert str(tmp_path) not in str(raised.value)


def test_unknown_run_and_symlink_containment_fail_without_host_path_disclosure(
    tmp_path: Path,
) -> None:
    reader = _reader(tmp_path)
    with pytest.raises(UnknownPublishedRunError, match="unknown published run") as raised:
        reader.terminal(RUN_ID, ATTEMPT_ID)
    assert str(tmp_path) not in str(raised.value)

    outside = tmp_path / "outside"
    outside.mkdir()
    run_parent = tmp_path / "published" / RUN_ID
    run_parent.parent.mkdir()
    run_parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(EvidenceValidationError, match="containment") as contained:
        reader.terminal(RUN_ID, ATTEMPT_ID)
    assert str(outside) not in str(contained.value)


@pytest.mark.parametrize("control_file", ("SUCCESS", "artifact_index.json"))
def test_missing_completion_or_index_fails_closed(tmp_path: Path, control_file: str) -> None:
    root = _publish(tmp_path)
    (root / control_file).unlink()

    with pytest.raises(EvidenceValidationError):
        _reader(tmp_path).terminal(RUN_ID, ATTEMPT_ID)


@pytest.mark.parametrize("tampered_file", ("artifact_index.json", "run_result.json"))
def test_control_digest_tampering_is_rejected(tmp_path: Path, tampered_file: str) -> None:
    root = _publish(tmp_path)
    (root / tampered_file).write_bytes((root / tampered_file).read_bytes() + b" ")

    with pytest.raises(EvidenceValidationError, match="digest|canonical"):
        _reader(tmp_path).terminal(RUN_ID, ATTEMPT_ID)


@pytest.mark.parametrize(
    "trajectory",
    (
        [{"tick": 0}],
        canonical_bytes(_trajectory()).replace(b'"speed_mps":8.0', b'"speed_mps":1e999'),
        [
            _trajectory()[0],
            {**_trajectory()[1], "participant_id": "intruder"},
        ],
        [
            *_trajectory()[2:4],
            *_trajectory()[0:2],
        ],
    ),
)
def test_trajectory_schema_finite_participants_and_tick_order_are_enforced(
    tmp_path: Path,
    trajectory: Any,
) -> None:
    _publish(tmp_path, trajectory=trajectory)

    with pytest.raises(EvidenceValidationError, match="trajectory"):
        _reader(tmp_path).playback(RUN_ID, ATTEMPT_ID)


def test_indexed_trajectory_size_and_digest_are_checked_before_json_use(
    tmp_path: Path,
) -> None:
    root = _publish(tmp_path)
    trajectory_path = root / "output" / "trajectory.json"
    trajectory_path.write_bytes(b'[{"host_path":"/should-not-be-read-as-playback"}]')

    with pytest.raises(EvidenceValidationError, match="size|digest"):
        _reader(tmp_path).playback(RUN_ID, ATTEMPT_ID)
