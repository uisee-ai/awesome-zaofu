from __future__ import annotations

import hashlib
from typing import Any, NoReturn

import rfc8785

from scenarioforge.spec import RunRequest, ScenarioSpec, canonical_scenario

from .models import CompiledBundle, CompiledCase

DEFAULT_MAXIMA = {
    "cases": 4,
    "actors": 4,
    "workers": 1,
    "aggregate_cpu_threads": 2,
    "max_steps": 3_000,
    "max_simulated_seconds": 30.0,
    "case_wall_seconds": 60.0,
    "bundle_wall_seconds": 600.0,
    "bundle_disk_bytes": 1_073_741_824,
}
HARD_MAXIMA = {
    "cases": 16,
    "actors": 8,
    "workers": 2,
    "aggregate_cpu_threads": 4,
    "max_steps": 10_000,
    "max_simulated_seconds": 60.0,
    "case_wall_seconds": 120.0,
    "bundle_wall_seconds": 1_800.0,
    "bundle_disk_bytes": 2_147_483_648,
}


class CompilationError(ValueError):
    def __init__(self, diagnostics: list[dict[str, str]]):
        self.diagnostics = diagnostics
        super().__init__("; ".join(item["message"] for item in diagnostics))


def _reject(location: str, message: str) -> NoReturn:
    raise CompilationError([{"location": location, "code": "limit_exceeded", "message": message}])


def _reject_unsupported(location: str, message: str) -> NoReturn:
    raise CompilationError(
        [{"location": location, "code": "unsupported_runtime_semantics", "message": message}]
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _check_limits(scenario: ScenarioSpec, request: RunRequest) -> None:
    maxima = DEFAULT_MAXIMA if request.profile == "default" else HARD_MAXIMA
    if len(request.seeds) > maxima["cases"]:
        _reject("seeds", f"{request.profile} profile permits at most {maxima['cases']} cases")
    if len(scenario.actors) > maxima["actors"]:
        _reject("actors", f"{request.profile} profile permits at most {maxima['actors']} actors")
    for field in (
        "workers",
        "aggregate_cpu_threads",
        "max_steps",
        "max_simulated_seconds",
        "case_wall_seconds",
        "bundle_wall_seconds",
        "bundle_disk_bytes",
    ):
        value = getattr(request.limits, field)
        if value > maxima[field]:
            _reject(f"limits.{field}", f"{field}={value} exceeds {request.profile} maximum {maxima[field]}")
    if request.limits.aggregate_cpu_threads < request.limits.workers:
        _reject("limits.aggregate_cpu_threads", "aggregate CPU threads must cover every worker")


def _p0_provenance(scenario: ScenarioSpec) -> dict[str, Any]:
    """Preserve P0 domain semantics that MetaDrive's base config cannot express directly."""
    return {
        "actors": [actor.model_dump(mode="json") for actor in scenario.actors],
        "event_triggers": [trigger.model_dump(mode="json") for trigger in scenario.event_triggers],
        "safety": None if scenario.safety is None else scenario.safety.model_dump(mode="json"),
        "static_obstacles": [obstacle.model_dump(mode="json") for obstacle in scenario.static_obstacles],
    }


def _runtime_plan(scenario: ScenarioSpec) -> dict[str, Any]:
    """Create the small, executable semantic plan consumed by the worker.

    Keeping this separate from provenance prevents accepted authoring fields from
    being silently archived without a runtime consumer.
    """
    return {
        "schema_version": "scenarioforge.runtime-plan.v1",
        "actors": [actor.model_dump(mode="json") for actor in scenario.actors],
        "event_triggers": [trigger.model_dump(mode="json") for trigger in scenario.event_triggers],
        "static_obstacles": [obstacle.model_dump(mode="json") for obstacle in scenario.static_obstacles],
        "safety": None if scenario.safety is None else scenario.safety.model_dump(mode="json"),
    }


def _check_runtime_semantics(scenario: ScenarioSpec) -> None:
    """Reject authoring values the real worker cannot execute deterministically."""
    for index, actor in enumerate(scenario.actors):
        if actor.goal is not None:
            _reject_unsupported(
                f"actors.{index}.goal.kind",
                f"goal kind {actor.goal.kind} is not supported by the MetaDrive runtime",
            )
        if actor.behavior == "cross_intersection":
            _reject_unsupported(
                f"actors.{index}.behavior",
                "behavior cross_intersection is not supported by the MetaDrive runtime",
            )
    for index, obstacle in enumerate(scenario.static_obstacles):
        expected_length = {"barrier": 2.0, "cone": 0.8}.get(obstacle.kind)
        if expected_length is not None and obstacle.length != expected_length:
            _reject_unsupported(
                f"static_obstacles.{index}.length",
                f"{obstacle.kind} supports runtime length {expected_length}",
            )
    for index, trigger in enumerate(scenario.event_triggers):
        target_required = trigger.action in {"yield", "spawn_traffic"} or trigger.kind == "on_approach"
        if target_required and trigger.target_actor_id is None:
            _reject_unsupported(
                f"event_triggers.{index}.target_actor_id",
                f"{trigger.action} requires an explicit target_actor_id",
            )


def _ego_initial_config(scenario: ScenarioSpec) -> dict[str, dict[str, object]]:
    ego = next(actor for actor in scenario.actors if actor.role == "ego")
    if ego.initial_state is None:
        return {}
    return {
        "default_agent": {
            "spawn_lane_index": [">", ">>", ego.initial_state.lane],
            "spawn_longitude": ego.initial_state.longitudinal,
            "spawn_velocity": [ego.initial_state.speed, 0.0],
            "spawn_velocity_car_frame": True,
        }
    }


def compile_scenario(scenario: ScenarioSpec, request: RunRequest) -> CompiledBundle:
    scenario_identity = canonical_scenario(scenario)
    if request.scenario_digest != scenario_identity.digest:
        raise CompilationError(
            [
                {
                    "location": "scenario_digest",
                    "code": "digest_mismatch",
                    "message": "RunRequest scenario_digest does not identify the supplied ScenarioSpec",
                }
            ]
        )
    _check_limits(scenario, request)
    _check_runtime_semantics(scenario)
    p0_provenance = _p0_provenance(scenario)
    runtime_plan = _runtime_plan(scenario)
    agent_configs = _ego_initial_config(scenario)
    cases: list[CompiledCase] = []
    for index, seed in enumerate(request.seeds):
        config = {
            "use_render": False,
            "image_observation": False,
            "show_logo": False,
            "num_scenarios": 1,
            "start_seed": seed,
            "map": 3,
            "map_config": {
                "type": "block_sequence",
                "config": scenario.map.block_sequence,
                "lane_num": scenario.map.lane_count,
                "lane_width": scenario.map.lane_width,
            },
            "traffic_density": scenario.environment.traffic_density,
            "random_traffic": False,
            "horizon": request.limits.max_steps,
            "truncate_as_terminate": False,
            "log_level": 30,
        }
        if agent_configs:
            config["agent_configs"] = agent_configs
        cases.append(
            CompiledCase(
                case_index=index,
                seed=seed,
                actor_plan=scenario.actors,
                metadrive_config=config,
                p0_provenance=p0_provenance,
                runtime_plan=runtime_plan,
                effective_config_digest=_sha256(config),
            )
        )
    effective_config_digest = _sha256([case.metadrive_config for case in cases])
    data = {
        "schema_version": "scenarioforge.compiled-bundle.v1",
        "scenario_digest": scenario_identity.digest,
        "run_request_digest": request.digest,
        "compiler_version": "scenarioforge.compiler.v1",
        "backend": {"distribution": "metadrive-simulator", "version": "0.4.3"},
        "field_map": {
            "/actors": "/cases/*/actor_plan",
            "/actors/*/behavior": "/cases/*/runtime_plan/actors/*/behavior",
            "/actors/*/goal": "/cases/*/runtime_plan/actors/*/goal",
            "/actors/*/initial_state": "/cases/*/runtime_plan/actors/*/initial_state",
            "/actors/*/initial_state/lane": (
                "/cases/*/metadrive_config/agent_configs/default_agent/spawn_lane_index/2"
            ),
            "/actors/*/initial_state/longitudinal": (
                "/cases/*/metadrive_config/agent_configs/default_agent/spawn_longitude"
            ),
            "/actors/*/initial_state/speed": (
                "/cases/*/metadrive_config/agent_configs/default_agent/spawn_velocity/0"
            ),
            "/environment/traffic_density": "/cases/*/metadrive_config/traffic_density",
            "/event_triggers": "/cases/*/runtime_plan/event_triggers",
            "/event_triggers/*": "/cases/*/runtime_plan/event_triggers/*",
            "/map/block_sequence": "/cases/*/metadrive_config/map_config/config",
            "/map/lane_count": "/cases/*/metadrive_config/map_config/lane_num",
            "/map/lane_width": "/cases/*/metadrive_config/map_config/lane_width",
            "/name": "/metadata/scenario_name",
            "/safety": "/cases/*/runtime_plan/safety",
            "/schema_version": "/metadata/source_schema_version",
            "/static_obstacles": "/cases/*/runtime_plan/static_obstacles",
            "/static_obstacles/*": "/cases/*/runtime_plan/static_obstacles/*",
            "/tags": "/metadata/tags",
        },
        "metadata": {
            "scenario_name": scenario.name,
            "source_schema_version": scenario.schema_version,
            "tags": scenario.tags,
        },
        "limits": request.limits.model_dump(mode="json"),
        "cases": tuple(case.model_dump(mode="json") for case in cases),
        "effective_config_digest": effective_config_digest,
    }
    return CompiledBundle(
        **data,
        compiled_digest=_sha256(data),
    )
