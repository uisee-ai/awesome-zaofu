"""Strict, versioned ScenarioSpec input and identity boundary."""

from .models import (
    ActorSpec,
    CanonicalScenario,
    EnvironmentSpec,
    EventTriggerSpec,
    GoalSpec,
    InitialStateSpec,
    MapSpec,
    ResourceLimits,
    RunRequest,
    ScenarioSpec,
    SafetyConstraints,
    StaticObstacleSpec,
)
from .serde import ScenarioInputError, canonical_scenario, export_scenario, load_scenario

__all__ = [
    "ActorSpec",
    "CanonicalScenario",
    "EnvironmentSpec",
    "EventTriggerSpec",
    "GoalSpec",
    "InitialStateSpec",
    "MapSpec",
    "ResourceLimits",
    "RunRequest",
    "ScenarioInputError",
    "ScenarioSpec",
    "SafetyConstraints",
    "StaticObstacleSpec",
    "canonical_scenario",
    "export_scenario",
    "load_scenario",
]
