from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scenarioforge.authoring.serialization import (
    ImportedAuthoringDocument,
    SerializationError,
    SerializationLimits,
    export_authoring,
    import_authoring,
)
from scenarioforge.core.canonical import canonical_bytes, thaw_json


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "authoring" / "valid_scenario.json"
EXPECTED_CANONICAL_DIGEST = (
    "2359f10985de5892f4353230813e9d0d380f0041508c3ddda98d56f4dd5e2f9a"
)


@pytest.fixture
def valid_scenario() -> dict[str, Any]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_json_and_yaml_share_exact_schema_and_canonical_identity(
    valid_scenario: dict[str, Any],
) -> None:
    json_payload = json.dumps(
        valid_scenario,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")

    from_json = import_authoring(json_payload, format="json")
    yaml_payload = export_authoring(from_json, format="yaml")
    from_yaml = import_authoring(yaml_payload, format="yaml")

    assert isinstance(from_json, ImportedAuthoringDocument)
    assert from_json.source_format == "json"
    assert from_yaml.source_format == "yaml"
    assert thaw_json(from_json.value) == valid_scenario
    assert thaw_json(from_yaml.value) == valid_scenario
    assert from_json.validation.to_dict() == {
        "schema_version": "scenarioforge.authoring-validation/v1",
        "document_schema_version": "scenarioforge.authoring/v1",
        "valid": True,
        "overall_status": "exact",
        "diagnostics": [],
    }
    assert from_yaml.validation.to_dict() == from_json.validation.to_dict()
    assert from_json.canonical_payload == canonical_bytes(valid_scenario)
    assert from_yaml.canonical_payload == from_json.canonical_payload
    assert from_json.canonical_digest == EXPECTED_CANONICAL_DIGEST
    assert from_yaml.canonical_digest == EXPECTED_CANONICAL_DIGEST


def test_exports_are_bounded_deterministic_content_only_bytes(
    valid_scenario: dict[str, Any],
) -> None:
    expected_json = canonical_bytes(valid_scenario)

    json_payload = export_authoring(valid_scenario, format="json")
    yaml_payload = export_authoring(valid_scenario, format="yaml")

    assert json_payload == expected_json
    assert export_authoring(valid_scenario, format="json") == json_payload
    assert export_authoring(valid_scenario, format="yaml") == yaml_payload
    assert yaml_payload.endswith(b"\n")
    assert b"&id" not in yaml_payload
    assert b"!!python" not in yaml_payload
    assert import_authoring(json_payload, format="json").canonical_digest == (
        EXPECTED_CANONICAL_DIGEST
    )
    assert import_authoring(yaml_payload, format="yaml").canonical_digest == (
        EXPECTED_CANONICAL_DIGEST
    )

    with pytest.raises(SerializationError) as too_large:
        export_authoring(
            valid_scenario,
            format="json",
            limits=SerializationLimits(byte_limit=len(expected_json) - 1),
        )
    assert (too_large.value.stage, too_large.value.code, too_large.value.path) == (
        "bounded_export",
        "byte_limit_exceeded",
        "$",
    )


@pytest.mark.parametrize(
    ("value", "expected_code"),
    [
        (Path("scenario.yaml"), "content_only_required"),
        ("https://example.invalid/scenario.yaml", "content_only_required"),
        (b"PK\x03\x04archive", "content_only_required"),
    ],
)
def test_export_rejects_paths_urls_and_archives(
    value: object,
    expected_code: str,
) -> None:
    with pytest.raises(SerializationError) as caught:
        export_authoring(value, format="yaml")

    assert (caught.value.stage, caught.value.code, caught.value.path) == (
        "content_boundary",
        expected_code,
        "$",
    )


@pytest.mark.parametrize(
    ("format", "payload", "limits", "code", "path"),
    [
        (
            "json",
            b'{"ignored":"payload that must not be parsed"}',
            SerializationLimits(byte_limit=8),
            "byte_limit_exceeded",
            "$",
        ),
        (
            "json",
            b'{"a":{"b":{"c":null}}}',
            SerializationLimits(max_depth=3),
            "max_depth_exceeded",
            "$.a.b.c",
        ),
        (
            "json",
            b'{"a":1,"b":2}',
            SerializationLimits(max_object_members=1),
            "object_members_exceeded",
            "$",
        ),
        (
            "json",
            b"[1,2]",
            SerializationLimits(max_array_items=1),
            "array_items_exceeded",
            "$",
        ),
        (
            "json",
            b'{"a":"12345"}',
            SerializationLimits(max_string_bytes=4),
            "string_bytes_exceeded",
            "$.a",
        ),
        (
            "json",
            b'{"a":1001}',
            SerializationLimits(max_absolute_number=1000),
            "number_range_exceeded",
            "$.a",
        ),
        (
            "json",
            b'{"a":1,"b":2}',
            SerializationLimits(max_parse_events=2),
            "parse_events_exceeded",
            "$",
        ),
    ],
)
def test_import_enforces_every_budget_before_schema_validation(
    format: str,
    payload: bytes,
    limits: SerializationLimits,
    code: str,
    path: str,
) -> None:
    with pytest.raises(SerializationError) as caught:
        import_authoring(payload, format=format, limits=limits)

    assert (caught.value.stage, caught.value.code, caught.value.path) == (
        "resource_budget",
        code,
        path,
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b'{"a":1,"a":2}', "duplicate_key"),
        (b'{"a":NaN}', "non_finite_number"),
        (b'{"a":Infinity}', "non_finite_number"),
        (b'{"a":1,}', "invalid_json"),
    ],
)
def test_json_import_is_strict_and_returns_sanitized_codes(
    payload: bytes,
    code: str,
) -> None:
    with pytest.raises(SerializationError) as caught:
        import_authoring(payload, format="json")

    assert (caught.value.stage, caught.value.code, caught.value.path) == (
        "strict_json",
        code,
        "$",
    )
    assert payload.decode("utf-8") not in str(caught.value)


def test_import_does_not_mutate_callers_and_invalid_schema_fails_closed(
    valid_scenario: dict[str, Any],
) -> None:
    original = copy.deepcopy(valid_scenario)
    invalid = copy.deepcopy(valid_scenario)
    invalid["schema_version"] = "scenarioforge.authoring/future"

    imported = import_authoring(
        json.dumps(valid_scenario).encode("utf-8"),
        format="json",
    )

    assert valid_scenario == original
    assert thaw_json(imported.value) == original

    with pytest.raises(SerializationError) as caught:
        import_authoring(json.dumps(invalid).encode("utf-8"), format="json")
    assert (caught.value.stage, caught.value.code, caught.value.path) == (
        "authoring_validation",
        "schema_validation_failed",
        "$.schema_version",
    )
    assert "future" not in str(caught.value)
