from __future__ import annotations

from dataclasses import dataclass

import pytest

from scenarioforge.web.api import ScenarioForgeAPI
from scenarioforge.web.catalog import scenario_catalog, scenario_metadata
from scenarioforge.web.coordinator import (
    ExecutionState,
    InvalidIdentifierError,
    RunReference,
    UnknownRunError,
    UnknownScenarioError,
)
from scenarioforge.web.evidence import UnknownArtifactError


CATALOG = {
    "schema_version": "scenarioforge.scenario-catalog/v1",
    "scenarios": [
        {
            "scenario_id": "brake_lead",
            "display_name": "Lead Vehicle Emergency Braking",
            "description": "An ego vehicle follows a lead vehicle that brakes at a fixed tick.",
        }
    ],
}


@dataclass
class FakeEvidenceReader:
    terminal_calls: list[tuple[str, str]]
    playback_calls: list[tuple[str, str]]

    def terminal(self, run_id: str, attempt_id: str) -> dict[str, object]:
        self.terminal_calls.append((run_id, attempt_id))
        return {
            "schema_version": "scenarioforge.terminal-evidence/v1",
            "run_id": run_id,
            "attempt_id": attempt_id,
            "status": "success",
        }

    def playback(self, run_id: str, attempt_id: str) -> dict[str, object]:
        self.playback_calls.append((run_id, attempt_id))
        return {
            "schema_version": "scenarioforge.playback/v1",
            "run_id": run_id,
            "attempt_id": attempt_id,
        }


class FakeCoordinator:
    def __init__(self) -> None:
        self.reference_value = RunReference(
            schema_version="scenarioforge.run-reference/v1",
            scenario_id="brake_lead",
            run_id="run-safe-0001",
            attempt_id="attempt-0001",
            published_ref="published/run-safe-0001/attempt-0001",
        )
        self.state: ExecutionState | None = None
        self.start_calls: list[tuple[str, str]] = []

    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference:
        if scenario_id != "brake_lead":
            raise UnknownScenarioError("unknown scenario_id")
        self.start_calls.append((scenario_id, idempotency_key))
        return self.reference_value

    def active_state(self, run_id: str) -> ExecutionState | None:
        if run_id != self.reference_value.run_id:
            raise UnknownRunError("unknown run_id")
        return self.state

    def reference(self, run_id: str) -> RunReference:
        if run_id != self.reference_value.run_id:
            raise UnknownRunError("unknown run_id")
        return self.reference_value


def test_catalog_is_an_exact_registered_metadata_projection() -> None:
    assert scenario_catalog() == CATALOG
    assert scenario_metadata("brake_lead") == CATALOG["scenarios"][0]

    public_text = repr(CATALOG)
    assert "brake-lead-happy" not in public_text
    assert "examples/" not in public_text
    assert "ScenarioSpec" not in public_text
    assert "seed" not in public_text.lower()


@pytest.mark.parametrize(
    "scenario_id",
    ("unknown", "../brake_lead", "/tmp/brake_lead", "brake_lead/../../secret"),
)
def test_catalog_unknown_and_path_like_identifiers_fail_closed(scenario_id: str) -> None:
    error = InvalidIdentifierError if scenario_id != "unknown" else UnknownScenarioError
    with pytest.raises(error) as raised:
        scenario_metadata(scenario_id)

    assert "/tmp" not in str(raised.value)
    assert "examples" not in str(raised.value)


def test_business_api_forwards_only_registered_start_and_active_state() -> None:
    coordinator = FakeCoordinator()
    evidence = FakeEvidenceReader([], [])
    api = ScenarioForgeAPI(coordinator=coordinator, evidence=evidence)

    assert api.list_scenarios() == CATALOG
    assert api.start_run("brake_lead", idempotency_key="request-0001") == (
        coordinator.reference_value.to_dict()
    )
    assert coordinator.start_calls == [("brake_lead", "request-0001")]

    coordinator.state = ExecutionState(
        schema_version="scenarioforge.execution-state/v1",
        scenario_id="brake_lead",
        run_id="run-safe-0001",
        attempt_id="attempt-0001",
        state="running",
    )
    assert api.run_status("run-safe-0001") == coordinator.state.to_dict()
    assert evidence.terminal_calls == []


def test_business_api_uses_immutable_reader_after_active_state_ends() -> None:
    coordinator = FakeCoordinator()
    evidence = FakeEvidenceReader([], [])
    api = ScenarioForgeAPI(coordinator=coordinator, evidence=evidence)

    assert api.run_status("run-safe-0001") == {
        "schema_version": "scenarioforge.terminal-evidence/v1",
        "run_id": "run-safe-0001",
        "attempt_id": "attempt-0001",
        "status": "success",
    }
    assert evidence.terminal_calls == [("run-safe-0001", "attempt-0001")]

    assert api.run_artifact("run-safe-0001", "trajectory") == {
        "schema_version": "scenarioforge.playback/v1",
        "run_id": "run-safe-0001",
        "attempt_id": "attempt-0001",
    }
    assert evidence.playback_calls == [("run-safe-0001", "attempt-0001")]

    with pytest.raises(UnknownArtifactError, match="unknown artifact key"):
        api.run_artifact("run-safe-0001", "../../run_manifest.json")
    assert evidence.playback_calls == [("run-safe-0001", "attempt-0001")]
