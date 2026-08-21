from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scenarioforge.core import (
    CompilationStatus,
    InputLimits,
    ScenarioCompiler,
    StrictJSONError,
    canonical_digest,
    instantiate_scenario,
    load_scenario,
    strict_loads,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "p0a" / "brake_lead.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "p0a" / "happy"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_nofollow_limited_pipeline_produces_exact_immutable_instance() -> None:
    document = load_scenario(EXAMPLE)
    instance = instantiate_scenario(document)

    assert document.raw_digest == "7ae9e59862227c9423efa6f499d40406e22177f4978a4eaa5c7947577988b961"
    assert document.canonical_digest == "628e8a458de35889fc1fe80e93aa69abd9a43ae25db438cbb56eb5efa4170498"
    assert instance.to_dict() == _fixture("scenario_instance.json")
    assert instance.digest == canonical_digest(_fixture("scenario_instance.json"))

    with pytest.raises(TypeError):
        instance.road["lane_count"] = 3  # type: ignore[index]
    with pytest.raises(TypeError):
        instance.participants[0]["id"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b'{"a": 1, // comment\n"b": 2}', "invalid_json"),
        (b'{"a": 1,}', "invalid_json"),
        (b'{"a": 1, "a": 2}', "duplicate_key"),
        (b'{"a": NaN}', "non_finite_number"),
        (b'{"a": Infinity}', "non_finite_number"),
        (b"{'a': 1}", "invalid_json"),
    ],
)
def test_strict_parse_rejects_non_json_before_schema(payload: bytes, code: str) -> None:
    with pytest.raises(StrictJSONError) as caught:
        strict_loads(payload)

    assert caught.value.stage == "strict_parse"
    assert caught.value.code == code
    assert caught.value.path == "$"


def test_reader_rejects_symlink_directory_and_byte_limit(tmp_path: Path) -> None:
    regular = tmp_path / "scenario.json"
    regular.write_bytes(EXAMPLE.read_bytes())
    link = tmp_path / "scenario-link.json"
    link.symlink_to(regular)

    with pytest.raises(StrictJSONError, match="regular file") as link_error:
        load_scenario(link)
    assert link_error.value.code == "not_regular_file"

    with pytest.raises(StrictJSONError, match="regular file") as directory_error:
        load_scenario(tmp_path)
    assert directory_error.value.code == "not_regular_file"

    with pytest.raises(StrictJSONError, match="byte limit") as size_error:
        load_scenario(regular, limits=InputLimits(byte_limit=64))
    assert size_error.value.code == "byte_limit_exceeded"

    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "input.fifo"
        os.mkfifo(fifo)
        with pytest.raises(StrictJSONError, match="regular file"):
            load_scenario(fifo)


@pytest.mark.parametrize(
    ("mutation", "code", "path"),
    [
        (lambda value: value.update({"unknown": True}), "schema_validation_failed", "$"),
        (
            lambda value: value["road"].update({"unknown": True}),
            "schema_validation_failed",
            "$.road",
        ),
        (
            lambda value: value["participants"][0]["initial"].update({"lane": 9}),
            "schema_validation_failed",
            "$.participants[0].initial.lane",
        ),
        (
            lambda value: value["policy"].update({"id": "/tmp/evil.py"}),
            "forbidden_content",
            "$.policy.id",
        ),
        (
            lambda value: value["backend_extensions"].update({"schema_version": "wrong"}),
            "schema_validation_failed",
            "$.backend_extensions.schema_version",
        ),
    ],
)
def test_schema_rejects_unknown_out_of_range_and_forbidden_content(
    tmp_path: Path,
    mutation,
    code: str,
    path: str,
) -> None:
    value = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    mutation(value)
    candidate = tmp_path / "candidate.json"
    _write_json(candidate, value)

    with pytest.raises(StrictJSONError) as caught:
        load_scenario(candidate)

    assert caught.value.stage == "schema_validation"
    assert caught.value.code == code
    assert caught.value.path == path


def test_structure_limits_reject_depth_members_arrays_strings_and_numbers(tmp_path: Path) -> None:
    base = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    cases = []

    deep = json.loads(json.dumps(base))
    deep["backend_extensions"]["extensions"]["future"] = {
        "schema_version": "future/v1",
        "options": {"a": {"b": {"c": {"d": 1}}}},
    }
    cases.append((deep, InputLimits(max_depth=8), "max_depth_exceeded"))

    members = json.loads(json.dumps(base))
    members["backend_extensions"]["extensions"]["future"] = {
        "schema_version": "future/v1",
        "options": {f"k{i}": i for i in range(9)},
    }
    cases.append((members, InputLimits(max_object_members=8), "object_members_exceeded"))

    array = json.loads(json.dumps(base))
    array["required_capabilities"] = [f"capability-{i}" for i in range(10)]
    cases.append((array, InputLimits(max_array_items=9), "array_items_exceeded"))

    string = json.loads(json.dumps(base))
    string["scenario_id"] = "x" * 33
    cases.append((string, InputLimits(max_string_bytes=32), "string_bytes_exceeded"))

    number = json.loads(json.dumps(base))
    number["road"]["length_m"] = 1_000_001
    cases.append((number, InputLimits(max_absolute_number=1_000_000), "number_range_exceeded"))

    for index, (value, limits, code) in enumerate(cases):
        candidate = tmp_path / f"limited-{index}.json"
        _write_json(candidate, value)
        with pytest.raises(StrictJSONError) as caught:
            load_scenario(candidate, limits=limits)
        assert caught.value.stage == "schema_validation"
        assert caught.value.code == code


def test_unknown_backend_extension_is_serializable_but_blocks_execution(tmp_path: Path) -> None:
    value = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    value["backend_extensions"]["extensions"]["future_backend"] = {
        "schema_version": "future-backend/v1",
        "options": {"mode": "strict"},
    }
    candidate = tmp_path / "future-extension.json"
    _write_json(candidate, value)

    instance = instantiate_scenario(load_scenario(candidate))
    bundle = ScenarioCompiler().compile(instance)

    assert bundle.report.overall_status is CompilationStatus.UNSUPPORTED
    assert bundle.report.executable is False
    assert bundle.execution_plan is None
    assert [item.to_dict() for item in bundle.report.diagnostics] == [
        {
            "path": "$.backend_extensions.extensions.future_backend",
            "capability": "backend-extension.future_backend",
            "status": "unsupported",
            "reason": "extension namespace is not supported by the MetaDrive adapter",
            "alternative": "remove the extension and express the scenario with the P0-A core",
        }
    ]


def test_non_default_lane_width_is_lossy_and_fails_closed(tmp_path: Path) -> None:
    value = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    value["road"]["lane_width_m"] = 3.2
    candidate = tmp_path / "lossy-width.json"
    _write_json(candidate, value)

    bundle = ScenarioCompiler().compile(instantiate_scenario(load_scenario(candidate)))

    assert bundle.report.overall_status is CompilationStatus.LOSSY
    assert bundle.report.executable is False
    assert bundle.execution_plan is None
    assert [item.to_dict() for item in bundle.report.diagnostics] == [
        {
            "path": "$.road.lane_width_m",
            "capability": "road.lane-width.3.5m",
            "status": "lossy",
            "reason": "MetaDrive P0-A is frozen to a 3.5 m lane width",
            "alternative": "set road.lane_width_m to 3.5",
        }
    ]
