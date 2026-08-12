from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.spec import canonical_scenario, export_scenario, load_scenario


SAMPLES_ROOT = Path(__file__).parents[2] / "samples"
CATALOG = json.loads((SAMPLES_ROOT / "catalog.json").read_text(encoding="utf-8"))


def test_catalog_exposes_the_committed_metadrive_scenarios() -> None:
    assert CATALOG["backend"] == "metadrive-simulator"
    assert [sample["id"] for sample in CATALOG["samples"]] == [
        "following",
        "following-emergency-brake",
        "merge",
        "lane-conflict",
        "intersection",
        "static-obstacle-avoidance",
    ]


@pytest.mark.parametrize("sample", CATALOG["samples"], ids=lambda sample: sample["id"])
def test_every_catalog_sample_has_equal_json_and_yaml_canonical_round_trips(sample: dict[str, str]) -> None:
    json_scenario = load_scenario(
        (SAMPLES_ROOT / sample["json"]).read_text(encoding="utf-8"), "application/json"
    )
    yaml_scenario = load_scenario(
        (SAMPLES_ROOT / sample["yaml"]).read_text(encoding="utf-8"), "application/yaml"
    )

    assert canonical_scenario(json_scenario) == canonical_scenario(yaml_scenario)
    assert load_scenario(export_scenario(json_scenario, "json"), "application/json") == json_scenario
    assert load_scenario(export_scenario(yaml_scenario, "yaml"), "application/yaml") == yaml_scenario
