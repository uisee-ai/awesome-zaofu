from __future__ import annotations

import json
import os
import site
import subprocess
import sys
from pathlib import Path

import pytest

from scenarioforge.clients import (
    ClientResponse,
    ScenarioForgeClient,
    ScenarioForgeClientError,
)
from scenarioforge.orchestration import ExperimentLimits


ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "examples" / "p0c" / "brake_lead.json"


def _definition() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.experiment-definition/v1",
        "matrix": {"scenario_id": ["brake_lead"], "seed": [7]},
        "inputs": {"scenario_revision_digest": "a" * 64},
        "limits": ExperimentLimits.release_default().to_dict(),
    }


def _assert_public_payload(value: object) -> None:
    encoded = json.dumps(value, sort_keys=True)
    assert str(ROOT) not in encoded
    assert "ExperimentService" not in encoded
    assert "ScenarioForgeApplication" not in encoded
    assert "PosixPath" not in encoded


def test_public_typed_sdk_exposes_every_non_web_service_without_backend_leakage(
    tmp_path: Path,
) -> None:
    client = ScenarioForgeClient(
        project_root=ROOT,
        workspace=tmp_path / "workspace",
    )

    health = client.health()
    validation = client.validate(SCENARIO)
    preflight = client.preflight(SCENARIO)
    submitted = client.submit_experiment(
        _definition(),
        idempotency_key="installed-client-submit-0001",
    )
    experiment_id = str(submitted.payload["experiment_id"])
    queried = client.get_experiment(experiment_id)
    controlled = client.control_experiment(
        experiment_id,
        "stop",
        command_id="installed-client-stop-0001",
    )
    recovered = client.recover_experiments()
    comparison = client.comparison_contract()

    for operation, response in (
        ("health", health),
        ("validate", validation),
        ("preflight", preflight),
        ("submit_experiment", submitted),
        ("get_experiment", queried),
        ("control_experiment", controlled),
        ("recover_experiments", recovered),
        ("comparison_contract", comparison),
    ):
        assert isinstance(response, ClientResponse)
        payload = response.to_dict()
        assert payload["schema_version"] == "scenarioforge.client-response/v1"
        assert payload["operation"] == operation
        _assert_public_payload(payload)

    assert validation.payload["valid"] is True
    assert preflight.payload["executable"] is True
    assert submitted.payload["cardinality"] == 1
    assert queried.payload["experiment_id"] == experiment_id
    assert controlled.payload["state"] == "cancelled"
    assert recovered.payload["experiments"][0]["experiment_id"] == experiment_id
    comparison_payload = comparison.to_dict()["payload"]
    assert comparison_payload["matrix"]["seeds"] == [7, 8, 9]
    assert comparison_payload["matrix"]["real_child_runs"] == 30


def test_public_typed_errors_are_stable_json_and_hide_host_paths(tmp_path: Path) -> None:
    client = ScenarioForgeClient(
        project_root=ROOT,
        workspace=tmp_path / "workspace",
    )

    with pytest.raises(ScenarioForgeClientError) as captured:
        client.validate(tmp_path / "missing-scenario.json")

    payload = captured.value.to_dict()
    assert payload == {
        "schema_version": "scenarioforge.client-error/v1",
        "operation": "validate",
        "code": "scenario_input_invalid",
        "message": "scenario input failed closed",
    }
    _assert_public_payload(payload)


def test_built_wheel_exposes_real_console_script_and_typed_sdk_in_isolation(
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--no-build-isolation",
            "--offline",
            "--out-dir",
            str(wheelhouse),
            str(ROOT),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("scenarioforge-*.whl"))
    environment = tmp_path / "installed"
    subprocess.run(
        [
            "uv",
            "venv",
            "--no-project",
            "--system-site-packages",
            "--python",
            sys.executable,
            str(environment),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    python = environment / "bin" / "python"
    console = environment / "bin" / "scenarioforge"
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--offline",
            "--no-deps",
            "--python",
            str(python),
            str(wheel),
        ],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    child_environment = dict(os.environ)
    child_environment["PYTHONPATH"] = os.pathsep.join(site.getsitepackages())
    child_environment["PYTHONDONTWRITEBYTECODE"] = "1"

    origin = subprocess.run(
        [str(python), "-c", "import scenarioforge; print(scenarioforge.__file__)"],
        check=True,
        cwd=tmp_path,
        env=child_environment,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert origin.startswith(str(environment))
    assert str(ROOT / "src") not in origin

    help_result = subprocess.run(
        [str(console), "--help"],
        check=True,
        cwd=tmp_path,
        env=child_environment,
        capture_output=True,
        text=True,
    )
    assert "validate" in help_result.stdout
    validate_result = subprocess.run(
        [str(console), "validate", "--json", str(SCENARIO)],
        check=True,
        cwd=tmp_path,
        env=child_environment,
        capture_output=True,
        text=True,
    )
    validate_payload = json.loads(validate_result.stdout)
    assert validate_payload["operation"] == "validate"
    assert validate_payload["payload"]["valid"] is True
    _assert_public_payload(validate_payload)

    smoke = subprocess.run(
        [
            str(python),
            str(ROOT / "tests" / "release" / "sdk_client_smoke.py"),
            "--operation",
            "health",
        ],
        check=True,
        cwd=tmp_path,
        env={
            **child_environment,
            "SCENARIOFORGE_PROJECT_ROOT": str(ROOT),
            "SCENARIOFORGE_WORKSPACE": str(tmp_path / "sdk-workspace"),
        },
        capture_output=True,
        text=True,
    )
    smoke_payload = json.loads(smoke.stdout)
    assert smoke_payload["operation"] == "health"
    assert smoke_payload["payload"]["package"] == "scenarioforge"
    assert str(ROOT / "src") not in smoke.stdout
