from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scenarioforge.compiler import CompilationError, compile_scenario
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


SAMPLES_ROOT = Path(__file__).parents[2] / "samples"


def test_p0_fields_have_complete_config_and_provenance_mappings(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    payload = deepcopy(scenario_payload)
    payload["actors"][0].update(
        {
            "initial_state": {"lane": 0, "longitudinal": 8.0, "speed": 7.5},
            "behavior": "follow_lead",
        }
    )
    payload["static_obstacles"] = [
        {"id": "barrier-1", "kind": "barrier", "lane": 1, "longitudinal": 35.0, "length": 2.0}
    ]
    payload["event_triggers"] = [
        {"id": "slow-traffic", "kind": "at_distance", "distance": 25.0, "action": "set_speed_limit"}
    ]
    payload["safety"] = {"max_speed": 20.0, "minimum_headway": 1.5, "collision_free": True}
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest

    compiled = compile_scenario(scenario, RunRequest.model_validate(request_payload))

    assert {
        key: value
        for key, value in compiled.field_map.items()
        if key not in {"/event_triggers/*", "/static_obstacles/*"}
    } == {
        "/actors": "/cases/*/actor_plan",
        "/actors/*/behavior": "/cases/*/runtime_plan/actors/*/behavior",
        "/actors/*/goal": "/cases/*/runtime_plan/actors/*/goal",
        "/actors/*/initial_state": "/cases/*/runtime_plan/actors/*/initial_state",
        "/actors/*/initial_state/lane": "/cases/*/metadrive_config/agent_configs/default_agent/spawn_lane_index/2",
        "/actors/*/initial_state/longitudinal": "/cases/*/metadrive_config/agent_configs/default_agent/spawn_longitude",
        "/actors/*/initial_state/speed": "/cases/*/metadrive_config/agent_configs/default_agent/spawn_velocity/0",
        "/environment/traffic_density": "/cases/*/metadrive_config/traffic_density",
        "/event_triggers": "/cases/*/runtime_plan/event_triggers",
        "/map/block_sequence": "/cases/*/metadrive_config/map_config/config",
        "/map/lane_count": "/cases/*/metadrive_config/map_config/lane_num",
        "/map/lane_width": "/cases/*/metadrive_config/map_config/lane_width",
        "/name": "/metadata/scenario_name",
        "/safety": "/cases/*/runtime_plan/safety",
        "/schema_version": "/metadata/source_schema_version",
        "/static_obstacles": "/cases/*/runtime_plan/static_obstacles",
        "/tags": "/metadata/tags",
    }
    assert compiled.cases[0].metadrive_config["agent_configs"] == {
        "default_agent": {
            "spawn_lane_index": [">", ">>", 0],
            "spawn_longitude": 8.0,
            "spawn_velocity": [7.5, 0.0],
            "spawn_velocity_car_frame": True,
        }
    }
    assert compiled.cases[0].p0_provenance == {
        "actors": [
            {
                "id": "ego",
                "role": "ego",
                "initial_state": {"lane": 0, "longitudinal": 8.0, "speed": 7.5},
                "behavior": "follow_lead",
            },
            {"id": "npc-1", "role": "traffic"},
        ],
        "event_triggers": [
            {
                "id": "slow-traffic",
                "kind": "at_distance",
                "action": "set_speed_limit",
                "seconds": None,
                "distance": 25.0,
            }
        ],
        "safety": {"max_speed": 20.0, "minimum_headway": 1.5, "collision_free": True},
        "static_obstacles": [
            {"id": "barrier-1", "kind": "barrier", "lane": 1, "longitudinal": 35.0, "length": 2.0}
        ],
    }


def test_compiler_preserves_metadrive_default_agent_config_without_authored_initial_state(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    scenario = load_scenario(json.dumps(scenario_payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest

    compiled = compile_scenario(scenario, RunRequest.model_validate(request_payload))

    assert "agent_configs" not in compiled.cases[0].metadrive_config


def test_unaddressed_runtime_yield_trigger_fails_closed_before_execution(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    payload = deepcopy(scenario_payload)
    payload["event_triggers"] = [
        {"id": "brake", "kind": "at_time", "seconds": 2.0, "action": "yield"}
    ]
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest

    with pytest.raises(CompilationError) as raised:
        compile_scenario(scenario, RunRequest.model_validate(request_payload))

    assert raised.value.diagnostics == [
        {
            "location": "event_triggers.0.target_actor_id",
            "code": "unsupported_runtime_semantics",
            "message": "yield requires an explicit target_actor_id",
        }
    ]


@pytest.mark.parametrize(
    ("goal", "location"),
    [
        ({"kind": "route_progress", "minimum_progress": 0.8}, "actors.0.goal.kind"),
        ({"kind": "lane", "lane": 1}, "actors.0.goal.kind"),
        ({"kind": "stop"}, "actors.0.goal.kind"),
    ],
)
def test_unsupported_goal_kinds_fail_closed_before_execution(
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
    goal: dict[str, object],
    location: str,
) -> None:
    payload = deepcopy(scenario_payload)
    payload["actors"][0]["goal"] = goal
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest

    with pytest.raises(CompilationError) as raised:
        compile_scenario(scenario, RunRequest.model_validate(request_payload))

    assert raised.value.diagnostics == [
        {
            "location": location,
            "code": "unsupported_runtime_semantics",
            "message": f"goal kind {goal['kind']} is not supported by the MetaDrive runtime",
        }
    ]


def test_cross_intersection_behavior_fails_closed_before_execution(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    payload = deepcopy(scenario_payload)
    payload["actors"][0]["behavior"] = "cross_intersection"
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = deepcopy(run_request_payload)
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest

    with pytest.raises(CompilationError) as raised:
        compile_scenario(scenario, RunRequest.model_validate(request_payload))

    assert raised.value.diagnostics == [
        {
            "location": "actors.0.behavior",
            "code": "unsupported_runtime_semantics",
            "message": "behavior cross_intersection is not supported by the MetaDrive runtime",
        }
    ]


def test_all_catalog_samples_compile_repeatedly_with_complete_p0_provenance(
    run_request_payload: dict[str, object]
) -> None:
    catalog = json.loads((SAMPLES_ROOT / "catalog.json").read_text(encoding="utf-8"))

    for sample in catalog["samples"]:
        scenario = load_scenario(
            (SAMPLES_ROOT / sample["json"]).read_text(encoding="utf-8"), "application/json"
        )
        request_payload = deepcopy(run_request_payload)
        request_payload["seeds"] = [17]
        request_payload["scenario_digest"] = canonical_scenario(scenario).digest
        request = RunRequest.model_validate(request_payload)

        target_required = any(
            trigger.action in {"yield", "spawn_traffic"} or trigger.kind == "on_approach"
            for trigger in scenario.event_triggers
        )
        has_unaddressed_trigger = any(
            (trigger.action in {"yield", "spawn_traffic"} or trigger.kind == "on_approach")
            and trigger.target_actor_id is None
            for trigger in scenario.event_triggers
        )
        has_unsupported_goal_or_behavior = any(
            actor.goal is not None or actor.behavior == "cross_intersection" for actor in scenario.actors
        )
        if (target_required and has_unaddressed_trigger) or has_unsupported_goal_or_behavior:
            with pytest.raises(CompilationError) as raised:
                compile_scenario(scenario, request)
            assert raised.value.diagnostics[0]["code"] == "unsupported_runtime_semantics"
            continue

        first = compile_scenario(scenario, request)
        second = compile_scenario(scenario, request)

        assert first.canonical_bytes() == second.canonical_bytes()
        assert first.compiled_digest == second.compiled_digest
        assert first.cases[0].p0_provenance["actors"] == [
            actor.model_dump(mode="json") for actor in scenario.actors
        ]
        assert first.cases[0].p0_provenance["static_obstacles"] == [
            obstacle.model_dump(mode="json") for obstacle in scenario.static_obstacles
        ]
        assert first.cases[0].p0_provenance["event_triggers"] == [
            trigger.model_dump(mode="json") for trigger in scenario.event_triggers
        ]
        assert first.cases[0].p0_provenance["safety"] == (
            None if scenario.safety is None else scenario.safety.model_dump(mode="json")
        )


def test_compilation_is_repeatable_and_has_complete_field_mapping(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object]
) -> None:
    scenario = load_scenario(json.dumps(scenario_payload), "application/json")
    run_request_payload["scenario_digest"] = canonical_scenario(scenario).digest
    request = RunRequest.model_validate(run_request_payload)

    first = compile_scenario(scenario, request)
    second = compile_scenario(scenario, request)

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.compiled_digest == second.compiled_digest
    assert first.effective_config_digest == second.effective_config_digest
    first_dump = first.model_dump(mode="json")
    for case in first_dump["cases"]:
        case.pop("runtime_plan")
    first_dump["field_map"].pop("/event_triggers/*")
    first_dump["field_map"].pop("/static_obstacles/*")
    assert first_dump == {
        "schema_version": "scenarioforge.compiled-bundle.v1",
        "scenario_digest": canonical_scenario(scenario).digest,
        "run_request_digest": request.digest,
        "compiler_version": "scenarioforge.compiler.v1",
        "backend": {"distribution": "metadrive-simulator", "version": "0.4.3"},
        "field_map": {
            "/actors": "/cases/*/actor_plan",
            "/actors/*/behavior": "/cases/*/runtime_plan/actors/*/behavior",
            "/actors/*/goal": "/cases/*/runtime_plan/actors/*/goal",
            "/actors/*/initial_state": "/cases/*/runtime_plan/actors/*/initial_state",
            "/actors/*/initial_state/lane": "/cases/*/metadrive_config/agent_configs/default_agent/spawn_lane_index/2",
            "/actors/*/initial_state/longitudinal": "/cases/*/metadrive_config/agent_configs/default_agent/spawn_longitude",
            "/actors/*/initial_state/speed": "/cases/*/metadrive_config/agent_configs/default_agent/spawn_velocity/0",
            "/environment/traffic_density": "/cases/*/metadrive_config/traffic_density",
            "/event_triggers": "/cases/*/runtime_plan/event_triggers",
            "/map/block_sequence": "/cases/*/metadrive_config/map_config/config",
            "/map/lane_count": "/cases/*/metadrive_config/map_config/lane_num",
            "/map/lane_width": "/cases/*/metadrive_config/map_config/lane_width",
            "/name": "/metadata/scenario_name",
            "/safety": "/cases/*/runtime_plan/safety",
            "/schema_version": "/metadata/source_schema_version",
            "/static_obstacles": "/cases/*/runtime_plan/static_obstacles",
            "/tags": "/metadata/tags",
        },
        "metadata": {
            "scenario_name": "canonical-demo",
            "source_schema_version": "scenarioforge.scenario-spec.v1",
            "tags": ["demo"],
        },
        "limits": {
            "workers": 1,
            "aggregate_cpu_threads": 2,
            "max_steps": 40,
            "max_simulated_seconds": 30.0,
            "case_wall_seconds": 60.0,
            "bundle_wall_seconds": 600.0,
            "bundle_disk_bytes": 1_073_741_824,
        },
        "cases": [
            {
                "case_index": 0,
                "seed": 17,
                "actor_plan": [
                    {"id": "ego", "role": "ego"},
                    {"id": "npc-1", "role": "traffic"},
                ],
                "metadrive_config": {
                    "use_render": False,
                    "image_observation": False,
                    "show_logo": False,
                    "num_scenarios": 1,
                    "start_seed": 17,
                    "map": 3,
                    "map_config": {
                        "type": "block_sequence",
                        "config": "S",
                        "lane_num": 2,
                        "lane_width": 3.5,
                    },
                    "traffic_density": 0.1,
                    "random_traffic": False,
                    "horizon": 40,
                    "truncate_as_terminate": False,
                    "log_level": 30,
                },
                "p0_provenance": {
                    "actors": [{"id": "ego", "role": "ego"}, {"id": "npc-1", "role": "traffic"}],
                    "event_triggers": [],
                    "safety": None,
                    "static_obstacles": [],
                },
                "effective_config_digest": first.cases[0].effective_config_digest,
            },
            {
                "case_index": 1,
                "seed": 23,
                "actor_plan": [
                    {"id": "ego", "role": "ego"},
                    {"id": "npc-1", "role": "traffic"},
                ],
                "metadrive_config": {
                    "use_render": False,
                    "image_observation": False,
                    "show_logo": False,
                    "num_scenarios": 1,
                    "start_seed": 23,
                    "map": 3,
                    "map_config": {
                        "type": "block_sequence",
                        "config": "S",
                        "lane_num": 2,
                        "lane_width": 3.5,
                    },
                    "traffic_density": 0.1,
                    "random_traffic": False,
                    "horizon": 40,
                    "truncate_as_terminate": False,
                    "log_level": 30,
                },
                "p0_provenance": {
                    "actors": [{"id": "ego", "role": "ego"}, {"id": "npc-1", "role": "traffic"}],
                    "event_triggers": [],
                    "safety": None,
                    "static_obstacles": [],
                },
                "effective_config_digest": first.cases[1].effective_config_digest,
            },
        ],
        "effective_config_digest": first.effective_config_digest,
        "compiled_digest": first.compiled_digest,
    }


@pytest.mark.parametrize(
    ("profile", "seeds", "actors", "limits_patch", "location"),
    [
        ("default", list(range(5)), 2, {}, "seeds"),
        ("boundary", list(range(17)), 2, {}, "seeds"),
        ("default", [1], 5, {}, "actors"),
        ("boundary", [1], 2, {"workers": 3}, "limits.workers"),
        ("boundary", [1], 2, {"aggregate_cpu_threads": 5}, "limits.aggregate_cpu_threads"),
        ("boundary", [1], 2, {"max_steps": 10_001}, "limits.max_steps"),
        ("boundary", [1], 2, {"max_simulated_seconds": 60.1}, "limits.max_simulated_seconds"),
        ("boundary", [1], 2, {"case_wall_seconds": 120.1}, "limits.case_wall_seconds"),
        ("boundary", [1], 2, {"bundle_wall_seconds": 1800.1}, "limits.bundle_wall_seconds"),
        ("boundary", [1], 2, {"bundle_disk_bytes": 2_147_483_649}, "limits.bundle_disk_bytes"),
    ],
)
def test_profile_and_hard_resource_limits_fail_before_execution(
    scenario_payload: dict[str, object],
    run_request_payload: dict[str, object],
    copied,
    profile: str,
    seeds: list[int],
    actors: int,
    limits_patch: dict[str, object],
    location: str,
) -> None:
    payload = copied(scenario_payload)
    payload["actors"] = [
        {"id": "ego", "role": "ego"},
        *({"id": f"npc-{index}", "role": "traffic"} for index in range(actors - 1)),
    ]
    scenario = load_scenario(json.dumps(payload), "application/json")
    request_payload = copied(run_request_payload)
    request_payload["profile"] = profile
    request_payload["seeds"] = seeds
    request_payload["scenario_digest"] = canonical_scenario(scenario).digest
    request_payload["limits"].update(limits_patch)

    with pytest.raises(CompilationError) as raised:
        request = RunRequest.model_validate(request_payload)
        compile_scenario(scenario, request)

    assert raised.value.diagnostics[0]["location"] == location


def test_digest_mismatch_and_duplicate_or_out_of_range_seeds_are_rejected(
    scenario_payload: dict[str, object], run_request_payload: dict[str, object], copied
) -> None:
    scenario = load_scenario(json.dumps(scenario_payload), "application/json")
    invalid_requests = [
        run_request_payload,
        {**copied(run_request_payload), "seeds": [4, 4]},
        {**copied(run_request_payload), "seeds": [-1]},
        {**copied(run_request_payload), "seeds": [2**31]},
    ]

    for payload in invalid_requests:
        with pytest.raises((CompilationError, ValueError)):
            request = RunRequest.model_validate(payload)
            compile_scenario(scenario, request)
