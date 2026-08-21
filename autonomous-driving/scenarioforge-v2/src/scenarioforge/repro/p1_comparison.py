from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scenarioforge.core import strict_loads
from scenarioforge.core.canonical import CanonicalModel


_PROFILE_FIELDS = {
    "schema_version",
    "profile_id",
    "run_count",
    "position_abs_m",
    "speed_abs_mps",
    "heading_abs_deg",
    "min_ttc_abs_s",
    "completed_steps",
    "metadrive_profile_ref",
}
_RUN_FIELDS = {
    "schema_version",
    "scenario_id",
    "run_id",
    "execution_snapshot_digest",
    "backend",
    "scenario_digest",
    "policy_digest",
    "seed",
    "parameters_digest",
    "fixed_timestep_s",
    "participants",
    "events",
    "terminal_state",
    "metrics",
    "trajectory",
    "road_geometry",
}
_SCOPE_FIELDS = (
    "scenario_id",
    "execution_snapshot_digest",
    "backend",
    "scenario_digest",
    "policy_digest",
    "seed",
    "parameters_digest",
    "fixed_timestep_s",
    "participants",
    "road_geometry",
)


class P1ComparisonError(ValueError):
    pass


def _finite_nonnegative(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise P1ComparisonError(f"{label} must be finite and non-negative")
    return result


@dataclass(frozen=True)
class SmartsToleranceProfile(CanonicalModel):
    schema_version: str
    profile_id: str
    run_count: int
    position_abs_m: float
    speed_abs_mps: float
    heading_abs_deg: float
    min_ttc_abs_s: float
    completed_steps: int
    metadrive_profile_ref: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SmartsToleranceProfile":
        if set(value) != _PROFILE_FIELDS:
            raise P1ComparisonError("SMARTS tolerance profile fields are incomplete or unknown")
        if value["schema_version"] != "scenarioforge.smarts-tolerance-profile/v1":
            raise P1ComparisonError("SMARTS tolerance profile schema is unsupported")
        if value["run_count"] != 3:
            raise P1ComparisonError("SMARTS reproducibility requires exactly three runs")
        completed_steps = value["completed_steps"]
        if (
            isinstance(completed_steps, bool)
            or not isinstance(completed_steps, int)
            or completed_steps < 0
        ):
            raise P1ComparisonError("completed_steps tolerance is invalid")
        profile_id = value["profile_id"]
        metadrive_ref = value["metadrive_profile_ref"]
        if not isinstance(profile_id, str) or not profile_id:
            raise P1ComparisonError("SMARTS tolerance profile id is invalid")
        if not isinstance(metadrive_ref, str) or not metadrive_ref:
            raise P1ComparisonError("MetaDrive tolerance profile ref is invalid")
        return cls(
            schema_version=str(value["schema_version"]),
            profile_id=profile_id,
            run_count=3,
            position_abs_m=_finite_nonnegative(value["position_abs_m"], "position tolerance"),
            speed_abs_mps=_finite_nonnegative(value["speed_abs_mps"], "speed tolerance"),
            heading_abs_deg=_finite_nonnegative(value["heading_abs_deg"], "heading tolerance"),
            min_ttc_abs_s=_finite_nonnegative(value["min_ttc_abs_s"], "min-TTC tolerance"),
            completed_steps=completed_steps,
            metadrive_profile_ref=metadrive_ref,
        )


def load_smarts_tolerance_profile(path: Path) -> SmartsToleranceProfile:
    value = strict_loads(path.read_bytes())
    if not isinstance(value, Mapping):
        raise P1ComparisonError("SMARTS tolerance profile must be an object")
    return SmartsToleranceProfile.from_dict(value)


def _trajectory_index(
    trajectory: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, int], Mapping[str, Any]]:
    result: dict[tuple[str, int], Mapping[str, Any]] = {}
    for sample in trajectory:
        if not isinstance(sample, Mapping):
            raise P1ComparisonError("trajectory sample must be an object")
        agent_id = sample.get("agent_id")
        tick = sample.get("tick")
        if not isinstance(agent_id, str) or not agent_id:
            raise P1ComparisonError("trajectory agent_id is invalid")
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
            raise P1ComparisonError("trajectory tick is invalid")
        key = (agent_id, tick)
        if key in result:
            raise P1ComparisonError(f"duplicate trajectory sample: {key}")
        position = sample.get("position_m")
        if not isinstance(position, (list, tuple)) or len(position) != 3:
            raise P1ComparisonError("trajectory position_m is invalid")
        for field in ("speed_mps", "heading_deg"):
            if field not in sample:
                raise P1ComparisonError(f"trajectory {field} is missing")
        result[key] = sample
    if not result:
        raise P1ComparisonError("trajectory must not be empty")
    return result


def _heading_delta(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _round(value: float) -> float:
    return round(value, 12)


def _validate_runs(runs: Sequence[Mapping[str, Any]]) -> None:
    if len(runs) != 3:
        raise P1ComparisonError("SMARTS comparison requires exactly three runs")
    for run in runs:
        if not isinstance(run, Mapping) or set(run) != _RUN_FIELDS:
            raise P1ComparisonError("SMARTS run evidence fields are incomplete or unknown")
        if run["schema_version"] != "scenarioforge.smarts-run-evidence/v1":
            raise P1ComparisonError("SMARTS run evidence schema is unsupported")
    run_ids = [run["run_id"] for run in runs]
    if any(not isinstance(run_id, str) or not run_id for run_id in run_ids):
        raise P1ComparisonError("SMARTS run id is invalid")
    if len(set(run_ids)) != 3:
        raise P1ComparisonError("SMARTS comparison requires independent run IDs")
    baseline = {field: runs[0][field] for field in _SCOPE_FIELDS}
    if any(
        {field: run[field] for field in _SCOPE_FIELDS} != baseline for run in runs[1:]
    ):
        raise P1ComparisonError("runs do not share one locked comparison scope")


def compare_three_smarts_runs(
    runs: Sequence[Mapping[str, Any]],
    profile: SmartsToleranceProfile,
) -> dict[str, Any]:
    _validate_runs(runs)
    if profile.run_count != 3:
        raise P1ComparisonError("profile does not require exactly three runs")

    events_match = all(run["events"] == runs[0]["events"] for run in runs[1:])
    terminal_state_match = all(
        run["terminal_state"] == runs[0]["terminal_state"] for run in runs[1:]
    )
    discrete_passed = events_match and terminal_state_match

    indexed = [_trajectory_index(run["trajectory"]) for run in runs]
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
                    "missing": [[agent_id, tick] for agent_id, tick in missing],
                    "unexpected": [[agent_id, tick] for agent_id, tick in unexpected],
                }
            )

    maximums = {
        "position_abs_m": 0.0,
        "speed_abs_mps": 0.0,
        "heading_abs_deg": 0.0,
        "min_ttc_abs_s": 0.0,
        "completed_steps": 0,
    }
    common_keys = set.intersection(*(set(item) for item in indexed))
    for key in sorted(common_keys):
        for left_index in range(3):
            for right_index in range(left_index + 1, 3):
                left = indexed[left_index][key]
                right = indexed[right_index][key]
                left_position = [_finite_nonnegative(abs(value), "position") for value in left["position_m"]]
                right_position = [_finite_nonnegative(abs(value), "position") for value in right["position_m"]]
                position_delta = math.dist(left_position, right_position)
                maximums["position_abs_m"] = max(
                    float(maximums["position_abs_m"]), position_delta
                )
                maximums["speed_abs_mps"] = max(
                    float(maximums["speed_abs_mps"]),
                    abs(float(left["speed_mps"]) - float(right["speed_mps"])),
                )
                maximums["heading_abs_deg"] = max(
                    float(maximums["heading_abs_deg"]),
                    _heading_delta(
                        float(left["heading_deg"]), float(right["heading_deg"])
                    ),
                )

    ttc_values = [run["metrics"].get("min_ttc_s") for run in runs]
    if all(value is None for value in ttc_values):
        pass
    elif any(value is None for value in ttc_values):
        violations.append({"field": "min_ttc_abs_s", "reason": "null_mismatch"})
    else:
        numeric_ttc = [float(value) for value in ttc_values]
        maximums["min_ttc_abs_s"] = max(numeric_ttc) - min(numeric_ttc)
    completed = [int(run["metrics"]["completed_steps"]) for run in runs]
    maximums["completed_steps"] = max(completed) - min(completed)
    maximums = {
        field: value if field == "completed_steps" else _round(float(value))
        for field, value in maximums.items()
    }

    limits: dict[str, float | int] = {
        "position_abs_m": profile.position_abs_m,
        "speed_abs_mps": profile.speed_abs_mps,
        "heading_abs_deg": profile.heading_abs_deg,
        "min_ttc_abs_s": profile.min_ttc_abs_s,
        "completed_steps": profile.completed_steps,
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

    continuous_passed = not violations
    return {
        "schema_version": "scenarioforge.smarts-reproducibility-report/v1",
        "profile_id": profile.profile_id,
        "run_ids": [str(run["run_id"]) for run in runs],
        "discrete": {
            "events_match": events_match,
            "terminal_state_match": terminal_state_match,
            "passed": discrete_passed,
        },
        "continuous": {
            "aligned_agent_ids": sorted({agent_id for agent_id, _ in baseline_keys}),
            "aligned_ticks": sorted({tick for _, tick in baseline_keys}),
            "max_deltas": maximums,
            "violations": violations,
            "passed": continuous_passed,
        },
        "passed": discrete_passed and continuous_passed,
    }


__all__ = [
    "P1ComparisonError",
    "SmartsToleranceProfile",
    "compare_three_smarts_runs",
    "load_smarts_tolerance_profile",
]
