from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.core import canonical_digest, strict_loads
from scenarioforge.runtime.smarts_worker import (
    CANONICAL_SMARTS_SCENARIOS,
    publish_smarts_evidence,
    run_canonical_smarts_scenario,
)


FIXTURE_ROOT = Path("tests/fixtures/p1/scenarios")


@pytest.mark.parametrize("scenario_id", CANONICAL_SMARTS_SCENARIOS)
def test_all_five_canonical_scenarios_execute_exact_on_real_smarts(
    scenario_id: str,
    tmp_path: Path,
) -> None:
    evidence = run_canonical_smarts_scenario(
        scenario_id,
        run_id=f"real-{scenario_id}",
        max_episode_steps=220,
    )
    spec = strict_loads((FIXTURE_ROOT / f"{scenario_id}.json").read_bytes())

    assert evidence["schema_version"] == "scenarioforge.smarts-run-evidence/v1"
    assert evidence["backend"] == {
        "id": "scenarioforge.smarts",
        "version": "2.0.1",
    }
    assert evidence["scenario_digest"] == canonical_digest(spec)
    assert evidence["terminal_state"]["status"] == "completed"
    assert evidence["terminal_state"]["reason"] == "goal"
    assert evidence["metrics"]["completed_steps"] >= 120
    assert {event["event_id"] for event in evidence["events"]}.issuperset(
        event["id"] for event in spec["events"]
    )
    assert {point["agent_id"] for point in evidence["trajectory"]}.issuperset(
        actor["id"] for actor in spec["actors"]
    )

    tracks = {
        actor_id: [
            point
            for point in evidence["trajectory"]
            if point["agent_id"] == actor_id
        ]
        for actor_id in {point["agent_id"] for point in evidence["trajectory"]}
    }
    if scenario_id == "competitive_lane_change":
        assert abs(
            tracks["challenger"][-1]["position_m"][1]
            - tracks["challenger"][0]["position_m"][1]
        ) > 2.5
    elif scenario_id == "cross_traffic_red_light_violation":
        assert (
            tracks["violator"][0]["position_m"][1]
            - tracks["violator"][-1]["position_m"][1]
        ) > 100.0
    elif scenario_id == "highway_merge":
        assert (
            tracks["ego"][-1]["position_m"][1]
            - tracks["ego"][0]["position_m"][1]
        ) > 25.0
    elif scenario_id == "pedestrian_red_light_crossing":
        assert (
            tracks["pedestrian"][-1]["position_m"][0]
            - tracks["pedestrian"][0]["position_m"][0]
        ) > 15.0
    elif scenario_id == "unprotected_left_turn":
        assert abs(tracks["ego"][-1]["heading_deg"] - 90.0) < 5.0
        assert (
            tracks["ego"][-1]["position_m"][1]
            - tracks["ego"][0]["position_m"][1]
        ) > 50.0

    output = publish_smarts_evidence(evidence, tmp_path)
    assert strict_loads(output.read_bytes()) == evidence


def test_real_scenario_assets_are_content_bound_and_matrix_status_is_truthful() -> None:
    manifest = strict_loads(Path("assets/p1/smarts/asset-manifest.json").read_bytes())
    matrix = strict_loads(
        Path("tests/fixtures/p1/backend-capability-matrix.json").read_bytes()
    )

    assert manifest["schema_version"] == "scenarioforge.smarts-assets/v1"
    assert sorted(manifest["scenarios"]) == list(CANONICAL_SMARTS_SCENARIOS)
    for scenario_id, asset in manifest["scenarios"].items():
        assert set(asset) == {
            "asset_id",
            "seed",
            "scenario_digest",
            "policy_digest",
            "parameters_digest",
            "map_dir",
            "map_sha256",
            "traffic_file",
            "traffic_sha256",
            "participants",
            "missions",
            "lane_aliases",
            "events",
            "default_actions",
            "external_actors",
        }
        row = next(
            item for item in matrix["scenarios"] if item["scenario_id"] == scenario_id
        )
        assert row["backends"]["scenarioforge.smarts"] == {
            "status": "exact",
            "executable": True,
            "reason": "canonical semantics are implemented by the locked SMARTS adapter",
        }
