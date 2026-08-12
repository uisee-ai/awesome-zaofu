from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MapSpec(_StrictModel):
    block_sequence: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z]+$")
    lane_count: int = Field(ge=2, le=3)
    lane_width: float = Field(ge=3.0, le=4.5, allow_inf_nan=False)


class ActorSpec(_StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    role: Literal["ego", "traffic"]
    initial_state: InitialStateSpec | None = None
    goal: GoalSpec | None = None
    behavior: Literal[
        "keep_lane", "follow_lead", "merge", "yield", "cross_intersection", "avoid_obstacle"
    ] = "keep_lane"

    @model_serializer(mode="wrap")
    def serialize_without_default_p0_fields(self, handler: object) -> object:
        data = handler(self)
        return {
            key: value
            for key, value in data.items()
            if not (
                (key in {"initial_state", "goal"} and value is None)
                or (key == "behavior" and value == "keep_lane")
            )
        }


class InitialStateSpec(_StrictModel):
    lane: int = Field(ge=0, le=2)
    longitudinal: float = Field(ge=0.0, le=10_000.0, allow_inf_nan=False)
    speed: float = Field(ge=0.0, le=40.0, allow_inf_nan=False)


class GoalSpec(_StrictModel):
    kind: Literal["route_progress", "lane", "stop"]
    minimum_progress: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)
    lane: int | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def require_kind_specific_target(self) -> GoalSpec:
        if self.kind == "route_progress" and self.minimum_progress is None:
            raise ValueError("route_progress goals require minimum_progress")
        if self.kind == "lane" and self.lane is None:
            raise ValueError("lane goals require lane")
        if self.kind == "stop" and (self.minimum_progress is not None or self.lane is not None):
            raise ValueError("stop goals do not accept a target")
        return self


class StaticObstacleSpec(_StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    kind: Literal["barrier", "cone", "stalled_vehicle"]
    lane: int = Field(ge=0, le=2)
    longitudinal: float = Field(ge=0.0, le=10_000.0, allow_inf_nan=False)
    length: float = Field(gt=0.0, le=20.0, allow_inf_nan=False)


class EventTriggerSpec(_StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    kind: Literal["at_time", "at_distance", "on_approach"]
    action: Literal["set_speed_limit", "spawn_traffic", "yield"]
    target_actor_id: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    seconds: float | None = Field(default=None, ge=0.0, le=600.0, allow_inf_nan=False)
    distance: float | None = Field(default=None, ge=0.0, le=10_000.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_kind_specific_condition(self) -> EventTriggerSpec:
        if self.kind == "at_time" and self.seconds is None:
            raise ValueError("at_time triggers require seconds")
        if self.kind in {"at_distance", "on_approach"} and self.distance is None:
            raise ValueError(f"{self.kind} triggers require distance")
        return self

    @model_serializer(mode="wrap")
    def serialize_without_unset_target(self, handler: object) -> object:
        data = handler(self)
        if data.get("target_actor_id") is None:
            data.pop("target_actor_id", None)
        return data


class SafetyConstraints(_StrictModel):
    max_speed: float = Field(gt=0.0, le=40.0, allow_inf_nan=False)
    minimum_headway: float = Field(gt=0.0, le=10.0, allow_inf_nan=False)
    collision_free: bool


class EnvironmentSpec(_StrictModel):
    traffic_density: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class ScenarioSpec(_StrictModel):
    schema_version: Literal["scenarioforge.scenario-spec.v1"]
    name: str = Field(min_length=1, max_length=128)
    map: MapSpec
    actors: tuple[ActorSpec, ...] = Field(min_length=1, max_length=8)
    environment: EnvironmentSpec
    tags: tuple[str, ...] = Field(default=(), max_length=16)
    static_obstacles: tuple[StaticObstacleSpec, ...] = Field(default=(), max_length=8)
    event_triggers: tuple[EventTriggerSpec, ...] = Field(default=(), max_length=8)
    safety: SafetyConstraints | None = None

    @field_validator("actors", "tags", "static_obstacles", "event_triggers", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("actors")
    @classmethod
    def require_one_ego_and_unique_ids(cls, actors: tuple[ActorSpec, ...]) -> tuple[ActorSpec, ...]:
        if sum(actor.role == "ego" for actor in actors) != 1:
            raise ValueError("actors must contain exactly one ego")
        ids = [actor.id for actor in actors]
        if len(ids) != len(set(ids)):
            raise ValueError("actor ids must be unique")
        return actors

    @model_validator(mode="after")
    def require_references_to_fit_the_map(self) -> ScenarioSpec:
        for index, actor in enumerate(self.actors):
            if actor.initial_state is not None and actor.initial_state.lane >= self.map.lane_count:
                raise ValueError(f"actors.{index}.initial_state.lane must fit map.lane_count")
            if actor.goal is not None and actor.goal.lane is not None and actor.goal.lane >= self.map.lane_count:
                raise ValueError(f"actors.{index}.goal.lane must fit map.lane_count")
        obstacle_ids = [obstacle.id for obstacle in self.static_obstacles]
        if len(obstacle_ids) != len(set(obstacle_ids)):
            raise ValueError("static_obstacles ids must be unique")
        for index, obstacle in enumerate(self.static_obstacles):
            if obstacle.lane >= self.map.lane_count:
                raise ValueError(f"static_obstacles.{index}.lane must fit map.lane_count")
        trigger_ids = [trigger.id for trigger in self.event_triggers]
        if len(trigger_ids) != len(set(trigger_ids)):
            raise ValueError("event_triggers ids must be unique")
        actor_ids = {actor.id for actor in self.actors}
        for index, trigger in enumerate(self.event_triggers):
            if trigger.target_actor_id is not None and trigger.target_actor_id not in actor_ids:
                raise ValueError(f"event_triggers.{index}.target_actor_id must name a declared actor")
        return self


class ResourceLimits(_StrictModel):
    workers: int = Field(gt=0)
    aggregate_cpu_threads: int = Field(gt=0)
    max_steps: int = Field(gt=0)
    max_simulated_seconds: float = Field(gt=0, allow_inf_nan=False)
    case_wall_seconds: float = Field(gt=0, allow_inf_nan=False)
    bundle_wall_seconds: float = Field(gt=0, allow_inf_nan=False)
    bundle_disk_bytes: int = Field(gt=0)


class RunRequest(_StrictModel):
    schema_version: Literal["scenarioforge.run-request.v1"]
    scenario_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    seeds: tuple[int, ...] = Field(min_length=1, max_length=17)
    profile: Literal["default", "boundary"]
    limits: ResourceLimits

    @field_validator("seeds", mode="before")
    @classmethod
    def freeze_seeds(cls, seeds: object) -> object:
        return tuple(seeds) if isinstance(seeds, list) else seeds

    @field_validator("seeds")
    @classmethod
    def ordered_unique_bounded_seeds(cls, seeds: tuple[int, ...]) -> tuple[int, ...]:
        if len(seeds) != len(set(seeds)):
            raise ValueError("seeds must be ordered and unique")
        if any(seed < 0 or seed >= 2**31 for seed in seeds):
            raise ValueError("seeds must be between 0 and 2147483647")
        return seeds

    @property
    def digest(self) -> str:
        data = rfc8785.dumps(self.model_dump(mode="json"))
        return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CanonicalScenario:
    bytes: bytes
    digest: str
