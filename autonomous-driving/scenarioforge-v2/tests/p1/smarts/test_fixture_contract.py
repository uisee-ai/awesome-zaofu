from __future__ import annotations

from pathlib import Path

from scenarioforge.authoring import CapabilityStatus, validate_authoring_spec
from scenarioforge.core import canonical_digest, strict_loads


FIXTURE_ROOT = Path("tests/fixtures/p1/scenarios")
SCENARIOS = {
    "competitive_lane_change": {
        "actors": ["ego", "challenger", "traffic"],
        "events": ["challenger-claims-gap"],
        "capabilities": [
            "actor.vehicle",
            "event.time-trigger",
            "road.corridor",
            "route.stable-id",
        ],
    },
    "cross_traffic_red_light_violation": {
        "actors": ["ego", "violator", "traffic"],
        "events": ["cross-traffic-runs-red"],
        "capabilities": [
            "actor.vehicle",
            "event.time-trigger",
            "road.intersection",
            "route.stable-id",
        ],
    },
    "highway_merge": {
        "actors": ["ego", "front", "rear", "traffic"],
        "events": ["ego-selects-gap"],
        "capabilities": [
            "actor.vehicle",
            "event.time-trigger",
            "road.merge",
            "route.stable-id",
        ],
    },
    "pedestrian_red_light_crossing": {
        "actors": ["ego", "pedestrian", "traffic"],
        "events": ["pedestrian-crosses-red"],
        "capabilities": [
            "actor.pedestrian",
            "actor.vehicle",
            "event.time-trigger",
            "road.intersection",
            "route.stable-id",
        ],
    },
    "unprotected_left_turn": {
        "actors": ["ego", "oncoming", "traffic"],
        "events": ["ego-yields", "ego-commits-left"],
        "capabilities": [
            "actor.vehicle",
            "event.time-trigger",
            "road.intersection",
            "route.stable-id",
        ],
    },
}


def _read(path: Path):
    return strict_loads(path.read_bytes())


def test_five_canonical_specs_are_complete_valid_and_exact_golden_fixtures() -> None:
    scenario_paths = sorted(
        path for path in FIXTURE_ROOT.glob("*.json") if not path.name.startswith("_")
    )
    assert [path.stem for path in scenario_paths] == sorted(SCENARIOS)
    manifest = _read(FIXTURE_ROOT / "_digests.json")
    assert manifest == {
        "schema_version": "scenarioforge.p1-scenario-digests/v1",
        "canonical_digests": {
            scenario_id: canonical_digest(_read(FIXTURE_ROOT / f"{scenario_id}.json"))
            for scenario_id in sorted(SCENARIOS)
        },
    }

    for scenario_id, expected in SCENARIOS.items():
        spec = _read(FIXTURE_ROOT / f"{scenario_id}.json")
        report = validate_authoring_spec(spec)
        assert report.overall_status is CapabilityStatus.EXACT, report.to_dict()
        assert set(spec) == {
            "schema_version",
            "title",
            "description",
            "seed",
            "road",
            "routes",
            "actors",
            "static_obstacles",
            "environment",
            "events",
            "constraints",
            "parameters",
            "policy",
            "required_capabilities",
        }
        assert [actor["id"] for actor in spec["actors"]] == expected["actors"]
        assert [event["id"] for event in spec["events"]] == expected["events"]
        assert spec["required_capabilities"] == expected["capabilities"]
        assert spec["road"]["coordinate_system"] == "right-handed-x-forward-y-left"
        assert spec["road"]["units"] == {
            "distance": "m",
            "speed": "m/s",
            "heading": "deg",
            "time": "s",
        }


def test_backend_matrix_truthfully_marks_every_scenario_and_never_implies_equivalence() -> None:
    matrix = _read(Path("tests/fixtures/p1/backend-capability-matrix.json"))
    assert set(matrix) == {"schema_version", "backends", "scenarios"}
    assert matrix["schema_version"] == "scenarioforge.backend-capability-matrix/v1"
    assert matrix["backends"] == [
        {"backend_id": "scenarioforge.smarts", "version": "2.0.1"},
        {"backend_id": "scenarioforge.metadrive", "version": "0.4.3"},
    ]
    assert [row["scenario_id"] for row in matrix["scenarios"]] == sorted(SCENARIOS)
    for row in matrix["scenarios"]:
        assert set(row) == {"scenario_id", "scenario_digest", "backends"}
        assert row["scenario_digest"] == canonical_digest(
            _read(FIXTURE_ROOT / f"{row['scenario_id']}.json")
        )
        assert row["backends"]["scenarioforge.smarts"] == {
            "status": "exact",
            "executable": True,
            "reason": "canonical semantics are implemented by the locked SMARTS adapter",
        }
        metadrive = row["backends"]["scenarioforge.metadrive"]
        assert set(metadrive) == {"status", "executable", "reason"}
        assert metadrive["status"] in {"exact", "lossy", "unsupported"}
        assert metadrive["executable"] is (metadrive["status"] == "exact")
        assert metadrive["reason"]
    assert "equivalent" not in repr(matrix).lower()
