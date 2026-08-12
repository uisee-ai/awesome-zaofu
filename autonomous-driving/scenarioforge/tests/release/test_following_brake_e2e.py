from __future__ import annotations

import json
from pathlib import Path

from scripts.backend.run_following_brake_e2e import (
    REGRESSION_SAMPLE_ID,
    _bootstrap_project_runtime,
    build_regression_request,
    load_regression_cases,
    validate_regression_report,
)
from scripts.release._common import write_digest_sidecar, write_immutable_json
from scripts.release.run_following_brake_browser_e2e import _browser_bundle_sources, _comparison_profile, validate_browser_report
from scenarioforge.compiler import compile_scenario
from scenarioforge.spec import canonical_scenario


PROJECT_ROOT = Path(__file__).parents[2]


def _execution_receipts() -> list[dict[str, object]]:
    return [
        {"path": "cli", "status": "completed", "command": ["scenarioforge", "compile"], "seed": 17, "profile": "default"},
        {"path": "web_api", "status": "completed", "submit_endpoint": "/api/runs", "seed": 17, "profile": "default"},
    ]


def test_committed_following_brake_cases_are_distinct_and_share_a_replay_request() -> None:
    baseline, candidate = load_regression_cases(PROJECT_ROOT / "samples")

    assert baseline.name == REGRESSION_SAMPLE_ID
    assert candidate.name == f"{REGRESSION_SAMPLE_ID}-candidate"
    assert canonical_scenario(baseline).digest != canonical_scenario(candidate).digest
    assert build_regression_request(baseline).seeds == build_regression_request(candidate).seeds == (17,)
    assert compile_scenario(baseline, build_regression_request(baseline)).cases
    assert compile_scenario(candidate, build_regression_request(candidate)).cases


def test_bare_entry_reexecs_the_project_interpreter_with_preserved_pythonpath(
    monkeypatch, tmp_path: Path
) -> None:
    import scripts.backend.run_following_brake_e2e as runner

    project_root = tmp_path / "project"
    project_python = project_root / ".venv/bin/python"
    project_python.parent.mkdir(parents=True)
    project_python.touch()
    script = project_root / "scripts/backend/run_following_brake_e2e.py"
    calls: list[tuple[str, list[str], dict[str, str]]] = []

    monkeypatch.setattr(runner, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(runner.sys, "executable", "/usr/bin/python")
    monkeypatch.setattr(runner.sys, "argv", [str(script), "--repeat", "2"])
    monkeypatch.setenv("PYTHONPATH", "existing-path")
    monkeypatch.delenv("SCENARIOFORGE_REGRESSION_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(
        runner.os,
        "execve",
        lambda executable, argv, environment: calls.append((executable, argv, environment)),
    )

    _bootstrap_project_runtime()

    assert calls == [
        (
            str(project_python),
            [str(project_python), str(script), "--repeat", "2"],
            {
                **{key: value for key, value in calls[0][2].items() if key not in {"PYTHONPATH", "SCENARIOFORGE_REGRESSION_BOOTSTRAPPED"}},
                "PYTHONPATH": f"{project_root / 'src'}:{project_root}:existing-path",
                "SCENARIOFORGE_REGRESSION_BOOTSTRAPPED": "1",
            },
        )
    ]


def test_regression_report_rejects_wall_cpu_and_rss_comparisons() -> None:
    report = {
        "schema_version": "scenarioforge.following-brake-regression.v1",
        "status": "passed",
        "execution": {"interpreter": "/worktree/.venv/bin/python"},
        "comparison_fields": [
            "most_dangerous_tick",
            "minimum_ttc_seconds",
            "collision",
            "event_receipt",
            "safety_verdict",
        ],
        "baseline": {
            "bundle": {"path": "cli/baseline", "manifest_sha256": "a" * 64},
            "safety": {
                "most_dangerous_tick": 60,
                "minimum_ttc_seconds": 4.0,
                "event_receipt": {"triggered_tick": 20},
                "collision": False,
                "safety_verdict": "pass",
            },
        },
        "candidate": {
            "bundle": {"path": "web/candidate", "manifest_sha256": "b" * 64},
            "safety": {
                "most_dangerous_tick": 5,
                "minimum_ttc_seconds": 0.2,
                "event_receipt": {"triggered_tick": 0},
                "collision": True,
                "safety_verdict": "fail",
            },
        },
        "execution_receipts": _execution_receipts(),
        "tamper_negative": "passed",
        "exact_replay": "passed",
        "tolerance_calibration": "passed",
    }

    validate_regression_report(report)
    report["comparison_fields"].append("wall_seconds")

    try:
        validate_regression_report(report)
    except ValueError as error:
        assert "performance" in str(error)
    else:
        raise AssertionError("performance comparison was accepted")


def test_regression_report_requires_collision_and_verdict_to_differ() -> None:
    report = {
        "schema_version": "scenarioforge.following-brake-regression.v1",
        "status": "passed",
        "execution": {"interpreter": "/worktree/.venv/bin/python"},
        "comparison_fields": [
            "most_dangerous_tick",
            "minimum_ttc_seconds",
            "collision",
            "event_receipt",
            "safety_verdict",
        ],
        "baseline": {
            "bundle": {"path": "cli/baseline", "manifest_sha256": "a" * 64},
            "safety": {
                "most_dangerous_tick": 60,
                "minimum_ttc_seconds": 4.0,
                "event_receipt": {"triggered_tick": 20},
                "collision": False,
                "safety_verdict": "pass",
            },
        },
        "candidate": {
            "bundle": {"path": "web/candidate", "manifest_sha256": "b" * 64},
            "safety": {
                "most_dangerous_tick": 5,
                "minimum_ttc_seconds": 0.2,
                "event_receipt": {"triggered_tick": 0},
                "collision": False,
                "safety_verdict": "pass",
            },
        },
        "execution_receipts": _execution_receipts(),
        "tamper_negative": "passed",
        "exact_replay": "passed",
        "tolerance_calibration": "passed",
    }

    try:
        validate_regression_report(report)
    except ValueError as error:
        assert "collision" in str(error)
    else:
        raise AssertionError("report accepted equal collision and safety verdict results")


def test_regression_report_requires_distinct_cli_and_web_api_receipts() -> None:
    report = {
        "schema_version": "scenarioforge.following-brake-regression.v1",
        "status": "passed",
        "execution": {"interpreter": "/worktree/.venv/bin/python"},
        "comparison_fields": [
            "most_dangerous_tick",
            "minimum_ttc_seconds",
            "collision",
            "event_receipt",
            "safety_verdict",
        ],
        "baseline": {
            "bundle": {"path": "cli/baseline", "manifest_sha256": "a" * 64},
            "safety": {
                "most_dangerous_tick": 60,
                "minimum_ttc_seconds": 4.0,
                "event_receipt": {"triggered_tick": 20},
                "collision": False,
                "safety_verdict": "pass",
            },
        },
        "candidate": {
            "bundle": {"path": "web/candidate", "manifest_sha256": "b" * 64},
            "safety": {
                "most_dangerous_tick": 5,
                "minimum_ttc_seconds": 0.2,
                "event_receipt": {"triggered_tick": 0},
                "collision": True,
                "safety_verdict": "fail",
            },
        },
        "tamper_negative": "passed",
        "exact_replay": "passed",
        "tolerance_calibration": "passed",
    }

    try:
        validate_regression_report(report)
    except ValueError as error:
        assert "receipt" in str(error)
    else:
        raise AssertionError("report accepted runs without CLI and Web API receipts")


def test_catalog_registers_the_committed_regression_fixture() -> None:
    catalog = json.loads((PROJECT_ROOT / "samples/catalog.json").read_text(encoding="utf-8"))

    assert {
        "id": REGRESSION_SAMPLE_ID,
        "json": "following-emergency-brake.json",
        "yaml": "following-emergency-brake.yaml",
    } in catalog["samples"]


def test_browser_sources_preserve_the_web_api_sealed_bundle_id(tmp_path: Path) -> None:
    write_immutable_json(
        tmp_path / "report.json",
        {
            "baseline": {"bundle": {"path": "cli/baseline"}},
            "candidate": {"bundle": {"path": "web/run-4f2d"}},
        },
    )

    sources = _browser_bundle_sources(tmp_path)

    assert sources == {
        "baseline": tmp_path / "cli/baseline",
        "candidate": tmp_path / "web/run-4f2d",
    }


def test_browser_comparison_uses_the_calibrated_profile_from_regression_evidence(tmp_path: Path) -> None:
    profile = {"schema_version": "scenarioforge.tolerance-profile.v1", "profile_version": 1}
    write_immutable_json(tmp_path / "report.json", {"tolerance_profile": profile})

    assert _comparison_profile(tmp_path) == profile


def _write_browser_evidence(
    tmp_path: Path,
    network_digest: str | None = None,
    baseline_screenshot_digest: str | None = None,
    include_product_assertions: bool = True,
) -> None:
    write_immutable_json(
        tmp_path / "network.json",
        {
            "responses": [
                {"method": "POST", "url": "http://127.0.0.1:8123/api/replays/load", "response_status": 200, "bundle_id": "baseline"},
                {"method": "POST", "url": "http://127.0.0.1:8123/api/replays/load", "response_status": 200, "bundle_id": "candidate"},
            ]
        },
    )
    for name in ("baseline.png", "candidate.png"):
        (tmp_path / name).write_bytes(name.encode("ascii"))
    screenshot_digests = {name: write_digest_sidecar(tmp_path / name) for name in ("baseline.png", "candidate.png")}
    report = {
        "schema_version": "scenarioforge.following-brake-browser-e2e.v1",
        "status": "passed",
        "network_log": {"path": "network.json", "sha256": network_digest or write_digest_sidecar(tmp_path / "network.json")},
        "screenshots": [
            {"path": "baseline.png", "sha256": baseline_screenshot_digest or screenshot_digests["baseline.png"]},
            {"path": "candidate.png", "sha256": screenshot_digests["candidate.png"]},
        ],
        "bundles": {"baseline": "d" * 64, "candidate": "e" * 64},
        "bundle_ids": {"baseline": "baseline", "candidate": "candidate"},
        "docker_image": {"reference": "mcp/playwright:latest", "image_id": "sha256:" + "f" * 64, "repo_digest": "mcp/playwright@sha256:" + "a" * 64},
    }
    if include_product_assertions:
        report["product_assertions"] = {
            "job_status": True,
            "baseline_actor_replay": True,
            "candidate_actor_replay": True,
            "event": True,
            "minimum_ttc": True,
            "safety_verdict": True,
            "comparison": True,
        }
    write_immutable_json(tmp_path / "report.json", report)


def test_browser_report_requires_verified_sidecars_network_and_image_identity(tmp_path: Path) -> None:
    _write_browser_evidence(tmp_path)

    validate_browser_report(tmp_path)


def test_browser_report_rejects_network_digest_that_disagrees_with_sidecar(tmp_path: Path) -> None:
    _write_browser_evidence(tmp_path, network_digest="a" * 64)

    try:
        validate_browser_report(tmp_path)
    except ValueError as error:
        assert "digest" in str(error)
    else:
        raise AssertionError("report accepted a network digest that differs from its sidecar")


def test_browser_report_rejects_screenshot_digest_that_disagrees_with_sidecar(tmp_path: Path) -> None:
    _write_browser_evidence(tmp_path, baseline_screenshot_digest="a" * 64)

    try:
        validate_browser_report(tmp_path)
    except ValueError as error:
        assert "screenshot" in str(error)
    else:
        raise AssertionError("report accepted a screenshot digest that differs from its sidecar")


def test_browser_report_requires_visible_product_assertions(tmp_path: Path) -> None:
    _write_browser_evidence(tmp_path, include_product_assertions=False)

    try:
        validate_browser_report(tmp_path)
    except ValueError as error:
        assert "assertion" in str(error)
    else:
        raise AssertionError("browser report accepted without product-state assertions")
