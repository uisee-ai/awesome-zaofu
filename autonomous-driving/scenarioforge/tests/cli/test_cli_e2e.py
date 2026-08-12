from __future__ import annotations

import json
from pathlib import Path

from scenarioforge.app import main


def test_cli_lists_samples_validates_and_verifies_replay(capsys) -> None:
    assert main(["samples", "list"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert catalog["backend"] == "metadrive-simulator"

    assert main(["validate", "samples/following.json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["digest"]) == 64

    assert main(["replay", "verify", "--bundle", "evidence/runtime/metadrive-smoke/bundle"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"


def test_cli_compile_uses_the_run_request_file(tmp_path: Path, capsys) -> None:
    request = {
        "schema_version": "scenarioforge.run-request.v1",
        "scenario_digest": "0" * 64,
        "seeds": [17],
        "profile": "default",
        "limits": {
            "workers": 1,
            "aggregate_cpu_threads": 2,
            "max_steps": 20,
            "max_simulated_seconds": 30.0,
            "case_wall_seconds": 60.0,
            "bundle_wall_seconds": 600.0,
            "bundle_disk_bytes": 1073741824,
        },
    }
    scenario_path = Path("samples/following-emergency-brake.json")
    scenario = json.loads(scenario_path.read_text())
    from scenarioforge.spec import canonical_scenario, load_scenario

    request["scenario_digest"] = canonical_scenario(
        load_scenario(json.dumps(scenario), "application/json")
    ).digest
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")

    assert main(["compile", str(scenario_path), "--request", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["backend"]["version"] == "0.4.3"
