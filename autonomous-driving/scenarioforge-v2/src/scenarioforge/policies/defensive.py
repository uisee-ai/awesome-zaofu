from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from scenarioforge.core.canonical import CanonicalModel


DEFENSIVE_CONSTANTS: Mapping[str, float] = MappingProxyType(
    {
        "nominal_target_speed_scale": 1.0,
        "desired_time_headway_s": 2.0,
        "minimum_gap_m": 5.0,
        "ttc_brake_threshold_s": 3.0,
        "maximum_brake_command": 1.0,
        "release_hysteresis_s": 0.5,
    }
)


@dataclass(frozen=True)
class DefensiveObservation:
    elapsed_s: float
    ego_speed_mps: float
    lead_gap_m: float | None
    lead_speed_mps: float | None
    merge_yield_required: bool

    def __post_init__(self) -> None:
        numeric = [self.elapsed_s, self.ego_speed_mps]
        if self.lead_gap_m is not None:
            numeric.append(self.lead_gap_m)
        if self.lead_speed_mps is not None:
            numeric.append(self.lead_speed_mps)
        if any(not math.isfinite(float(value)) for value in numeric):
            raise ValueError("defensive observation values must be finite")
        if self.elapsed_s < 0.0 or self.ego_speed_mps < 0.0:
            raise ValueError("elapsed time and ego speed must be non-negative")
        if self.lead_gap_m is not None and self.lead_gap_m < 0.0:
            raise ValueError("lead gap must be non-negative")
        if (self.lead_gap_m is None) != (self.lead_speed_mps is None):
            raise ValueError("lead gap and speed must be provided together")


@dataclass(frozen=True)
class DefensiveControlState:
    braking: bool
    safe_since_s: float | None
    brake_command: float

    @classmethod
    def initial(cls) -> "DefensiveControlState":
        return cls(braking=False, safe_since_s=None, brake_command=0.0)


@dataclass(frozen=True)
class DefensiveDecision(CanonicalModel):
    schema_version: str
    nominal_target_speed_scale: float
    steering_override: None
    throttle_brake: float
    reason: str


def _hazard_assessment(observation: DefensiveObservation) -> tuple[str | None, float]:
    if observation.merge_yield_required:
        return "merge_yield", 0.25
    if observation.lead_gap_m is None or observation.lead_speed_mps is None:
        return None, 0.0

    gap = observation.lead_gap_m
    minimum_gap = DEFENSIVE_CONSTANTS["minimum_gap_m"]
    desired_gap = max(
        minimum_gap,
        observation.ego_speed_mps * DEFENSIVE_CONSTANTS["desired_time_headway_s"],
    )
    closing_speed = max(0.0, observation.ego_speed_mps - observation.lead_speed_mps)
    ttc = math.inf if closing_speed <= 1e-12 else gap / closing_speed
    gap_risk = max(0.0, (desired_gap - gap) / max(desired_gap, 1e-12))
    ttc_risk = max(
        0.0,
        (DEFENSIVE_CONSTANTS["ttc_brake_threshold_s"] - ttc)
        / DEFENSIVE_CONSTANTS["ttc_brake_threshold_s"],
    )
    severity = max(0.1, gap_risk, ttc_risk)
    if gap <= minimum_gap:
        return "minimum_gap", severity
    if gap < desired_gap and ttc <= DEFENSIVE_CONSTANTS["ttc_brake_threshold_s"]:
        return "time_headway_and_ttc", severity
    if ttc <= DEFENSIVE_CONSTANTS["ttc_brake_threshold_s"]:
        return "ttc", severity
    if gap < desired_gap:
        return "time_headway", severity
    return None, 0.0


def _decision(throttle_brake: float, reason: str) -> DefensiveDecision:
    return DefensiveDecision(
        schema_version="scenarioforge.defensive-decision/v1",
        nominal_target_speed_scale=DEFENSIVE_CONSTANTS[
            "nominal_target_speed_scale"
        ],
        steering_override=None,
        throttle_brake=throttle_brake,
        reason=reason,
    )


def decide_defensive_control(
    observation: DefensiveObservation,
    state: DefensiveControlState,
) -> tuple[DefensiveDecision, DefensiveControlState]:
    """Return a longitudinal-only defensive decision with fixed hysteresis."""
    reason, severity = _hazard_assessment(observation)
    if reason is not None:
        brake = -min(
            DEFENSIVE_CONSTANTS["maximum_brake_command"],
            max(0.1, severity),
        )
        return _decision(brake, reason), DefensiveControlState(
            braking=True,
            safe_since_s=None,
            brake_command=brake,
        )

    if state.braking:
        safe_since = (
            observation.elapsed_s
            if state.safe_since_s is None
            else state.safe_since_s
        )
        if (
            observation.elapsed_s - safe_since
            < DEFENSIVE_CONSTANTS["release_hysteresis_s"]
        ):
            return _decision(
                state.brake_command,
                "release_hysteresis",
            ), DefensiveControlState(
                braking=True,
                safe_since_s=safe_since,
                brake_command=state.brake_command,
            )

    return _decision(0.0, "nominal"), DefensiveControlState.initial()


def planned_defensive_throttle_brake(
    plan: Mapping[str, Any],
    tick: int,
    participant_id: str,
    baseline_throttle_brake: float,
) -> float:
    """Project fixed evidence-bound hazards into a conservative pre-event brake.

    Live state control uses :func:`decide_defensive_control`. The immutable P0
    plans currently expose tick-bound hazards to the worker, so this adapter
    seam begins a small longitudinal yield within the fixed headway window and
    leaves all declared scenario overrides untouched.
    """
    participant = next(
        (
            item
            for item in plan["participants"]
            if str(item["id"]) == participant_id
        ),
        None,
    )
    if participant is None or participant.get("role") != "ego":
        return baseline_throttle_brake
    response_tick = planned_defensive_response_tick(plan)
    if response_tick is None or tick != response_tick:
        return baseline_throttle_brake
    gentle_yield = -min(
        DEFENSIVE_CONSTANTS["maximum_brake_command"],
        0.001,
    )
    return min(baseline_throttle_brake, gentle_yield)


def planned_defensive_response_tick(plan: Mapping[str, Any]) -> int | None:
    """Return the one-tick pre-response supported by immutable tick evidence."""
    sample_interval_s = float(plan["simulation"]["physics_world_step_size_s"]) * int(
        plan["simulation"]["decision_repeat"]
    )
    if not math.isfinite(sample_interval_s) or sample_interval_s <= 0.0:
        raise ValueError("defensive policy requires a positive finite sample interval")
    hazard_ticks = sorted(
        int(event["trigger"]["tick"])
        for event in plan["events"]
        if event.get("trigger", {}).get("kind") == "tick"
    )
    if not hazard_ticks:
        return None
    return max(0, hazard_ticks[0] - 1)
