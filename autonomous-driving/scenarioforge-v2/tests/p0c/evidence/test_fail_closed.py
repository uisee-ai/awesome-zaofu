from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.core import canonical_bytes
from scenarioforge.web.evidence import EvidenceValidationError, PublishedEvidenceReader

from .conftest import (
    read_json,
    resign_controls,
    rewrite_artifact,
    rewrite_raw_artifact,
)


def _partial(published: Path) -> None:
    index = read_json(published / "artifact_index.json")
    entry = next(
        item for item in index["artifacts"] if item["path"] == "output/trajectory.json"
    )
    entry["validation"] = "verified_partial"
    resign_controls(published, index)


def _digest_mismatch(published: Path) -> None:
    trajectory = published / "output" / "trajectory.json"
    trajectory.chmod(0o600)
    trajectory.write_bytes(trajectory.read_bytes() + b" ")


def _oversize(published: Path) -> None:
    index = read_json(published / "artifact_index.json")
    entry = next(
        item for item in index["artifacts"] if item["path"] == "output/trajectory.json"
    )
    entry["size_bytes"] = 10_485_761
    resign_controls(published, index)


def _duplicate_json_key(published: Path) -> None:
    rewrite_raw_artifact(
        published,
        "output/events.json",
        b'[{"schema_version":"scenarioforge.event/v2",'
        b'"schema_version":"scenarioforge.event/v2"}]',
    )


def _non_finite(published: Path) -> None:
    payload = read_json(published / "output" / "trajectory.json")
    encoded = canonical_bytes(payload).replace(
        b'"speed_mps":21.0', b'"speed_mps":NaN', 1
    )
    rewrite_raw_artifact(published, "output/trajectory.json", encoded)


def _participant_mismatch(published: Path) -> None:
    def mutate(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        value[0]["participant_id"] = "intruder"
        return value

    rewrite_artifact(published, "output/trajectory.json", mutate)


def _tick_gap(published: Path) -> None:
    def mutate(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for point in value:
            if point["tick"] >= 1:
                point["tick"] += 1
        return value

    rewrite_artifact(published, "output/trajectory.json", mutate)


def _missing_field(published: Path) -> None:
    def mutate(value: dict[str, Any]) -> dict[str, Any]:
        del value["metric_values"][0]["raw_evidence_value"]
        return value

    rewrite_artifact(published, "output/metrics.json", mutate)


def _terminal_identity_mismatch(published: Path) -> None:
    def mutate(value: dict[str, Any]) -> dict[str, Any]:
        value["attempt_id"] = "attempt-other"
        return value

    rewrite_artifact(published, "output/worker_result.json", mutate)


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(_partial, id="partial"),
        pytest.param(_digest_mismatch, id="digest-mismatch"),
        pytest.param(_oversize, id="oversize"),
        pytest.param(_duplicate_json_key, id="duplicate-json-key"),
        pytest.param(_non_finite, id="non-finite"),
        pytest.param(_participant_mismatch, id="participant-mismatch"),
        pytest.param(_tick_gap, id="tick-gap"),
        pytest.param(_missing_field, id="missing-field"),
        pytest.param(_terminal_identity_mismatch, id="terminal-identity-mismatch"),
    ],
)
def test_v2_projection_and_playback_fail_closed_for_untrusted_evidence(
    v2_publication: Path,
    corrupt: Callable[[Path], None],
) -> None:
    corrupt(v2_publication)
    reader = PublishedEvidenceReader(publish_root=v2_publication.parents[1])

    with pytest.raises(EvidenceValidationError):
        reader.terminal("run-v2-evidence", "attempt-0001")
    with pytest.raises(EvidenceValidationError):
        reader.playback("run-v2-evidence", "attempt-0001")
