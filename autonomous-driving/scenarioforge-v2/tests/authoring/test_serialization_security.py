from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.authoring.serialization import (
    SerializationError,
    SerializationLimits,
    import_authoring,
)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"value: !!str tagged\n", "tag_forbidden"),
        (b"value: &shared anchored\n", "anchor_forbidden"),
        (b"value: *missing\n", "alias_forbidden"),
        (b"<<: {}\n", "merge_key_forbidden"),
        (b"---\n{}\n---\n{}\n", "multiple_documents_forbidden"),
        (b"value: first\nvalue: second\n", "duplicate_key"),
        (b"value: .nan\n", "non_finite_number"),
        (b"value: 2026-08-13\n", "non_json_scalar"),
        (b"value: !!binary c2VjcmV0\n", "tag_forbidden"),
    ],
)
def test_yaml_subset_rejects_each_unsafe_construct(
    payload: bytes,
    code: str,
) -> None:
    with pytest.raises(SerializationError) as caught:
        import_authoring(payload, format="yaml")

    assert caught.value.stage == "safe_yaml"
    assert caught.value.code == code
    assert caught.value.path == "$"
    assert payload.decode("utf-8").strip() not in str(caught.value)


def test_yaml_attack_text_is_never_reflected_in_error() -> None:
    marker = "DO_NOT_REFLECT_SECRET_MARKER"
    payload = (
        "value: !!python/object/apply:os.system "
        f"['{marker}']\n"
    ).encode("utf-8")

    with pytest.raises(SerializationError) as caught:
        import_authoring(payload, format="yaml")

    assert caught.value.code == "tag_forbidden"
    assert marker not in str(caught.value)
    assert marker not in repr(caught.value)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"\x1f\x8bcompressed", "compressed_content_forbidden"),
        (b"PK\x03\x04archive", "compressed_content_forbidden"),
        (b"BZhcompressed", "compressed_content_forbidden"),
        (b"\xfd7zXZ\x00compressed", "compressed_content_forbidden"),
    ],
)
def test_import_rejects_compressed_or_archive_content(
    payload: bytes,
    code: str,
) -> None:
    with pytest.raises(SerializationError) as caught:
        import_authoring(payload, format="yaml")

    assert (caught.value.stage, caught.value.code, caught.value.path) == (
        "content_boundary",
        code,
        "$",
    )


@pytest.mark.parametrize(
    "payload",
    [
        Path("/tmp/server-owned.yaml"),
        "file:///tmp/server-owned.yaml",
        "https://example.invalid/scenario.yaml",
        "../client-controlled/scenario.yaml",
    ],
)
def test_import_rejects_paths_urls_and_client_storage_references(
    payload: object,
) -> None:
    with pytest.raises(SerializationError) as caught:
        import_authoring(payload, format="yaml")

    assert (caught.value.stage, caught.value.code, caught.value.path) == (
        "content_boundary",
        "content_only_required",
        "$",
    )


def test_yaml_parser_depth_and_event_budgets_fail_before_construction() -> None:
    with pytest.raises(SerializationError) as depth:
        import_authoring(
            b"[[[[null]]]]\n",
            format="yaml",
            limits=SerializationLimits(max_depth=3),
        )
    assert (depth.value.stage, depth.value.code) == (
        "resource_budget",
        "max_depth_exceeded",
    )

    with pytest.raises(SerializationError) as events:
        import_authoring(
            b"[null, null, null]\n",
            format="yaml",
            limits=SerializationLimits(max_parse_events=4),
        )
    assert (events.value.stage, events.value.code) == (
        "resource_budget",
        "parse_events_exceeded",
    )


@pytest.mark.parametrize(
    ("payload", "limits", "code"),
    [
        (
            b"a: 1\nb: 2\n",
            SerializationLimits(max_object_members=1),
            "object_members_exceeded",
        ),
        (
            b"- 1\n- 2\n",
            SerializationLimits(max_array_items=1),
            "array_items_exceeded",
        ),
        (
            b"value: 12345\n",
            SerializationLimits(max_string_bytes=4),
            "string_bytes_exceeded",
        ),
        (
            b"value: 1001\n",
            SerializationLimits(max_absolute_number=1000),
            "number_range_exceeded",
        ),
    ],
)
def test_yaml_conversion_enforces_structure_and_scalar_budgets(
    payload: bytes,
    limits: SerializationLimits,
    code: str,
) -> None:
    with pytest.raises(SerializationError) as caught:
        import_authoring(payload, format="yaml", limits=limits)

    assert caught.value.stage == "resource_budget"
    assert caught.value.code == code


def test_invalid_utf8_and_invalid_yaml_have_stable_sanitized_errors() -> None:
    cases = [
        (b"\xff\xfe", "invalid_utf8"),
        (b"value: [unterminated\n", "invalid_yaml"),
    ]

    for payload, code in cases:
        with pytest.raises(SerializationError) as caught:
            import_authoring(payload, format="yaml")
        assert caught.value.stage == "safe_yaml"
        assert caught.value.code == code
        assert caught.value.path == "$"
        assert payload.hex() not in str(caught.value)
