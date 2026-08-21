from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.web.api import ScenarioForgeAPI
from scenarioforge.web.catalog import scenario_catalog, scenario_metadata
from scenarioforge.web.coordinator import (
    InvalidIdentifierError,
    RunCoordinator,
    UnknownScenarioError,
)


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_CATALOG = {
    "schema_version": "scenarioforge.scenario-catalog/v2",
    "default_scenario_id": "brake_lead",
    "scenarios": [
        {
            "scenario_id": "brake_lead",
            "display_name": "Lead Vehicle Emergency Braking",
            "description": (
                "Ego follows a lead vehicle that brakes suddenly on a straight road."
            ),
            "target_outcome": "near_miss",
            "participants": [
                {"id": "ego", "role": "ego", "label": "Following vehicle"},
                {"id": "lead", "role": "social", "label": "Lead vehicle"},
            ],
            "routes": [
                {
                    "participant_id": "ego",
                    "summary": "Continue along the following lane behind the lead vehicle.",
                },
                {
                    "participant_id": "lead",
                    "summary": "Continue along the same lane while slowing sharply.",
                },
            ],
            "danger": "The lead vehicle brakes at tick 35 while ego is following closely.",
            "expected_reaction": "Ego brakes at tick 40 to avoid the lead vehicle.",
            "success_meaning": "Both vehicles finish their routes without a collision.",
            "failure_meaning": "A collision, boundary violation, or route timeout occurs.",
        },
        {
            "scenario_id": "construction_merge",
            "display_name": "Construction Lane Closure",
            "description": (
                "Ego starts in a closing lane and must merge into the open lane."
            ),
            "target_outcome": "safe_pass",
            "participants": [
                {"id": "ego", "role": "ego", "label": "Merging vehicle"},
                {"id": "social", "role": "social", "label": "Open-lane vehicle"},
            ],
            "routes": [
                {
                    "participant_id": "ego",
                    "summary": "Move from the closing lane into the open lane.",
                },
                {
                    "participant_id": "social",
                    "summary": "Continue straight in the open lane.",
                },
            ],
            "danger": "The closing lane reaches a construction taper between 60 m and 90 m.",
            "expected_reaction": "Ego selects a gap and merges before entering the closure.",
            "success_meaning": "Ego reaches the open lane and passes the construction zone.",
            "failure_meaning": (
                "A collision, boundary violation, closed-region entry, or timeout occurs."
            ),
        },
        {
            "scenario_id": "dangerous_cut_in",
            "display_name": "Dangerous Adjacent-Lane Cut-In",
            "description": (
                "A nearby vehicle cuts abruptly into ego's lane inside a conflict area."
            ),
            "target_outcome": "collision_failure",
            "participants": [
                {"id": "ego", "role": "ego", "label": "Main-lane vehicle"},
                {"id": "cutter", "role": "social", "label": "Cut-in vehicle"},
            ],
            "routes": [
                {
                    "participant_id": "ego",
                    "summary": "Continue straight in the ego lane.",
                },
                {
                    "participant_id": "cutter",
                    "summary": "Move from the adjacent lane into the ego lane.",
                },
            ],
            "danger": "The cut-in begins at tick 5 in the 35 m to 80 m conflict area.",
            "expected_reaction": "Observe the forced cut-in and the resulting collision evidence.",
            "success_meaning": "The expected collision failure is recorded with complete evidence.",
            "failure_meaning": "The run diverges from the frozen cut-in or lacks complete evidence.",
        },
        {
            "scenario_id": "highway_merge",
            "display_name": "Highway Entrance-Ramp Merge",
            "description": (
                "Ego enters from a ramp and must merge between two mainline vehicles."
            ),
            "target_outcome": "safe_pass",
            "participants": [
                {"id": "ego", "role": "ego", "label": "Ramp vehicle"},
                {"id": "front", "role": "social", "label": "Front mainline vehicle"},
                {"id": "rear", "role": "social", "label": "Rear mainline vehicle"},
            ],
            "routes": [
                {
                    "participant_id": "ego",
                    "summary": "Follow the ramp and enter the right mainline lane.",
                },
                {
                    "participant_id": "front",
                    "summary": "Continue ahead in the right mainline lane.",
                },
                {
                    "participant_id": "rear",
                    "summary": "Continue behind the available merge gap.",
                },
            ],
            "danger": "The ramp and mainline overlap in the 35 m to 80 m merge area.",
            "expected_reaction": "Ego observes both mainline vehicles and selects the gap.",
            "success_meaning": "Ego reaches the right mainline lane without a collision.",
            "failure_meaning": (
                "A collision, route departure, wrong-lane entry, or timeout occurs."
            ),
        },
        {
            "scenario_id": "unprotected_left_turn",
            "display_name": "Unprotected Left Turn",
            "description": (
                "Ego turns left across the path of an oncoming through vehicle."
            ),
            "target_outcome": "near_miss",
            "participants": [
                {"id": "ego", "role": "ego", "label": "Left-turning vehicle"},
                {"id": "oncoming", "role": "social", "label": "Oncoming vehicle"},
            ],
            "routes": [
                {
                    "participant_id": "ego",
                    "summary": "Yield, cross the intersection, and reach the north exit.",
                },
                {
                    "participant_id": "oncoming",
                    "summary": "Travel straight through the intersection to the west exit.",
                },
            ],
            "danger": "Both routes cross in the left-turn conflict zone at the intersection.",
            "expected_reaction": "Ego yields first, then commits to the turn after oncoming clears.",
            "success_meaning": "Ego yields and completes the left-turn route without collision.",
            "failure_meaning": (
                "A collision, boundary violation, wrong route, or timeout occurs."
            ),
        },
    ],
}


class RecordingApplication:
    def __init__(self) -> None:
        self.scenario_paths: list[Path] = []

    def run_single(
        self,
        scenario_path: Path | str,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: int,
    ) -> object:
        self.scenario_paths.append(Path(scenario_path))
        return object()


class IdleEvidence:
    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]:
        raise AssertionError("terminal evidence was not requested")

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        raise AssertionError("playback evidence was not requested")


def test_p0c_catalog_is_an_exact_bounded_presentation_projection() -> None:
    catalog = scenario_catalog(profile="p0c")

    assert catalog == EXPECTED_CATALOG
    assert scenario_metadata("brake_lead", profile="p0c") == catalog["scenarios"][0]
    assert catalog["scenarios"][0]["target_outcome"] == "near_miss"

    forbidden_keys = {
        "path",
        "url",
        "spec",
        "raw_spec",
        "source",
        "secret",
        "executable",
        "seed",
        "policy",
    }

    def assert_bounded(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            assert len(value) <= 12
            for child in value.values():
                assert_bounded(child)
        elif isinstance(value, list):
            assert len(value) <= 5
            for child in value:
                assert_bounded(child)
        elif isinstance(value, str):
            assert len(value) <= 240
            assert "<script" not in value.lower()

    assert_bounded(catalog)


def test_p0c_catalog_returns_defensive_copies_and_fails_closed() -> None:
    first = scenario_catalog(profile="p0c")
    first["scenarios"][0]["display_name"] = "tampered"

    assert scenario_catalog(profile="p0c") == EXPECTED_CATALOG
    for scenario_id in (
        "unknown",
        "../brake_lead",
        "/tmp/brake_lead",
        "https://example.invalid/scenario",
        "<script>alert(1)</script>",
    ):
        expected_error = (
            UnknownScenarioError
            if scenario_id == "unknown"
            else InvalidIdentifierError
        )
        with pytest.raises(expected_error):
            scenario_metadata(scenario_id, profile="p0c")


def test_p0c_coordinator_runs_only_the_five_registered_project_fixtures(
    tmp_path: Path,
) -> None:
    application = RecordingApplication()
    coordinator = RunCoordinator(
        workspace=tmp_path,
        project_root=ROOT,
        timeout_seconds=17,
        application=application,
        catalog_profile="p0c",
    )

    for scenario in EXPECTED_CATALOG["scenarios"]:
        scenario_id = scenario["scenario_id"]
        reference = coordinator.start(
            scenario_id,
            idempotency_key=f"request-{scenario_id}",
        )
        coordinator.wait_for_terminal(reference.run_id, timeout=2)

    assert application.scenario_paths == [
        ROOT / "examples" / "p0c" / f"{scenario['scenario_id']}.json"
        for scenario in EXPECTED_CATALOG["scenarios"]
    ]
    with pytest.raises(UnknownScenarioError, match="unknown scenario_id"):
        coordinator.start("not_registered", idempotency_key="request-unknown")


def test_p0c_business_api_uses_the_five_preset_profile() -> None:
    class Coordinator:
        def start(self, scenario_id: str, *, idempotency_key: str):
            raise AssertionError("start was not requested")

    api = ScenarioForgeAPI(
        coordinator=Coordinator(),
        evidence=IdleEvidence(),
        catalog_profile="p0c",
    )

    assert api.list_scenarios() == EXPECTED_CATALOG
