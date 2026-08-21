from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "tests/fixtures/p1/visual-review-schema.json"
RECEIPT_NAME = "visual-review-receipt.json"
SCENARIO_IDS = (
    "highway_merge",
    "competitive_lane_change",
    "cross_traffic_red_light_violation",
    "unprotected_left_turn",
    "pedestrian_red_light_crossing",
)
MEDIA_KINDS = ("screenshot", "video", "trace")
REVIEW_CHECKS = (
    "scenario_understandable",
    "non_box_vehicle_model",
    "vehicle_proportions",
    "right_hand_lane_placement",
    "trajectory_heading",
    "ego_follow_camera",
    "non_empty_replay",
    "identity_consistency",
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _package_digest(report_digest: str, media_digest: str) -> str:
    return hashlib.sha256(
        f"{report_digest}\n{media_digest}\n".encode("ascii")
    ).hexdigest()


def _scene_review(scenario_id: str) -> dict[str, dict[str, str]]:
    return {
        check: {
            "verdict": "passed",
            "observation": f"Independent reviewer confirmed {check} for {scenario_id}.",
        }
        for check in REVIEW_CHECKS
    }


def _golden_receipt(source_candidate_commit: str = "a" * 40) -> dict[str, object]:
    scenarios: list[dict[str, object]] = []
    scanned_refs: list[str] = []
    for index, scenario_id in enumerate(SCENARIO_IDS, start=1):
        media = {
            kind: {
                "content_ref": f"{kind}s/{scenario_id}.{_extension(kind)}",
                "content_digest": _digest(f"{scenario_id}:{kind}"),
                "capture_allowlist_digest": _digest(f"allowlist:{kind}"),
            }
            for kind in MEDIA_KINDS
        }
        scanned_refs.extend(str(item["content_ref"]) for item in media.values())
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "run_id": f"run-p1-{index:02d}",
                "attempt_id": f"attempt-p1-{index:02d}",
                "execution_snapshot_id": (
                    f"p1-smarts-runs/run-p1-{index:02d}/attempt-p1-{index:02d}"
                ),
                "execution_snapshot_digest": _digest(f"snapshot:{scenario_id}"),
                "media": media,
                "review": _scene_review(scenario_id),
            }
        )
    report_digest = _digest("candidate-media-report")
    media_digest = _digest("candidate-media")
    content_digest = _package_digest(report_digest, media_digest)
    return {
        "schema_version": "scenarioforge.visual-review-receipt/v3",
        "status": "approved",
        "source_candidate_commit": source_candidate_commit,
        "evidence_package": {
            "schema_version": "scenarioforge.candidate-evidence-package/v1",
            "report_ref": "p1-release-browser-report.json",
            "report_digest": report_digest,
            "media_digest": media_digest,
            "content_digest": content_digest,
            "content_ref": f"sha256:{content_digest}",
        },
        "review": {
            "reviewer_id": "independent-reviewer-01",
            "reviewer_role": "independent-quality-reviewer",
            "producer": "human",
            "independent": True,
            "reviewed_at": "2026-08-20T12:00:00Z",
            "decision": "approved",
            "review_task_id": "SF-P1-INDEPENDENT-VISUAL-REVIEW-023",
            "prerequisite_gate_ids": [
                "V-P1-RIGHT-HAND-TRAFFIC",
                "V-P1-DOCKER-CHROMIUM",
            ],
        },
        "scenarios": scenarios,
        "redaction_evidence": {
            "schema_version": "scenarioforge.candidate-redaction-evidence/v1",
            "status": "passed",
            "source_candidate_commit": source_candidate_commit,
            "allowlist_schema_version": "scenarioforge.artifact-allowlist/v1",
            "allowlist_digest": _digest("artifact-allowlists"),
            "scanned_encodings": ["raw", "url", "base64", "hex", "zip"],
            "scanned_artifact_refs": sorted(scanned_refs),
            "capture_layers": [
                "replay_canvas",
                "legend",
                "controls",
                "replay_dom",
                "console_sanitized",
            ],
            "absolute_path_policy": "project-relative-or-content-addressed",
            "findings": [],
        },
    }


def _extension(kind: str) -> str:
    return {"screenshot": "png", "video": "webm", "trace": "zip"}[kind]


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_visual_review_schema_is_strict_versioned_and_complete() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert list(schema) == [
        "$schema",
        "$id",
        "title",
        "type",
        "additionalProperties",
        "required",
        "properties",
        "$defs",
    ]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "status",
        "source_candidate_commit",
        "evidence_package",
        "review",
        "scenarios",
        "redaction_evidence",
    ]
    assert list(schema["$defs"]) == [
        "commit",
        "digest",
        "evidencePackage",
        "relativeRef",
        "media",
        "sceneCheck",
        "scenarioReview",
        "scenario",
        "redactionEvidence",
    ]
    assert schema["properties"]["review"]["additionalProperties"] is False
    assert schema["$defs"]["scenario"]["additionalProperties"] is False
    assert schema["$defs"]["sceneCheck"]["additionalProperties"] is False
    assert schema["$defs"]["scenarioReview"]["additionalProperties"] is False
    assert schema["$defs"]["media"]["additionalProperties"] is False
    assert schema["$defs"]["redactionEvidence"]["additionalProperties"] is False
    _validator().validate(_golden_receipt())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("unknown-field", "Additional properties"),
        ("non-independent-review", "True was expected"),
        ("self-signed-review", "should not be valid under"),
        ("missing-scenario", "is too short"),
        ("failed-scene-review", "'passed' was expected"),
        ("missing-observation", "'observation' is a required property"),
        ("failed-redaction", "'passed' was expected"),
        ("absolute-media-ref", "does not match"),
        ("package-ref-mismatch", "does not match"),
    ],
)
def test_visual_review_schema_fails_closed_on_incomplete_or_unsafe_receipts(
    mutation: str,
    message: str,
) -> None:
    receipt = copy.deepcopy(_golden_receipt())
    if mutation == "unknown-field":
        receipt["debug_dump"] = "not governed"
    elif mutation == "non-independent-review":
        receipt["review"]["independent"] = False  # type: ignore[index]
    elif mutation == "self-signed-review":
        receipt["review"]["reviewer_id"] = "dev-lane-1"  # type: ignore[index]
    elif mutation == "missing-scenario":
        receipt["scenarios"].pop()  # type: ignore[union-attr]
    elif mutation == "failed-scene-review":
        receipt["scenarios"][0]["review"]["vehicle_proportions"][  # type: ignore[index]
            "verdict"
        ] = "failed"
    elif mutation == "missing-observation":
        receipt["scenarios"][0]["review"]["ego_follow_camera"].pop(  # type: ignore[index]
            "observation"
        )
    elif mutation == "failed-redaction":
        receipt["redaction_evidence"]["status"] = "failed"  # type: ignore[index]
    elif mutation == "absolute-media-ref":
        receipt["scenarios"][0]["media"]["trace"]["content_ref"] = (  # type: ignore[index]
            "/tmp/unredacted/trace.zip"
        )
    elif mutation == "package-ref-mismatch":
        receipt["evidence_package"]["content_ref"] = "project://artifacts/p1"  # type: ignore[index]
    else:  # pragma: no cover - the parameter list is exhaustive
        raise AssertionError(mutation)

    with pytest.raises(ValidationError, match=message):
        _validator().validate(receipt)


def test_visual_review_receipt_binds_exact_scenarios_runs_snapshots_and_media() -> None:
    receipt = _golden_receipt()
    _validator().validate(receipt)
    scenarios = receipt["scenarios"]

    assert [item["scenario_id"] for item in scenarios] == list(SCENARIO_IDS)
    assert len({item["run_id"] for item in scenarios}) == 5
    assert len({item["attempt_id"] for item in scenarios}) == 5
    assert len({item["execution_snapshot_id"] for item in scenarios}) == 5
    assert all(
        list(item["media"]) == list(MEDIA_KINDS)
        and all(len(media["content_digest"]) == 64 for media in item["media"].values())
        and list(item["review"]) == list(REVIEW_CHECKS)
        and all(
            check["verdict"] == "passed" and len(check["observation"]) >= 12
            for check in item["review"].values()
        )
        for item in scenarios
    )
    media_refs = sorted(
        media["content_ref"]
        for item in scenarios
        for media in item["media"].values()
    )
    assert receipt["redaction_evidence"]["scanned_artifact_refs"] == media_refs


def test_candidate_visual_receipt_is_valid_when_browser_gate_has_started() -> None:
    configured = os.environ.get("SCENARIOFORGE_RELEASE_EVIDENCE_DIR")
    if configured is None:
        return

    actual_receipt = Path(configured) / RECEIPT_NAME
    assert actual_receipt.is_file(), "external sidecar visual receipt is missing"
    expected_digest = os.environ.get("SCENARIOFORGE_VISUAL_REVIEW_RECEIPT_DIGEST")
    assert expected_digest is not None, "runtime visual receipt digest is missing"
    assert hashlib.sha256(actual_receipt.read_bytes()).hexdigest() == expected_digest
    receipt = json.loads(actual_receipt.read_text(encoding="utf-8"))
    _validator().validate(receipt)
    assert [item["scenario_id"] for item in receipt["scenarios"]] == list(
        SCENARIO_IDS
    )
