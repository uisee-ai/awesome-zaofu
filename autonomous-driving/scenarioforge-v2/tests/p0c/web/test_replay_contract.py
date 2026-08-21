from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scenarioforge.web.api import ScenarioForgeAPI
from scenarioforge.web.coordinator import RunReference


ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "src" / "scenarioforge" / "web" / "static"


@dataclass
class TerminalCoordinator:
    reference_value: RunReference

    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference:
        raise AssertionError("start was not requested")

    def active_state(self, run_id: str):
        return None

    def reference(self, run_id: str) -> RunReference:
        assert run_id == self.reference_value.run_id
        return self.reference_value


class V2Evidence:
    def __init__(self) -> None:
        self.terminal_value = {
            "schema_version": "scenarioforge.terminal-evidence/v2",
            "scenario_id": "brake_lead",
            "run_id": "run-p0c-web",
            "attempt_id": "attempt-p0c-web",
            "execution_status": "completed",
            "scenario_outcome": "near_miss",
            "termination_reason": "success_predicates_satisfied",
            "terminal": True,
            "playable": True,
            "metric_projections": [
                {
                    "definition_id": f"scenarioforge.metric.{metric}/v2",
                    "metric": metric,
                    "unit": unit,
                    "participant_ids": ["ego"],
                    "topology_kinds": ["straight"],
                    "value": value,
                    "threshold": None,
                    "threshold_met": None,
                    "null_semantics": null_semantics,
                    "explanation": explanation,
                    "raw_evidence_value": value,
                    "evidence_field": evidence_field,
                }
                for metric, unit, value, null_semantics, explanation, evidence_field in (
                    (
                        "collision",
                        "boolean",
                        False,
                        "not_applicable",
                        "Whether a collision occurred.",
                        "collision",
                    ),
                    (
                        "hard_braking",
                        "m/s^2",
                        -7.0,
                        "threshold_pending_calibration",
                        "The strongest observed braking.",
                        "minimum_acceleration_mps2",
                    ),
                    (
                        "minimum_ttc",
                        "s",
                        0.8,
                        "no_closing_pair",
                        "The shortest observed time to collision.",
                        "min_ttc_s",
                    ),
                    (
                        "completion_time",
                        "s",
                        8.2,
                        "execution_incomplete",
                        "Time until the required route completed.",
                        "completion_time_s",
                    ),
                    (
                        "termination_reason",
                        "category",
                        "success_predicates_satisfied",
                        "never_null_for_terminal_run",
                        "Why execution stopped.",
                        "termination_reason",
                    ),
                )
            ],
        }
        self.playback_value = {
            "schema_version": "scenarioforge.playback/v2",
            "scenario_id": "brake_lead",
            "run_id": "run-p0c-web",
            "attempt_id": "attempt-p0c-web",
            "execution_status": "completed",
            "scenario_outcome": "near_miss",
            "termination_reason": "success_predicates_satisfied",
            "logical_ref": "published/run-p0c-web/attempt-p0c-web/output/trajectory.json",
            "trajectory_digest": "a" * 64,
            "road": {
                "schema_version": "scenarioforge.topology/v2",
                "topology_kind": "straight",
                "map_block_sequence": "S",
                "lane_width_m": 3.5,
                "coordinate_system": "right-handed-x-forward-y-left",
                "units": {
                    "distance": "m",
                    "speed": "m/s",
                    "heading": "deg",
                    "time": "tick",
                },
                "lanes": [],
                "conflict_zones": [],
            },
            "participants": [
                {"id": "ego", "role": "ego"},
                {"id": "lead", "role": "social"},
            ],
            "sample_interval_s": 0.1,
            "terminal_tick": 82,
            "events": [],
            "trajectory": [],
        }

    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]:
        assert (run_id, attempt_id) == ("run-p0c-web", "attempt-p0c-web")
        return self.terminal_value

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        assert (run_id, attempt_id) == ("run-p0c-web", "attempt-p0c-web")
        return self.playback_value


def test_business_api_preserves_complete_v2_terminal_and_playback_projection() -> None:
    reference = RunReference(
        schema_version="scenarioforge.run-reference/v1",
        scenario_id="brake_lead",
        run_id="run-p0c-web",
        attempt_id="attempt-p0c-web",
        published_ref="published/run-p0c-web/attempt-p0c-web",
    )
    evidence = V2Evidence()
    api = ScenarioForgeAPI(
        coordinator=TerminalCoordinator(reference),
        evidence=evidence,
        catalog_profile="p0c",
    )

    assert api.run_status(reference.run_id) is evidence.terminal_value
    assert api.run_artifact(reference.run_id, "trajectory") is evidence.playback_value
    assert [item["metric"] for item in evidence.terminal_value["metric_projections"]] == [
        "collision",
        "hard_braking",
        "minimum_ttc",
        "completion_time",
        "termination_reason",
    ]


def test_frontend_contract_covers_comprehension_and_recorded_replay_controls() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "scenario-select",
        "scenario-target-outcome",
        "scenario-participants",
        "scenario-routes",
        "scenario-danger",
        "scenario-reaction",
        "scenario-success",
        "scenario-failure",
        "scenario-outcome",
        "metric-projections",
        "recorded-evidence-badge",
        "previous-event",
        "next-event",
        "replay-restart",
        "simulation-time",
        "camera-mode",
    ):
        assert f'"{element_id}"' in app

    assert "const EVENT_PREROLL_TICKS = 10;" in app
    assert 'option.value = "0.25"' in app
    assert 'option.value = "0.5"' in app
    assert 'option.value = "1"' in app
    assert 'option.value = "2"' in app
    assert "terminal.metric_projections" in app
    for field in (
        "definition_id",
        "unit",
        "participant_ids",
        "value",
        "threshold",
        "null_semantics",
        "explanation",
        "raw_evidence_value",
    ):
        assert field in app

    assert "recorded immutable evidence" in app.lower()
    assert "function seekRelativeEvent(" in app
    assert "function restartReplay(" in app
    assert "function updateSimulationTime(" in app
    assert "function applyCameraMode(" in app
    assert "conflict_zones" in app
    assert "geometry.source" in app
    assert "function addRoadStrip(" in app
    assert "duration_ticks" in app
    assert "formatThreshold" in app
    assert "[object Object]" not in app
    assert "mesh.rotation.y = THREE.MathUtils.degToRad(point.heading_deg);" in app
    assert "Recorded result:" in app
    assert ".metric-projection" in css
    assert ".scenario-comprehension" in css
    assert ".road-legend" in css
    assert ".replay-status" in css

    lowered = app.lower()
    for forbidden in (
        "innerhtml",
        "insertadjacenthtml",
        "document.write",
        "eval(",
        "/stop",
        "/pause",
        "/step",
        "/reset",
        "/cancel",
        "questionnaire",
        "answer submission",
    ):
        assert forbidden not in lowered
