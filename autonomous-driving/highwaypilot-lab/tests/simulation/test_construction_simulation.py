import json
from pathlib import Path

import pytest

from highwaypilot_lab.config import parse_config
from highwaypilot_lab.simulation import ACTIONS, ConstructionSimulation
from highwaypilot_lab.strategies.policy import QualifiedRulePolicy


PRESET_ROOT = Path("configs/presets")


def load_preset(name: str) -> dict[str, object]:
    return json.loads((PRESET_ROOT / f"{name}-v1.json").read_text(encoding="utf-8"))


def empty_traffic_config(*, lanes_count: int = 3, side: str = "right", seed: int = 17) -> dict[str, object]:
    return parse_config(
        {
            "schema_version": "construction-config/v1",
            "scenario_id": "construction-v0",
            "seed": seed,
            "road": {"lanes_count": lanes_count},
            "construction": {"side": side},
            "traffic": {"vehicles_count": 0},
        }
    )


def test_normal_preset_creates_a_complete_python_authoritative_world() -> None:
    simulation = ConstructionSimulation.from_config(load_preset("normal"))

    snapshot = simulation.snapshot()
    assert list(snapshot) == [
        "schema_version",
        "authority",
        "scenario_id",
        "step",
        "time_s",
        "config_digest",
        "rng",
        "road",
        "construction",
        "ego",
        "vehicles",
        "objects",
        "reward",
        "safety",
        "status",
        "last_action",
        "available_actions",
    ]
    assert snapshot["schema_version"] == "simulation-snapshot/v1"
    assert snapshot["authority"] == "python"
    assert snapshot["road"] == {
        "lanes_count": 3,
        "lane_width_m": 4.0,
        "length_m": 1000.0,
        "speed_limit_mps": 30.0,
    }
    assert snapshot["construction"] == {
        "side": "right",
        "closed_lane_index": 2,
        "target_lane_index": 1,
        "zone_start_m": 260.0,
        "zone_end_m": 340.0,
        "authoritative_merge_action": "LANE_LEFT",
    }
    assert snapshot["ego"]["lane_index"] == 2
    assert snapshot["ego"]["position_m"] == {"x": 40.0, "y": 8.0}
    assert snapshot["ego"]["speed_mps"] == 22.0
    assert set(snapshot["ego"]) == {
        "vehicle_id",
        "position_m",
        "speed_mps",
        "heading_rad",
        "lane_index",
        "target_lane_index",
        "crashed",
        "scenario_event",
    }
    assert len(snapshot["vehicles"]) == 10
    assert all(set(vehicle) == set(snapshot["ego"]) for vehicle in snapshot["vehicles"])
    assert all(
        set(item) == {"object_id", "kind", "position_m", "lane_index", "solid"}
        for item in snapshot["objects"]
    )
    assert {item["lane_index"] for item in snapshot["objects"] if item["kind"] == "barrier"} == {2}
    assert [
        item["position_m"]["x"]
        for item in snapshot["objects"]
        if item["kind"] == "warning"
    ] == [140.0, 180.0, 220.0]
    assert snapshot["rng"]["env_seed"] == 261_116_608
    assert snapshot["rng"]["env_core_sealed"] is True


def test_traffic_upper_bound_materializes_all_fifty_vehicles() -> None:
    config = parse_config(
        {
            "schema_version": "construction-config/v1",
            "scenario_id": "construction-v0",
            "seed": 101,
            "traffic": {"vehicles_count": 50},
        }
    )
    simulation = ConstructionSimulation.from_config(config)
    try:
        assert config["traffic"]["vehicles_count"] == 50
        assert len(simulation.snapshot()["vehicles"]) == 50
    finally:
        simulation.close()


@pytest.mark.parametrize("lanes_count", [2, 3, 4, 5])
@pytest.mark.parametrize(
    ("side", "closed_lane", "target_lane", "merge_action"),
    [
        ("left", 0, 1, "LANE_RIGHT"),
        ("right", -1, -2, "LANE_LEFT"),
    ],
)
def test_all_supported_road_widths_preserve_authoritative_left_right_semantics(
    lanes_count: int,
    side: str,
    closed_lane: int,
    target_lane: int,
    merge_action: str,
) -> None:
    simulation = ConstructionSimulation.from_config(
        empty_traffic_config(lanes_count=lanes_count, side=side)
    )

    snapshot = simulation.snapshot()
    expected_closed = closed_lane if closed_lane >= 0 else lanes_count + closed_lane
    expected_target = target_lane if target_lane >= 0 else lanes_count + target_lane
    assert snapshot["ego"]["lane_index"] == expected_closed
    assert snapshot["construction"]["target_lane_index"] == expected_target
    assert snapshot["construction"]["authoritative_merge_action"] == merge_action
    assert {item["lane_index"] for item in snapshot["objects"] if item["solid"]} == {
        expected_closed
    }
    assert all(
        item["lane_index"] != expected_target
        for item in snapshot["objects"]
        if item["solid"]
    )


def test_boundary_lane_action_is_ignored_while_authoritative_merge_action_moves_target() -> None:
    right = ConstructionSimulation.from_config(empty_traffic_config(side="right"))

    ignored = right.step("LANE_RIGHT")
    assert ignored["ego"]["target_lane_index"] == 2
    moved = right.step("LANE_LEFT")
    assert moved["ego"]["target_lane_index"] == 1


def test_step_returns_only_python_computed_state_reward_ttc_and_status() -> None:
    simulation = ConstructionSimulation.from_config(load_preset("normal"))

    before = simulation.snapshot()
    after = simulation.step("IDLE")

    assert after["authority"] == "python"
    assert after["ego"]["position_m"]["x"] > before["ego"]["position_m"]["x"]
    assert set(after["reward"]["components"]) == {
        "collision",
        "speed",
        "safe_lane",
        "lane_change",
        "merge_success",
        "ttc",
        "comfort",
    }
    assert isinstance(after["reward"]["total"], float)
    assert after["safety"]["collision"] is False
    assert after["safety"]["min_ttc_s"] is None or after["safety"]["min_ttc_s"] >= 0
    assert after["status"] == {
        "terminated": False,
        "truncated": False,
        "termination_reason": None,
    }


def test_repeated_actions_produce_a_merge_success_terminal_reason() -> None:
    config = empty_traffic_config(side="right", seed=81)
    config["ego"]["initial_position_m"] = 160.0
    simulation = ConstructionSimulation.from_config(config)

    snapshot = simulation.step("LANE_LEFT")
    for _ in range(150):
        snapshot = simulation.step("IDLE")
        if snapshot["status"]["terminated"] or snapshot["status"]["truncated"]:
            break

    assert snapshot["status"] == {
        "terminated": True,
        "truncated": False,
        "termination_reason": "merge_success",
    }
    assert snapshot["reward"]["components"]["merge_success"] == 1.0
    assert snapshot["reward"]["components"]["safe_lane"] == 1.0


def test_passing_in_any_open_lane_receives_the_success_reward() -> None:
    config = empty_traffic_config(side="right", seed=181)
    config["ego"]["initial_position_m"] = 160.0
    simulation = ConstructionSimulation.from_config(config)
    try:
        snapshot = simulation.step("LANE_LEFT")
        for _ in range(10):
            if snapshot["ego"]["lane_index"] == 1:
                break
            snapshot = simulation.step("IDLE")
        snapshot = simulation.step("LANE_LEFT")
        for _ in range(150):
            snapshot = simulation.step("IDLE")
            if snapshot["status"]["terminated"] or snapshot["status"]["truncated"]:
                break

        assert snapshot["ego"]["lane_index"] == 0
        assert snapshot["status"]["termination_reason"] == "merge_success"
        assert snapshot["reward"]["components"]["merge_success"] == 1.0
    finally:
        simulation.close()


def test_safe_lane_reward_is_authoritative_and_total_is_mechanically_weighted() -> None:
    config = empty_traffic_config(side="right", seed=83)
    simulation = ConstructionSimulation.from_config(config)
    try:
        initial = simulation.snapshot()
        assert initial["reward"]["components"]["safe_lane"] == 0.0
        after = simulation.step("LANE_LEFT")
        for _ in range(10):
            if after["ego"]["lane_index"] == after["construction"]["target_lane_index"]:
                break
            after = simulation.step("IDLE")
        assert after["reward"]["components"]["safe_lane"] == 1.0
        expected = sum(
            config["reward"][name] * value
            for name, value in after["reward"]["components"].items()
        )
        assert after["reward"]["total"] == pytest.approx(expected)
    finally:
        simulation.close()


def test_staying_in_the_closed_lane_reaches_the_physical_barrier_as_a_collision() -> None:
    config = empty_traffic_config(side="right", seed=82)
    config["ego"]["initial_position_m"] = 220.0
    config["ego"]["initial_speed_mps"] = 24.0
    simulation = ConstructionSimulation.from_config(config)

    snapshot = simulation.snapshot()
    for _ in range(50):
        snapshot = simulation.step("IDLE")
        if snapshot["status"]["terminated"]:
            break

    assert snapshot["status"] == {
        "terminated": True,
        "truncated": False,
        "termination_reason": "collision",
    }
    assert snapshot["safety"]["collision"] is True
    assert snapshot["reward"]["components"]["collision"] == 1.0
    assert snapshot["ego"]["crashed"] is True


def test_dangerous_cut_in_produces_a_real_highwayenv_collision() -> None:
    simulation = ConstructionSimulation.from_config(load_preset("dangerous-cut-in"))
    try:
        snapshot = simulation.snapshot()
        for _ in range(100):
            snapshot = simulation.step("IDLE")
            if snapshot["status"]["terminated"]:
                break
        assert snapshot["status"]["termination_reason"] == "collision"
        assert snapshot["safety"]["collision"] is True
        assert snapshot["reward"]["components"]["collision"] == 1.0
    finally:
        simulation.close()


def test_qualified_rule_escapes_stopped_traffic_in_the_high_density_aggressive_scenario() -> None:
    config = load_preset("aggressive")
    config["road"]["lanes_count"] = 5
    config["traffic"]["vehicles_count"] = 50
    simulation = ConstructionSimulation.from_config(config)
    policy = QualifiedRulePolicy()
    try:
        snapshot = simulation.snapshot()
        issued_merge_actions = 0
        for _ in range(300):
            decision = policy.decide(snapshot)
            issued_merge_actions += int(decision.action == "LANE_RIGHT")
            snapshot = simulation.step(decision.action)
            if snapshot["status"]["terminated"] or snapshot["status"]["truncated"]:
                break

        assert issued_merge_actions == 1
        assert snapshot["status"]["termination_reason"] == "merge_success"
        assert snapshot["safety"]["collision"] is False
        assert snapshot["ego"]["lane_index"] == snapshot["construction"]["target_lane_index"]
    finally:
        simulation.close()


def test_qualified_rule_completes_the_five_lane_dense_ui_configuration() -> None:
    config = load_preset("normal")
    config["seed"] = 101
    config["road"]["lanes_count"] = 5
    config["construction"].update(
        closed_lane_index=4,
        zone_start_m=260.0,
        zone_end_m=440.0,
    )
    config["construction"].pop("target_lane_index", None)
    config["ego"]["initial_speed_mps"] = 22.0
    config["traffic"].update(
        vehicles_count=50,
        density=2.5,
        min_speed_mps=18.0,
        max_speed_mps=27.0,
        aggressive_fraction=0.15,
    )
    simulation = ConstructionSimulation.from_config(config)
    policy = QualifiedRulePolicy()
    try:
        initial = simulation.snapshot()
        assert not any(
            vehicle["lane_index"] == 4 and vehicle["position_m"]["x"] < 260.0
            for vehicle in initial["vehicles"]
        )

        snapshot = initial
        for _ in range(300):
            decision = policy.decide(snapshot)
            snapshot = simulation.step(decision.action)
            if snapshot["status"]["terminated"] or snapshot["status"]["truncated"]:
                break

        assert snapshot["status"]["termination_reason"] == "merge_success"
        assert snapshot["safety"]["collision"] is False
    finally:
        simulation.close()


def test_density_controls_longitudinal_traffic_concentration() -> None:
    def initial_approach_distances(density: float) -> list[float]:
        config = load_preset("normal")
        config["traffic"].update(vehicles_count=12, density=density)
        simulation = ConstructionSimulation.from_config(config)
        try:
            snapshot = simulation.snapshot()
            zone_start = snapshot["construction"]["zone_start_m"]
            return [
                zone_start - vehicle["position_m"]["x"]
                for vehicle in snapshot["vehicles"]
                if vehicle["position_m"]["x"] < zone_start
            ]
        finally:
            simulation.close()

    sparse = initial_approach_distances(0.5)
    dense = initial_approach_distances(2.5)

    assert len(sparse) == len(dense) == 6
    assert sum(dense) / len(dense) < sum(sparse) / len(sparse)


def test_duration_boundary_is_a_timeout_truncation_only() -> None:
    config = empty_traffic_config(seed=84)
    config["simulation"]["duration_s"] = 0.2
    simulation = ConstructionSimulation.from_config(config)
    try:
        snapshot = simulation.step("IDLE")
        assert snapshot["status"] == {
            "terminated": False,
            "truncated": True,
            "termination_reason": "timeout",
        }
        assert snapshot["safety"]["collision"] is False
    finally:
        simulation.close()


@pytest.mark.parametrize("preset", ["normal", "congested", "aggressive", "dangerous-cut-in"])
def test_background_traffic_enters_and_influences_the_core_decision_region(preset: str) -> None:
    config = load_preset(preset)
    simulation = ConstructionSimulation.from_config(config)
    policy = QualifiedRulePolicy()
    policy.reset()
    participants: set[str] = set()
    target_lane_participants: set[str] = set()
    observed_finite_gap = False
    try:
        snapshot = simulation.snapshot()
        core_start = snapshot["construction"]["zone_start_m"] - max(
            config["construction"]["warning_offsets_m"]
        )
        core_end = snapshot["construction"]["zone_end_m"]
        target_lane = snapshot["construction"]["target_lane_index"]
        for _ in range(500):
            for vehicle in snapshot["vehicles"]:
                if core_start <= vehicle["position_m"]["x"] <= core_end:
                    participants.add(vehicle["vehicle_id"])
                    if vehicle["lane_index"] == target_lane:
                        target_lane_participants.add(vehicle["vehicle_id"])
            if snapshot["status"]["terminated"] or snapshot["status"]["truncated"]:
                break
            decision = policy.decide(snapshot)
            observed_finite_gap |= (
                decision.explanation["front_gap_m"] is not None
                or decision.explanation["rear_gap_m"] is not None
            )
            snapshot = simulation.step(decision.action)
        assert participants
        assert target_lane_participants
        assert observed_finite_gap
    finally:
        simulation.close()


def test_same_complete_config_and_actions_reproduce_every_authoritative_snapshot() -> None:
    first = ConstructionSimulation.from_config(load_preset("normal"))
    second = ConstructionSimulation.from_config(load_preset("normal"))
    actions = ["IDLE", "FASTER", "LANE_LEFT", "IDLE", "SLOWER"]

    assert first.snapshot() == second.snapshot()
    assert [first.step(action) for action in actions] == [
        second.step(action) for action in actions
    ]


def test_each_preset_has_a_real_distinct_behavior_probe() -> None:
    normal = ConstructionSimulation.from_config(load_preset("normal")).snapshot()
    congested = ConstructionSimulation.from_config(load_preset("congested")).snapshot()
    aggressive = ConstructionSimulation.from_config(load_preset("aggressive")).snapshot()
    cut_in = ConstructionSimulation.from_config(load_preset("dangerous-cut-in")).snapshot()

    assert len(normal["vehicles"]) == 10
    assert len(congested["vehicles"]) == 24
    assert max(vehicle["speed_mps"] for vehicle in congested["vehicles"]) <= 18.0
    assert min(vehicle["speed_mps"] for vehicle in aggressive["vehicles"]) >= 24.0
    event_vehicles = [vehicle for vehicle in cut_in["vehicles"] if vehicle["scenario_event"]]
    assert len(event_vehicles) == 1
    assert event_vehicles[0]["vehicle_id"] == "event-dangerous-cut-in"
    assert event_vehicles[0]["target_lane_index"] == cut_in["construction"]["target_lane_index"]


def test_action_mapping_is_the_complete_highwayenv_discrete_meta_action_contract() -> None:
    assert ACTIONS == {
        0: "LANE_LEFT",
        1: "IDLE",
        2: "LANE_RIGHT",
        3: "FASTER",
        4: "SLOWER",
    }
