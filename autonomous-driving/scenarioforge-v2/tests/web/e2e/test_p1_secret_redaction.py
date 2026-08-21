from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest

from scenarioforge.security import SecurityViolation, assert_no_marked_secrets

ROOT = Path(__file__).resolve().parents[3]
P1_SCENARIOS = (
    "highway_merge",
    "competitive_lane_change",
    "cross_traffic_red_light_violation",
    "unprotected_left_turn",
    "pedestrian_red_light_crossing",
)
ACCEPTANCE_COVERAGE = (
    "AC-P1-005",
    "AC-P1-006",
    "AC-P1-007",
    "AC-P1-008",
    "AC-P1-009",
    "AC-P1-011",
    "AC-P1-014",
    "AC-P1-017",
    "AC-P1-018",
)
EXPECTED_RELEASE_FILES = (
    "p1-release-browser-report.json",
    "screenshots/competitive_lane_change.png",
    "screenshots/cross_traffic_red_light_violation.png",
    "screenshots/highway_merge.png",
    "screenshots/pedestrian_red_light_crossing.png",
    "screenshots/unprotected_left_turn.png",
    "traces/competitive_lane_change.zip",
    "traces/cross_traffic_red_light_violation.zip",
    "traces/highway_merge.zip",
    "traces/pedestrian_red_light_crossing.zip",
    "traces/unprotected_left_turn.zip",
    "videos/competitive_lane_change.webm",
    "videos/cross_traffic_red_light_violation.webm",
    "videos/highway_merge.webm",
    "videos/pedestrian_red_light_crossing.webm",
    "videos/unprotected_left_turn.webm",
)
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _release_root(tmp_path: Path) -> Path:
    configured = os.environ.get("SCENARIOFORGE_RELEASE_EVIDENCE_DIR")
    root = Path(configured) if configured else tmp_path.parent / "p1-release-evidence"
    if not root.is_absolute():
        root = ROOT / root
    resolved = root.resolve(strict=True)
    try:
        resolved.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise AssertionError("release evidence must use a repository-external sidecar")


def _marked_secret() -> str:
    value = os.environ.get("SCENARIOFORGE_MARKED_SECRET", "[REDACTED_SECRET]")
    assert len(value) >= 8
    return value


def _sensitive_values() -> tuple[str, ...]:
    marked = _marked_secret()
    configured = os.environ.get("SCENARIOFORGE_RELEASE_EVIDENCE_DIR", "")
    return tuple(
        value
        for value in (
            marked,
            f"{marked}:request-token",
            f"{marked}:cookie",
            f"{marked}:authorization",
            f"{marked}:controlled-file",
            f"{marked}:rejected-field",
            str(ROOT),
            "/workspace",
            "/tmp/scenarioforge-pw",
            configured,
        )
        if value
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _media_digest(report: dict[str, object]) -> str:
    scenarios = report["scenarios"]
    assert isinstance(scenarios, list)
    manifest: list[dict[str, object]] = []
    for scenario in scenarios:
        assert isinstance(scenario, dict)
        media = scenario["media"]
        assert isinstance(media, dict)
        for kind in ("screenshot", "video", "trace"):
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


def test_p1_release_evidence_enumerates_and_redacts_all_candidate_media(
    tmp_path: Path,
) -> None:
    evidence = _release_root(tmp_path)
    report_path = evidence / "p1-release-browser-report.json"
    assert report_path.is_file(), "run test_p1_release.py before the redaction gate"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert set(report) == {
        "schema_version",
        "acceptance_coverage",
        "assertion_summary",
        "browser",
        "console_errors",
        "evidence_package",
        "page_errors",
        "scenarios",
        "service_url",
        "source_candidate_bound",
        "source_candidate_commit",
    }
    assert report["schema_version"] == "scenarioforge.p1-candidate-media/v3"
    assert tuple(report["acceptance_coverage"]) == ACCEPTANCE_COVERAGE
    assert report["source_candidate_bound"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", report["source_candidate_commit"])
    configured_commit = os.environ.get("SCENARIOFORGE_CANDIDATE_COMMIT")
    if configured_commit is not None:
        assert report["source_candidate_commit"] == configured_commit
    assert report["browser"]["name"] == "chromium"
    assert isinstance(report["browser"]["version"], str)
    assert report["assertion_summary"] == {
        "heading_tangent_assertion_count": report["assertion_summary"][
            "heading_tangent_assertion_count"
        ],
        "media_count": 15,
        "scenario_count": 5,
        "status": "passed",
    }
    assert report["assertion_summary"]["heading_tangent_assertion_count"] > 0
    assert report["console_errors"] == []
    assert report["page_errors"] == []
    assert tuple(item["scenario_id"] for item in report["scenarios"]) == P1_SCENARIOS
    media_digest = _media_digest(report)
    assert report["evidence_package"] == {
        "artifact_count": 15,
        "content_digest": media_digest,
        "content_ref": f"sha256:{media_digest}",
        "schema_version": "scenarioforge.p1-media-package/v1",
    }

    media_paths: list[str] = []
    for scenario in report["scenarios"]:
        assert set(scenario) == {
            "attempt_id",
            "backend",
            "camera",
            "execution_snapshot_digest",
            "execution_snapshot_id",
            "follow_pose_samples",
            "media",
            "run_id",
            "scenario_id",
            "terminal_status",
        }
        assert scenario["run_id"].startswith("p1-run-")
        assert scenario["attempt_id"].startswith("attempt-")
        assert scenario["execution_snapshot_id"] == (
            f"p1-smarts-runs/{scenario['run_id']}/{scenario['attempt_id']}"
        )
        assert HEX_DIGEST.fullmatch(scenario["execution_snapshot_digest"])
        assert scenario["backend"] == {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
        }
        assert scenario["terminal_status"] == "completed"
        assert scenario["camera"] == {
            "available_modes": ["ego-follow", "overview", "fixed", "free"],
            "default_mode": "ego-follow",
            "pose_source": "recorded-trajectory",
            "target_participant_id": "ego",
        }
        assert [item["source_tick"] for item in scenario["follow_pose_samples"]] == [
            5,
            10,
        ]
        assert set(scenario["media"]) == {"screenshot", "trace", "video"}
        for kind, suffix in (
            ("screenshot", ".png"),
            ("trace", ".zip"),
            ("video", ".webm"),
        ):
            item = scenario["media"][kind]
            assert set(item) == {"byte_count", "path", "sha256"}
            assert item["path"].endswith(f"/{scenario['scenario_id']}{suffix}")
            assert not Path(item["path"]).is_absolute()
            target = evidence / item["path"]
            assert target.is_file()
            assert item["byte_count"] == target.stat().st_size
            assert item["byte_count"] > (10_000 if kind == "screenshot" else 1_000)
            assert item["sha256"] == _sha256(target)
            media_paths.append(item["path"])

    assert len(media_paths) == len(set(media_paths)) == 15
    assert tuple(sorted(("p1-release-browser-report.json", *media_paths))) == (
        EXPECTED_RELEASE_FILES
    )
    scanned = assert_no_marked_secrets(
        evidence,
        sensitive_values=_sensitive_values(),
    )
    expected_scanned = set(EXPECTED_RELEASE_FILES)
    # The final post-signoff gate intentionally reuses one external sidecar:
    # P0 browser evidence may already be present and the independent visual
    # receipt must remain present. Both are scanned rather than treated as
    # unexpected or silently excluded.
    for optional_ref in ("release-browser-report.json", "visual-review-receipt.json"):
        if (evidence / optional_ref).is_file():
            expected_scanned.add(optional_ref)
    assert set(scanned) == expected_scanned


def test_p1_release_evidence_gate_blocks_all_unredacted_counterfactuals(
    tmp_path: Path,
) -> None:
    secret = _marked_secret()
    variants = {
        "raw": secret.encode(),
        "url": quote(secret, safe="").encode(),
        "base64": base64.b64encode(secret.encode()),
        "hex": secret.encode().hex().encode(),
        "token": f"Bearer {secret}:request-token".encode(),
        "cookie": f"session={secret}:cookie".encode(),
        "authorization": f"Authorization: Bearer {secret}:authorization".encode(),
        "absolute-path": str(ROOT).encode(),
    }
    for name, payload in variants.items():
        target = tmp_path / name
        target.mkdir()
        (target / "evidence.bin").write_bytes(payload)
        with pytest.raises(SecurityViolation, match="marked secret") as caught:
            assert_no_marked_secrets(target, sensitive_values=_sensitive_values())
        assert caught.value.code == "marked_secret_detected"

    archive_root = tmp_path / "zip"
    archive_root.mkdir()
    with zipfile.ZipFile(archive_root / "trace.zip", "w") as archive:
        archive.writestr("resources/console.log", f"{secret}:rejected-field")
    with pytest.raises(SecurityViolation, match="marked secret") as caught:
        assert_no_marked_secrets(
            archive_root,
            sensitive_values=_sensitive_values(),
        )
    assert caught.value.code == "marked_secret_detected"
