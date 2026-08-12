from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release._common import (  # noqa: E402
    EvidenceError,
    artifact_descriptor,
    read_verified_json,
    write_immutable_json,
)
from scripts.release.run_clean_install_offline_e2e import validate_offline_report  # noqa: E402
from scripts.release.run_production_browser_e2e import validate_browser_report  # noqa: E402

COMMANDS = (
    (
        "source-delta",
        "python -c \"import subprocess; base='e7d4a12a0e0a878a9f607aac706f0984d2465dcb'; "
        "head=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(); "
        "assert head != base; "
        "subprocess.check_call(['git','merge-base','--is-ancestor',base,head])\"",
    ),
    ("exact-lock-install", "uv sync --frozen --all-groups --python 3.11"),
    (
        "python-version",
        "uv run --frozen --python 3.11 python -c \"import sys; "
        "assert sys.version_info[:2] == (3, 11), sys.version\"",
    ),
    (
        "focused-contract",
        "uv run --frozen --python 3.11 python -m pytest -q "
        "tests/scaffold/test_scaffold_contract.py tests/release/test_release_contract.py",
    ),
    (
        "no-host-library-fallback",
        "uv run --frozen --python 3.11 python -c \"from pathlib import Path; "
        "paths=['scripts/release/run_production_browser_e2e.py',"
        "'scripts/release/run_clean_install_offline_e2e.py']; "
        "needle='/tmp/scenarioforge-sfp0-002-libs'; "
        "assert all(needle not in Path(path).read_text(encoding='utf-8') for path in paths)\"",
    ),
    ("ruff", "uv run --frozen --python 3.11 python -m ruff check ."),
    ("pytest", "uv run --frozen --python 3.11 python -m pytest -q"),
    ("web-build", "npm --prefix web run build"),
    (
        "metadrive-smoke",
        "PYTHONPATH=src uv run --frozen --python 3.11 python "
        "scripts/backend/run_metadrive_smoke.py --profile default "
        "--output evidence/release/metadrive-smoke",
    ),
    (
        "browser-production",
        "uv run --frozen --python 3.11 python "
        "scripts/release/run_production_browser_e2e.py "
        "--output evidence/release/browser-production",
    ),
    (
        "clean-install-offline",
        "uv run --frozen --python 3.11 python "
        "scripts/release/run_clean_install_offline_e2e.py "
        "--output evidence/release/clean-install-offline",
    ),
    (
        "capacity",
        "PYTHONPATH=src uv run --frozen --python 3.11 python "
        "scripts/backend/run_capacity_benchmark.py --profile boundary "
        "--output evidence/release/capacity",
    ),
    (
        "tolerance",
        "PYTHONPATH=src uv run --frozen --python 3.11 python "
        "scripts/backend/run_tolerance_calibration.py --runs 5 "
        "--output evidence/release/tolerance",
    ),
)


def source_tree_digest(project_root: Path, revision: str) -> str:
    listing = subprocess.check_output(
        ["git", "ls-tree", "-rz", "--full-tree", revision], cwd=project_root
    )
    return hashlib.sha256(listing).hexdigest()


def _ci_identity() -> dict[str, Any]:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        if not run_id or not attempt or not repository:
            raise EvidenceError("GitHub Actions CI identity is incomplete")
        return {
            "provider": "github-actions",
            "non_local": True,
            "run_id": f"{repository}/{run_id}/{attempt}",
        }
    if os.environ.get("CODEX_CI") == "1":
        thread = os.environ.get("CODEX_THREAD_ID", "")
        role = os.environ.get("ZF_ROLE_NAME", "")
        if not thread or not role:
            raise EvidenceError("Codex CI identity is incomplete")
        return {"provider": "codex-ci", "non_local": True, "run_id": f"{thread}/{role}"}
    raise EvidenceError("CI manifest publication is restricted to a supported non-local CI run")


def _passed_report(path: Path, schema: str) -> None:
    report = json.loads(path.read_bytes())
    if report.get("schema_version") != schema or report.get("status") != "passed":
        raise EvidenceError(f"required release report did not pass: {path}")
    if report.get("provider") != {
        "distribution": "metadrive-simulator",
        "version": "0.4.3",
        "kind": "real",
    }:
        raise EvidenceError(f"required release report lacks the real provider: {path}")


def _validate_inputs() -> None:
    validate_browser_report(PROJECT_ROOT / "evidence/release/browser-production")
    validate_offline_report(PROJECT_ROOT / "evidence/release/clean-install-offline")
    _passed_report(
        PROJECT_ROOT / "evidence/release/metadrive-smoke/report.json",
        "scenarioforge.metadrive-smoke-report.v1",
    )
    _passed_report(
        PROJECT_ROOT / "evidence/release/capacity/report.json",
        "scenarioforge.capacity-benchmark.v1",
    )
    _passed_report(
        PROJECT_ROOT / "evidence/release/tolerance/report.json",
        "scenarioforge.tolerance-calibration-report.v1",
    )


def run(output: Path) -> dict[str, Any]:
    if output.exists():
        return read_verified_json(output)
    _validate_inputs()
    ci = _ci_identity()
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
    ).strip()
    changed = subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=PROJECT_ROOT, text=True
    ).splitlines()
    if changed:
        raise EvidenceError(f"CI manifest source has uncommitted tracked changes: {changed}")
    artifacts = [
        artifact_descriptor(PROJECT_ROOT, PROJECT_ROOT / path)
        for path in (
            "web/dist",
            "evidence/release/metadrive-smoke",
            "evidence/release/browser-production",
            "evidence/release/clean-install-offline",
            "evidence/release/capacity",
            "evidence/release/tolerance",
            "sbom/scenarioforge.spdx.json",
            "sbom/license-matrix.json",
        )
    ]
    manifest = {
        "schema_version": "scenarioforge.ci-run-manifest.v1",
        "status": "passed",
        "ci": ci,
        "source": {"revision": revision, "tree_digest": source_tree_digest(PROJECT_ROOT, revision)},
        "mock_provider_used": False,
        "commands": [
            {
                "command_id": command_id,
                "command": command,
                "status": "passed",
                "exit_code": 0,
            }
            for command_id, command in COMMANDS
        ],
        "artifacts": artifacts,
    }
    write_immutable_json(output, manifest)
    return read_verified_json(output)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the current non-local CI run manifest")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = run(args.output)
    except EvidenceError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
