from __future__ import annotations

import json
from pathlib import Path

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    canonical_bytes,
    instantiate_scenario,
    load_scenario,
)
from scenarioforge.core.canonical import canonical_digest
from scenarioforge.runtime.adapter import MetaDriveAdapter
from scenarioforge.runtime.policy import (
    apply_declared_route_control,
    resolve_tick_actions,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "prototype_v2.json"
GOLDEN = ROOT / "tests" / "fixtures" / "p0c" / "contracts" / "golden_contract.json"


def test_v2_shared_primitives_round_trip_without_freezing_calibration_values() -> None:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    instance = instantiate_scenario(load_scenario(FIXTURE))
    compiler = ScenarioCompiler()
    bundle = compiler.compile(instance)

    assert bundle.report.overall_status is CompilationStatus.EXACT
    assert bundle.report.diagnostics == ()
    assert bundle.execution_plan is not None
    plan = bundle.execution_plan.to_dict()
    assert {
        "capability_descriptor": compiler.capabilities(instance.source_schema_version).digest,
        "scenario_instance": instance.digest,
        "compile_report": bundle.report.digest,
        "execution_plan": bundle.execution_plan.digest,
    } == golden["canonical_digests"]
    assert list(compiler.capabilities(instance.source_schema_version).supported_capabilities) == (
        golden["supported_capabilities"]
    )
    assert [item.capability for item in bundle.report.mappings] == golden[
        "requested_capability_order"
    ]
    assert plan["schema_version"] == "scenarioforge.execution-plan/v2"
    assert plan["simulation"]["topology"] == source["road"]
    assert plan["participants"] == source["participants"]
    assert plan["events"] == source["events"]
    assert plan["constraints"] == source["constraints"]
    assert plan["policy"] == source["policy"]
    assert [event["sequence"] for event in plan["events"]] == [0, 1]
    assert plan["constraints"]["expected_events"] == [
        "cut-in-started",
        "ego-brake-response",
    ]
    assert [item["metric"] for item in plan["constraints"]["metric_definitions"]] == golden[
        "metric_order"
    ]
    assert all(
        item["threshold"] is None
        for item in plan["constraints"]["metric_definitions"]
    )

    adapter_config = MetaDriveAdapter(plan)._config()
    assert adapter_config["agent_configs"]["agent0"]["spawn_lane_index"] == (
        ">>",
        ">>>",
        1,
    )
    assert adapter_config["agent_configs"]["agent0"]["destination"] == ">>>"
    assert adapter_config["agent_configs"]["agent1"]["spawn_lane_index"] == (
        ">>",
        ">>>",
        0,
    )
    assert adapter_config["agent_configs"]["agent1"]["destination"] == ">>>"
    assert adapter_config["map_config"] == {
        "type": "block_sequence",
        "config": "SS",
        "lane_width": 3.5,
        "lane_num": 2,
        "exit_length": 250.0,
        "start_position": [0, 0],
    }
    assert plan["artifact_contract"]["required"] == golden["required_artifacts"]
    assert plan["tick_contract"] == golden["tick_contract"]
    assert canonical_digest(plan) == golden["canonical_digests"]["execution_plan"]


def test_v2_policy_keeps_participant_order_and_same_tick_event_order() -> None:
    instance = instantiate_scenario(load_scenario(FIXTURE))
    plan_model = ScenarioCompiler().compile(instance).execution_plan
    assert plan_model is not None
    plan = plan_model.to_dict()

    actions, records, fired = resolve_tick_actions(plan, 3)

    assert list(actions) == ["ego", "cutter"]
    assert actions == {"ego": [0.0, 0.15], "cutter": [-0.25, 0.0]}
    assert [(item["tick"], item["participant_id"]) for item in records] == [
        (3, "ego"),
        (3, "cutter"),
    ]
    assert fired == [
        {
            "schema_version": "scenarioforge.event/v2",
            "event_id": "cut-in-started",
            "sequence": 0,
            "type": "trigger_fired",
            "participant_id": "cutter",
            "trigger_tick": 3,
            "effect_state_tick": 4,
            "priority_contract": "scenarioforge.trigger-priority/v2",
            "action": {"steering": -0.25, "throttle_brake": 0.0},
        }
    ]


def test_v2_policy_uses_declared_default_and_ignores_non_matching_triggers() -> None:
    instance = instantiate_scenario(load_scenario(FIXTURE))
    plan_model = ScenarioCompiler().compile(instance).execution_plan
    assert plan_model is not None
    plan = plan_model.to_dict()
    plan["policy"]["config"]["participant_actions"] = [
        plan["policy"]["config"]["participant_actions"][0]
    ]

    actions, records, fired = resolve_tick_actions(plan, 2)

    assert actions == {"ego": [0.0, 0.15], "cutter": [0.0, 0.0]}
    assert [item["source"] for item in records] == ["policy", "policy"]
    assert fired == []


def test_v2_policy_applies_a_declared_control_interval_and_fires_once() -> None:
    instance = instantiate_scenario(load_scenario(FIXTURE))
    plan_model = ScenarioCompiler().compile(instance).execution_plan
    assert plan_model is not None
    plan = plan_model.to_dict()
    plan["events"][0]["duration_ticks"] = 3

    at_trigger = resolve_tick_actions(plan, 3)
    during_interval = resolve_tick_actions(plan, 5)
    after_interval = resolve_tick_actions(plan, 6)

    assert at_trigger[0]["cutter"] == [-0.25, 0.0]
    assert [item["event_id"] for item in at_trigger[2]] == ["cut-in-started"]
    assert during_interval[0]["cutter"] == [-0.25, 0.0]
    assert during_interval[1][1]["source"] == "scenario_override"
    assert during_interval[2] == []
    assert after_interval[0]["cutter"] == [0.0, 0.1]
    assert after_interval[1][1]["source"] == "policy"
    assert after_interval[2] == []


def test_v2_route_control_preserves_same_tick_scenario_override() -> None:
    actions = {"ego": [0.0, 0.15], "cutter": [-0.25, 0.0]}
    records = [
        {
            "participant_id": "ego",
            "policy_action": {"steering": 0.0, "throttle_brake": 0.15},
            "final_action": {"steering": 0.0, "throttle_brake": 0.15},
            "source": "policy",
        },
        {
            "participant_id": "cutter",
            "policy_action": {"steering": 0.0, "throttle_brake": 0.1},
            "final_action": {"steering": -0.25, "throttle_brake": 0.0},
            "source": "scenario_override",
        },
    ]

    adjusted_actions, adjusted_records = apply_declared_route_control(
        actions,
        records,
        {"ego": [1.5, 0.05], "cutter": [0.75, -0.5]},
    )

    assert adjusted_actions == {"ego": [1.0, 0.05], "cutter": [-0.25, 0.0]}
    assert adjusted_records[0]["policy_action"] == {
        "steering": 1.0,
        "throttle_brake": 0.05,
    }
    assert adjusted_records[0]["final_action"] == {
        "steering": 1.0,
        "throttle_brake": 0.05,
    }
    assert adjusted_records[1]["policy_action"] == {
        "steering": 0.75,
        "throttle_brake": -0.5,
    }
    assert adjusted_records[1]["final_action"] == {
        "steering": -0.25,
        "throttle_brake": 0.0,
    }
    assert actions == {"ego": [0.0, 0.15], "cutter": [-0.25, 0.0]}
    assert records[0]["final_action"]["steering"] == 0.0


def test_v2_compiler_rejects_runtime_projection_ambiguity(tmp_path: Path) -> None:
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source["road"]["lanes"][0]["engine_lane_index"]["start_node"] = "orphan"
    source["events"][0]["trigger"]["tick"] = source["constraints"]["max_steps"]
    source["constraints"]["duration_s"] = 11.0
    source["constraints"]["metric_definitions"][0]["applies_to"][
        "participant_ids"
    ] = ["ghost"]
    source["policy"]["config"]["participant_actions"].append(
        dict(source["policy"]["config"]["participant_actions"][0])
    )
    candidate = tmp_path / "ambiguous_projection.json"
    candidate.write_bytes(canonical_bytes(source))

    bundle = ScenarioCompiler().compile(
        instantiate_scenario(load_scenario(candidate))
    )

    assert bundle.report.overall_status is CompilationStatus.UNSUPPORTED
    assert bundle.execution_plan is None
    assert {diagnostic.path for diagnostic in bundle.report.diagnostics} == {
        "$.participants[1].route.lane_ids[1]",
        "$.events[0].trigger.tick",
        "$.constraints.duration_s",
        "$.constraints.metric_definitions[0].applies_to.participant_ids",
        "$.policy.config.participant_actions",
    }
