from __future__ import annotations

import hashlib
import math
import os
import re
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

from scenarioforge.core import canonical_bytes, canonical_digest, strict_loads
from scenarioforge.core.canonical import freeze_json
from scenarioforge.runtime.contracts import RunOutcome

from .contracts import (
    ComparisonReport,
    ContinuousComparison,
    ImmutableRunReference,
    ToleranceProfile,
    ensure_destination_parent,
    freeze_mapping,
)


_SAFE_COMPARISON_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _rounded(value: float) -> float:
    return round(value, 12)


def _circular_heading_delta(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def _trajectory_index(
    points: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, int], Mapping[str, Any]]:
    indexed: dict[tuple[str, int], Mapping[str, Any]] = {}
    for point in points:
        key = (str(point["participant_id"]), int(point["tick"]))
        if key in indexed:
            raise ValueError(f"duplicate trajectory point: {key}")
        indexed[key] = point
    return indexed


def compare_trajectory_series(
    trajectories: Sequence[Sequence[Mapping[str, Any]]],
    metrics: Sequence[Mapping[str, Any]],
    tolerances: ToleranceProfile,
) -> ContinuousComparison:
    if len(trajectories) != 3 or len(metrics) != 3:
        raise ValueError("the P0-A comparison contract requires exactly three runs")
    indexed = [_trajectory_index(points) for points in trajectories]
    baseline_keys = set(indexed[0])
    violations: list[dict[str, Any]] = []
    for run_index, current in enumerate(indexed[1:], start=2):
        missing = sorted(baseline_keys - set(current))
        unexpected = sorted(set(current) - baseline_keys)
        if missing or unexpected:
            violations.append(
                {
                    "field": "trajectory_alignment",
                    "run_index": run_index,
                    "missing": [[participant, tick] for participant, tick in missing],
                    "unexpected": [[participant, tick] for participant, tick in unexpected],
                }
            )

    position_delta = 0.0
    speed_delta = 0.0
    heading_delta = 0.0
    common_keys = set.intersection(*(set(item) for item in indexed))
    for key in sorted(common_keys):
        for left_index, right_index in combinations(range(3), 2):
            left = indexed[left_index][key]
            right = indexed[right_index][key]
            left_position = left["position_m"]
            right_position = right["position_m"]
            position_delta = max(
                position_delta,
                math.dist(
                    [float(left_position[0]), float(left_position[1])],
                    [float(right_position[0]), float(right_position[1])],
                ),
            )
            speed_delta = max(
                speed_delta,
                abs(float(left["speed_mps"]) - float(right["speed_mps"])),
            )
            heading_delta = max(
                heading_delta,
                _circular_heading_delta(
                    float(left["heading_deg"]),
                    float(right["heading_deg"]),
                ),
            )

    ttc_values = [item["min_ttc_s"] for item in metrics]
    if all(value is None for value in ttc_values):
        null_ttc_semantics = "all_null_equal"
        ttc_delta = 0.0
    elif any(value is None for value in ttc_values):
        null_ttc_semantics = "mixed_null_mismatch"
        ttc_delta = 0.0
        violations.append({"field": "min_ttc_s", "reason": "null_mismatch"})
    else:
        null_ttc_semantics = "all_numeric"
        numeric_ttc = [float(value) for value in ttc_values]
        ttc_delta = max(numeric_ttc) - min(numeric_ttc)

    completed_steps = [int(item["completed_steps"]) for item in metrics]
    completed_steps_delta = max(completed_steps) - min(completed_steps)
    maximums: dict[str, float | int] = {
        "position_m": _rounded(position_delta),
        "speed_mps": _rounded(speed_delta),
        "heading_deg": _rounded(heading_delta),
        "min_ttc_s": _rounded(ttc_delta),
        "completed_steps": completed_steps_delta,
    }
    limits: dict[str, float | int] = {
        "position_m": tolerances.position_m,
        "speed_mps": tolerances.speed_mps,
        "heading_deg": tolerances.heading_deg,
        "min_ttc_s": tolerances.min_ttc_s,
        "completed_steps": tolerances.completed_steps,
    }
    for field, maximum in maximums.items():
        if float(maximum) > float(limits[field]) + 1e-12:
            violations.append(
                {
                    "field": field,
                    "maximum_delta": maximum,
                    "tolerance": limits[field],
                }
            )

    participant_ids = tuple(sorted({participant for participant, _ in baseline_keys}))
    ticks = tuple(sorted({tick for _, tick in baseline_keys}))
    frozen_maximums = freeze_json(maximums)
    frozen_violations = freeze_json(violations)
    assert isinstance(frozen_maximums, Mapping)
    assert isinstance(frozen_violations, tuple)
    return ContinuousComparison(
        schema_version="scenarioforge.continuous-comparison/v1",
        aligned_participant_ids=participant_ids,
        aligned_ticks=ticks,
        max_deltas=frozen_maximums,
        null_ttc_semantics=null_ttc_semantics,
        violations=frozen_violations,
        passed=not violations,
    )


def _read_json(path: Path) -> dict[str, Any] | list[Any]:
    value = strict_loads(path.read_bytes())
    if not isinstance(value, (dict, list)):
        raise ValueError(f"comparison artifact is not structured JSON: {path.name}")
    return value


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _event_signature(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event["event_id"],
            "type": event["type"],
            "participant_id": event["participant_id"],
            "trigger_tick": event["trigger_tick"],
            "effect_state_tick": event["effect_state_tick"],
        }
        for event in events
    ]


def compare_runs(
    comparison_id: str,
    outcomes: Sequence[RunOutcome],
    tolerances: ToleranceProfile | None = None,
) -> ComparisonReport:
    if not _SAFE_COMPARISON_ID.fullmatch(comparison_id):
        raise ValueError("invalid comparison_id")
    if len(outcomes) != 3:
        raise ValueError("the P0-A comparison contract requires exactly three runs")
    run_ids = [outcome.run_result.run_id for outcome in outcomes]
    if len(set(run_ids)) != 3:
        raise ValueError("comparison runs must use three independent run IDs")
    if any(outcome.run_result.status != "success" for outcome in outcomes):
        raise ValueError("three-run reproducibility comparison requires published runs")
    plan = outcomes[0].bundle.execution_plan
    if plan is None:
        raise ValueError("comparison requires an executable plan")
    scenario_digest = outcomes[0].bundle.scenario_instance.digest
    plan_digest = plan.digest
    for outcome in outcomes[1:]:
        if outcome.bundle.scenario_instance.digest != scenario_digest:
            raise ValueError("comparison runs do not share one ScenarioInstance")
        if outcome.bundle.execution_plan is None or outcome.bundle.execution_plan.digest != plan_digest:
            raise ValueError("comparison runs do not share one ExecutionPlan")

    run_references: list[ImmutableRunReference] = []
    action_sequences: list[list[Any]] = []
    event_sequences: list[list[Any]] = []
    metric_records: list[dict[str, Any]] = []
    trajectories: list[list[Any]] = []
    for outcome in outcomes:
        output = outcome.published_path / "output"
        actions = _read_json(output / "actions.json")
        events = _read_json(output / "events.json")
        metrics = _read_json(output / "metrics.json")
        trajectory = _read_json(output / "trajectory.json")
        if not isinstance(actions, list) or not isinstance(events, list):
            raise ValueError("action and event artifacts must be lists")
        if not isinstance(metrics, dict) or not isinstance(trajectory, list):
            raise ValueError("metrics or trajectory artifact has an invalid shape")
        action_sequences.append(actions)
        event_sequences.append(events)
        metric_records.append(metrics)
        trajectories.append(trajectory)
        run_references.append(
            ImmutableRunReference(
                schema_version="scenarioforge.immutable-run-reference/v1",
                run_id=outcome.run_result.run_id,
                scenario_instance_digest=scenario_digest,
                execution_plan_digest=plan_digest,
                run_result_digest=_file_digest(outcome.published_path / "run_result.json"),
                artifact_index_digest=_file_digest(
                    outcome.published_path / "artifact_index.json"
                ),
            )
        )

    action_digests = [canonical_digest(item) for item in action_sequences]
    event_signatures = [_event_signature(item) for item in event_sequences]
    terminal_statuses = [str(item["terminal_status"]) for item in metric_records]
    termination_reasons = [str(item["termination_reason"]) for item in metric_records]
    collisions = [bool(item["collision"]) for item in metric_records]
    collision_participants = [item["collision_participants"] for item in metric_records]
    mismatches: list[str] = []
    if len(set(terminal_statuses)) != 1:
        mismatches.append("terminal_status")
    if len(set(termination_reasons)) != 1:
        mismatches.append("termination_reason")
    if len(set(collisions)) != 1:
        mismatches.append("collision")
    if any(item != collision_participants[0] for item in collision_participants[1:]):
        mismatches.append("collision_participants")
    if any(item != event_signatures[0] for item in event_signatures[1:]):
        mismatches.append("key_events")
    if len(set(action_digests)) != 1:
        mismatches.append("action_sequence")

    profile = ToleranceProfile.p0a() if tolerances is None else tolerances
    continuous = compare_trajectory_series(trajectories, metric_records, profile)
    discrete = freeze_mapping(
        {
            "schema_version": "scenarioforge.discrete-comparison/v1",
            "terminal_status": terminal_statuses[0],
            "termination_reason": termination_reasons[0],
            "collision": collisions[0],
            "collision_participants": collision_participants[0],
            "key_events": event_signatures[0],
            "action_sequence_digest": action_digests[0],
            "mismatches": mismatches,
            "passed": not mismatches,
        }
    )
    policy_reexecution = freeze_mapping(
        {
            "action_generation": "worker_policy_per_tick",
            "historical_actions_used": False,
            "action_sequence_digests": action_digests,
            "matched": len(set(action_digests)) == 1,
        }
    )
    comparison_scope = freeze_mapping(
        {
            "run_count": 3,
            "scenario_instance_digest": scenario_digest,
            "seed": outcomes[0].bundle.scenario_instance.seed,
            "execution_plan_digest": plan_digest,
            "policy": {
                "id": outcomes[0].bundle.scenario_instance.policy["id"],
                "version": outcomes[0].bundle.scenario_instance.policy["version"],
            },
            "tolerances_version": plan.tolerances_version,
        }
    )
    passed = bool(discrete["passed"] and continuous.passed and policy_reexecution["matched"])
    return ComparisonReport(
        schema_version="scenarioforge.repro-comparison/v1",
        comparison_id=comparison_id,
        run_references=tuple(run_references),
        comparison_scope=comparison_scope,
        excluded_nonsemantic_fields=(
            "artifact_path",
            "attempt_id",
            "run_id",
            "wall_clock_timestamp",
        ),
        policy_reexecution=policy_reexecution,
        discrete=discrete,
        continuous=continuous,
        tolerances=profile,
        passed=passed,
    )


def publish_comparison_report(report: ComparisonReport, destination: Path) -> None:
    destination = Path(destination)
    ensure_destination_parent(destination)
    descriptor = os.open(
        destination,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o400,
    )
    try:
        payload = canonical_bytes(report.to_dict())
        if os.write(descriptor, payload) != len(payload):
            raise OSError("short comparison report write")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    destination.chmod(0o444)
