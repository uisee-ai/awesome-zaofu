from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "tests/web/e2e/Dockerfile.playwright"
CONFTEST = ROOT / "tests/web/conftest.py"
RELEASE_SPEC = ROOT / "tests/web/e2e/test_p1_release.py"
SECRET_SPEC = ROOT / "tests/web/e2e/test_p1_secret_redaction.py"
VISUAL_RUNNER = ROOT / "tests/p1/delivery/run_visual_replay_e2e.py"

EXPECTED_PRODUCER_PATHS = (
    "tests/web/e2e/Dockerfile.playwright",
    "tests/web/e2e/test_p1_release.py",
    "tests/web/e2e/test_p1_secret_redaction.py",
    "tests/web/conftest.py",
    "tests/p1/delivery/run_visual_replay_e2e.py",
    "tests/p1/delivery/test_candidate_harness.py",
)
EXPECTED_ACCEPTANCE_COVERAGE = (
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


def _module_constants(path: Path) -> dict[str, object]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants: dict[str, object] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            try:
                constants[target.id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return constants


def _test_names(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def test_candidate_harness_owns_exactly_the_bounded_browser_inputs() -> None:
    assert tuple(
        path.relative_to(ROOT).as_posix()
        for path in (
            DOCKERFILE,
            RELEASE_SPEC,
            SECRET_SPEC,
            CONFTEST,
            VISUAL_RUNNER,
            Path(__file__),
        )
    ) == EXPECTED_PRODUCER_PATHS
    assert all(
        path.is_file()
        for path in (DOCKERFILE, RELEASE_SPEC, SECRET_SPEC, CONFTEST, VISUAL_RUNNER)
    )


def test_chromium_is_preinstalled_in_a_runtime_visible_shared_path() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    conftest = CONFTEST.read_text(encoding="utf-8")

    shared_path = "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright"
    install = "python -m playwright install --with-deps chromium"
    assert shared_path in dockerfile
    assert dockerfile.count(install) == 1
    assert dockerfile.index(shared_path) < dockerfile.index(install)
    assert dockerfile.index(install) < dockerfile.index("COPY pyproject.toml uv.lock ./")
    assert 'chmod 1777 "${PLAYWRIGHT_BROWSERS_PATH}"' in dockerfile
    assert (
        'chmod -R a+rwX "${PLAYWRIGHT_BROWSERS_PATH}/.links"' in dockerfile
    )
    assert "playwright install" not in dockerfile[dockerfile.index("CMD ") :]
    assert "chromium.executable_path" in conftest
    assert "preinstalled Chromium executable is missing" in conftest


def test_p1_specs_are_collectable_and_bind_complete_acceptance_coverage() -> None:
    release_constants = _module_constants(RELEASE_SPEC)
    secret_constants = _module_constants(SECRET_SPEC)

    assert tuple(release_constants["ACCEPTANCE_COVERAGE"]) == EXPECTED_ACCEPTANCE_COVERAGE
    assert tuple(secret_constants["ACCEPTANCE_COVERAGE"]) == EXPECTED_ACCEPTANCE_COVERAGE
    assert _test_names(RELEASE_SPEC) == {
        "test_five_real_p1_web_runs_emit_candidate_bound_media",
    }
    assert _test_names(SECRET_SPEC) == {
        "test_p1_release_evidence_enumerates_and_redacts_all_candidate_media",
        "test_p1_release_evidence_gate_blocks_all_unredacted_counterfactuals",
    }


def test_visual_runner_uses_a_real_offline_chromium_container() -> None:
    source = VISUAL_RUNNER.read_text(encoding="utf-8")

    for token in (
        "Dockerfile.playwright",
        '"--network", "none"',
        '"SCENARIOFORGE_CANDIDATE_COMMIT=',
        '"SCENARIOFORGE_RELEASE_EVIDENCE_DIR=/evidence"',
        "tests/web/e2e/test_p1_release.py",
    ):
        assert token in source
    assert "shell=True" not in source

    completed = subprocess.run(
        [sys.executable, str(VISUAL_RUNNER), "--health-check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "schema_version": "scenarioforge.visual-replay-runner-health/v1",
        "status": "ready",
        "runner_id": "p1-docker-chromium",
        "browser": "chromium",
        "network_policy": "offline-runtime",
        "scenario_count": 5,
        "required_arguments": ["--evidence-dir"],
    }
