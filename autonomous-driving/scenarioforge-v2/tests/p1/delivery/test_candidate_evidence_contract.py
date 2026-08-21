from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "tests/p1/delivery/run_candidate_delivery.py"
REPORT_REF = "p1-release-browser-report.json"
RECEIPT_REF = "visual-review-receipt.json"
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
_AUTO_RECEIPT_DIGEST = object()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _media_digest(scenarios: list[dict[str, object]]) -> str:
    manifest: list[dict[str, object]] = []
    for scenario in scenarios:
        media = scenario["media"]
        assert isinstance(media, dict)
        for kind in MEDIA_KINDS:
            item = media[kind]
            assert isinstance(item, dict)
            manifest.append(
                {
                    "byte_count": item["byte_count"],
                    "path": item["path"],
                    "sha256": item["sha256"],
                }
            )
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


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


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    if path.exists():
        path.chmod(0o600)
    path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o444)


def _write_evidence(root: Path, source_candidate_commit: str) -> Path:
    report_scenarios: list[dict[str, object]] = []
    receipt_scenarios: list[dict[str, object]] = []
    scanned_refs: list[str] = []
    for index, scenario_id in enumerate(SCENARIO_IDS, start=1):
        report_media: dict[str, dict[str, object]] = {}
        receipt_media: dict[str, dict[str, str]] = {}
        for kind in MEDIA_KINDS:
            extension = {"screenshot": "png", "video": "webm", "trace": "zip"}[kind]
            relative = Path(f"{kind}s") / f"{scenario_id}.{extension}"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind == "trace":
                with zipfile.ZipFile(target, "w") as archive:
                    archive.writestr(
                        "resources/console.log",
                        f"safe trace for {scenario_id}\n",
                    )
            else:
                target.write_bytes(f"safe {kind} for {scenario_id}\n".encode())
            reference = relative.as_posix()
            scanned_refs.append(reference)
            digest = _sha256(target)
            report_media[kind] = {
                "byte_count": target.stat().st_size,
                "path": reference,
                "sha256": digest,
            }
            receipt_media[kind] = {
                "content_ref": reference,
                "content_digest": digest,
                "capture_allowlist_digest": hashlib.sha256(
                    f"allowlist:{kind}".encode()
                ).hexdigest(),
            }
        shared = {
            "scenario_id": scenario_id,
            "run_id": f"p1-run-{index:02d}",
            "attempt_id": f"attempt-p1-{index:02d}",
            "execution_snapshot_id": f"snapshot-p1-{index:02d}",
            "execution_snapshot_digest": hashlib.sha256(
                f"snapshot:{scenario_id}".encode()
            ).hexdigest(),
        }
        report_scenarios.append(
            {
                **shared,
                "backend": {
                    "id": "scenarioforge.smarts",
                    "version": "2.0.1",
                },
                "terminal_status": "completed",
                "camera": {
                    "available_modes": [
                        "ego-follow",
                        "overview",
                        "fixed",
                        "free",
                    ],
                    "default_mode": "ego-follow",
                    "pose_source": "recorded-trajectory",
                    "target_participant_id": "ego",
                },
                "follow_pose_samples": [
                    {"source_tick": 5},
                    {"source_tick": 10},
                ],
                "media": report_media,
            }
        )
        receipt_scenarios.append(
            {
                **shared,
                "media": receipt_media,
                "review": _scene_review(scenario_id),
            }
        )
    media_digest = _media_digest(report_scenarios)
    report = {
        "schema_version": "scenarioforge.p1-candidate-media/v3",
        "acceptance_coverage": ["AC-P1-014", "AC-P1-017", "AC-P1-018"],
        "assertion_summary": {
            "heading_tangent_assertion_count": 5,
            "media_count": 15,
            "scenario_count": 5,
            "status": "passed",
        },
        "browser": {"name": "chromium", "version": "fixture"},
        "console_errors": [],
        "evidence_package": {
            "schema_version": "scenarioforge.p1-media-package/v1",
            "artifact_count": 15,
            "content_digest": media_digest,
            "content_ref": f"sha256:{media_digest}",
        },
        "page_errors": [],
        "scenarios": report_scenarios,
        "service_url": "http://127.0.0.1:8765",
        "source_candidate_bound": True,
        "source_candidate_commit": source_candidate_commit,
    }
    report_path = root / REPORT_REF
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_digest = _sha256(report_path)
    package_digest = _package_digest(report_digest, media_digest)
    receipt = {
        "schema_version": "scenarioforge.visual-review-receipt/v3",
        "status": "approved",
        "source_candidate_commit": source_candidate_commit,
        "evidence_package": {
            "schema_version": "scenarioforge.candidate-evidence-package/v1",
            "report_ref": REPORT_REF,
            "report_digest": report_digest,
            "media_digest": media_digest,
            "content_digest": package_digest,
            "content_ref": f"sha256:{package_digest}",
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
        "scenarios": receipt_scenarios,
        "redaction_evidence": {
            "schema_version": "scenarioforge.candidate-redaction-evidence/v1",
            "status": "passed",
            "source_candidate_commit": source_candidate_commit,
            "allowlist_schema_version": "scenarioforge.artifact-allowlist/v1",
            "allowlist_digest": hashlib.sha256(b"artifact-allowlists").hexdigest(),
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
    receipt_path = root / RECEIPT_REF
    _write_receipt(receipt_path, receipt)
    return receipt_path


def _run(
    *arguments: str,
    receipt_digest: str | None | object = _AUTO_RECEIPT_DIGEST,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("SCENARIOFORGE_VISUAL_REVIEW_RECEIPT_DIGEST", None)
    if receipt_digest is _AUTO_RECEIPT_DIGEST and "--evidence-dir" in arguments:
        root = Path(arguments[arguments.index("--evidence-dir") + 1])
        receipt_digest = _sha256(root / RECEIPT_REF)
    if isinstance(receipt_digest, str):
        environment["SCENARIOFORGE_VISUAL_REVIEW_RECEIPT_DIGEST"] = receipt_digest
    return subprocess.run(
        [sys.executable, str(RUNNER), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_candidate_delivery_health_check_is_executable_and_deterministic() -> None:
    first = _run("--health-check")
    second = _run("--health-check")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert json.loads(first.stdout) == {
        "entrypoint_id": "p1-candidate-gate",
        "browser_report": REPORT_REF,
        "required_arguments": ["--source-candidate-commit", "--evidence-dir"],
        "schema_version": "scenarioforge.candidate-delivery-health/v2",
        "status": "ready",
        "visual_review_receipt": RECEIPT_REF,
    }
    assert first.stderr == ""


def test_candidate_delivery_binds_head_evidence_tree_and_all_receipt_digests(
    tmp_path: Path,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    _write_evidence(evidence, candidate)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema_version"] == "scenarioforge.candidate-delivery-result/v2"
    assert result["status"] == "passed"
    assert result["source_candidate_commit"] == candidate
    assert result["scenario_ids"] == list(SCENARIO_IDS)
    assert result["report_ref"] == REPORT_REF
    assert result["receipt_ref"] == RECEIPT_REF
    assert result["visual_review_receipt_digest"] == _sha256(
        evidence / RECEIPT_REF
    )
    assert result["evidence_package_ref"].startswith("sha256:")
    assert result["evidence_package_digest"] == result["evidence_package_ref"][7:]
    assert result["sidecar_ref"].startswith("sha256:")
    assert result["scanned_artifact_count"] == 17
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "identity_field",
    [
        "run_id",
        "attempt_id",
        "execution_snapshot_id",
        "execution_snapshot_digest",
    ],
)
def test_candidate_delivery_rejects_receipt_identity_mismatch(
    tmp_path: Path,
    identity_field: str,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    receipt_path = _write_evidence(evidence, candidate)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["scenarios"][0][identity_field] = (
        "b" * 64
        if identity_field == "execution_snapshot_digest"
        else f"mismatched-{identity_field}"
    )
    _write_receipt(receipt_path, receipt)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert json.loads(completed.stderr) == {
        "error_code": "candidate_evidence_invalid",
        "schema_version": "scenarioforge.candidate-delivery-error/v2",
        "status": "failed",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "report-source",
        "receipt-source",
        "package-digest",
        "package-ref",
        "media-digest",
    ],
)
def test_candidate_delivery_fails_closed_on_sidecar_binding_tamper(
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    receipt_path = _write_evidence(evidence, candidate)
    report_path = evidence / REPORT_REF
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    if mutation == "report-source":
        report["source_candidate_commit"] = "b" * 40
        report_path.write_text(json.dumps(report), encoding="utf-8")
    elif mutation == "receipt-source":
        receipt["source_candidate_commit"] = "b" * 40
        _write_receipt(receipt_path, receipt)
    elif mutation == "package-digest":
        receipt["evidence_package"]["content_digest"] = "b" * 64
        _write_receipt(receipt_path, receipt)
    elif mutation == "package-ref":
        receipt["evidence_package"]["content_ref"] = f"sha256:{'b' * 64}"
        _write_receipt(receipt_path, receipt)
    elif mutation == "media-digest":
        receipt["scenarios"][0]["media"]["trace"]["content_digest"] = "b" * 64
        _write_receipt(receipt_path, receipt)
    else:  # pragma: no cover - the parameter list is exhaustive
        raise AssertionError(mutation)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert json.loads(completed.stderr) == {
        "error_code": "candidate_evidence_invalid",
        "schema_version": "scenarioforge.candidate-delivery-error/v2",
        "status": "failed",
    }


def test_candidate_delivery_rejects_candidate_or_redaction_binding_mismatch(
    tmp_path: Path,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    receipt_path = _write_evidence(evidence, candidate)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["redaction_evidence"]["source_candidate_commit"] = "b" * 40
    _write_receipt(receipt_path, receipt)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert json.loads(completed.stderr) == {
        "error_code": "candidate_evidence_invalid",
        "schema_version": "scenarioforge.candidate-delivery-error/v2",
        "status": "failed",
    }


@pytest.mark.parametrize("receipt_digest", [None, "b" * 64])
def test_candidate_delivery_requires_the_runtime_receipt_digest_binding(
    tmp_path: Path,
    receipt_digest: str | None,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    _write_evidence(evidence, candidate)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
        receipt_digest=receipt_digest,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert json.loads(completed.stderr)["error_code"] == "candidate_evidence_invalid"


def test_candidate_delivery_rejects_a_writable_visual_review_receipt(
    tmp_path: Path,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    receipt_path = _write_evidence(evidence, candidate)
    receipt_path.chmod(0o644)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert json.loads(completed.stderr)["error_code"] == "candidate_evidence_invalid"


@pytest.mark.parametrize(
    "mutation",
    ["self-signed-review", "failed-scene-review", "missing-scene-check"],
)
def test_candidate_delivery_rejects_non_independent_or_incomplete_scene_review(
    tmp_path: Path,
    mutation: str,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    receipt_path = _write_evidence(evidence, candidate)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "self-signed-review":
        receipt["review"]["reviewer_id"] = "dev-lane-1"
    elif mutation == "failed-scene-review":
        receipt["scenarios"][0]["review"]["trajectory_heading"]["verdict"] = (
            "failed"
        )
    elif mutation == "missing-scene-check":
        receipt["scenarios"][0]["review"].pop("identity_consistency")
    else:  # pragma: no cover - the parameter list is exhaustive
        raise AssertionError(mutation)
    _write_receipt(receipt_path, receipt)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert json.loads(completed.stderr)["error_code"] == "candidate_evidence_invalid"


def test_candidate_delivery_blocks_marked_secret_in_unreferenced_or_archived_output(
    tmp_path: Path,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    _write_evidence(evidence, candidate)
    canary = "SF_MARKED_SECRET_candidate_gate_17"
    extra = evidence / "structured.log"
    extra.write_text(f"authorization={canary}\n", encoding="utf-8")

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
        "--marked-secret",
        canary,
    )

    assert completed.returncode != 0
    assert canary not in completed.stdout
    assert canary not in completed.stderr
    assert json.loads(completed.stderr)["error_code"] == "candidate_evidence_invalid"


def test_candidate_delivery_rejects_symlinked_evidence_subdirectory(
    tmp_path: Path,
) -> None:
    candidate = _head()
    evidence = tmp_path / "candidate-evidence"
    _write_evidence(evidence, candidate)
    screenshots = evidence / "screenshots"
    actual = evidence / "screenshots-real"
    screenshots.rename(actual)
    screenshots.symlink_to(actual, target_is_directory=True)

    completed = _run(
        "--source-candidate-commit",
        candidate,
        "--evidence-dir",
        str(evidence),
    )

    assert completed.returncode != 0
    assert json.loads(completed.stderr)["error_code"] == "candidate_evidence_invalid"


def test_candidate_delivery_rejects_missing_arguments_without_echoing_paths() -> None:
    completed = _run()

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert json.loads(completed.stderr) == {
        "error_code": "candidate_evidence_invalid",
        "schema_version": "scenarioforge.candidate-delivery-error/v2",
        "status": "failed",
    }
