import json
import hashlib
from pathlib import Path

import pytest
import rfc8785

from highwaypilot_lab.config import ConfigError, parse_config, parse_config_json


PRESET_ROOT = Path("configs/presets")
EXPECTED_PRESETS = {
    "normal-v1.json",
    "congested-v1.json",
    "aggressive-v1.json",
    "dangerous-cut-in-v1.json",
}
EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "scenario_id",
    "seed",
    "road",
    "construction",
    "ego",
    "traffic",
    "scenario_events",
    "simulation",
    "observation",
    "reward",
}
EXPECTED_PRESET_DIGESTS = {
    "aggressive-v1.json": "b914be62f7a51d15bbe62e48ed52db83b1526e62796ffd352fa28fd1927936a3",
    "congested-v1.json": "67ea9b773cca1d326cb2453397bc23a9a0ad6145587093d2ed209f8de79a4f1a",
    "dangerous-cut-in-v1.json": "a1a234de09ebd6e36fb72b899fbeb9cc15150e0eaeb25cd1d52c7968c118eb75",
    "normal-v1.json": "6a021197a9241735b7345edc16e9f4cf31f52a03ea8ecb7442d01968cfa4c6d1",
}


def minimal_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "schema_version": "construction-config/v1",
        "scenario_id": "construction-v0",
        "seed": 7,
    }
    config.update(overrides)
    return config


def test_minimal_input_expands_to_a_complete_effective_config() -> None:
    effective = parse_config(minimal_config())

    assert set(effective) == EXPECTED_TOP_LEVEL_FIELDS
    assert effective["road"] == {
        "lanes_count": 3,
        "lane_width_m": 4.0,
        "length_m": 1000.0,
        "speed_limit_mps": 30.0,
    }
    assert effective["construction"] == {
        "side": "right",
        "closed_lane_index": 2,
        "target_lane_index": 1,
        "zone_start_m": 260.0,
        "zone_end_m": 340.0,
        "warning_offsets_m": [120.0, 80.0, 40.0],
        "cone_spacing_m": 8.0,
    }
    assert effective["observation"]["features"] == [
        "presence",
        "x",
        "y",
        "vx",
        "vy",
        "heading",
    ]


@pytest.mark.parametrize(
    ("construction", "path"),
    [
        ({"side": "left", "closed_lane_index": 2}, "construction.closed_lane_index"),
        ({"side": "left", "target_lane_index": 0}, "construction.target_lane_index"),
        ({"side": "right", "closed_lane_index": 0}, "construction.closed_lane_index"),
        ({"side": "right", "target_lane_index": 2}, "construction.target_lane_index"),
    ],
)
def test_inconsistent_side_and_lane_fields_are_rejected_without_repair(
    construction: dict[str, object], path: str
) -> None:
    with pytest.raises(ConfigError) as raised:
        parse_config(minimal_config(construction=construction))

    assert raised.value.issues[0]["path"] == path
    assert raised.value.issues[0]["code"] == "construction_lane_mismatch"


@pytest.mark.parametrize("lanes_count", [2, 3, 4, 5])
@pytest.mark.parametrize(
    ("side", "closed_offset", "target_offset"),
    [("left", 0, 1), ("right", -1, -2)],
)
def test_outer_lane_defaults_are_derived_for_every_supported_road_width(
    lanes_count: int, side: str, closed_offset: int, target_offset: int
) -> None:
    effective = parse_config(
        minimal_config(
            road={"lanes_count": lanes_count},
            construction={"side": side},
        )
    )

    expected_closed = closed_offset if closed_offset >= 0 else lanes_count + closed_offset
    expected_target = target_offset if target_offset >= 0 else lanes_count + target_offset
    assert effective["construction"]["closed_lane_index"] == expected_closed
    assert effective["construction"]["target_lane_index"] == expected_target


@pytest.mark.parametrize(
    "payload",
    [
        '{"schema_version":"construction-config/v1","scenario_id":"construction-v0","seed":1,"seed":2}',
        '{"schema_version":"construction-config/v1","scenario_id":"construction-v0","seed":1,"x":NaN}',
        '{"schema_version":"construction-config/v1","scenario_id":"construction-v0","seed":1,"x":Infinity}',
        '{"schema_version":"construction-config/v1","scenario_id":"construction-v0","seed":1,"reward":{"speed":1e400}}',
    ],
)
def test_json_parser_rejects_duplicate_keys_and_non_finite_numbers(payload: str) -> None:
    with pytest.raises(ConfigError):
        parse_config_json(payload)


def test_json_parser_rejects_invalid_utf8() -> None:
    with pytest.raises(ConfigError) as raised:
        parse_config_json(b"\xff")

    assert raised.value.issues == [
        {"path": "$", "code": "invalid_utf8", "message": "input is not valid UTF-8"}
    ]


@pytest.mark.parametrize("seed", [True, False, 1.5, "1", -1, 4294967296])
def test_seed_type_and_range_fail_closed(seed: object) -> None:
    with pytest.raises(ConfigError) as raised:
        parse_config(minimal_config(seed=seed))

    assert raised.value.issues[0]["path"] == "seed"


def test_external_seed_must_exactly_match_effective_seed() -> None:
    with pytest.raises(ConfigError) as raised:
        parse_config(minimal_config(seed=42), api_seed=43)

    assert raised.value.issues == [
        {
            "path": "seed",
            "code": "seed_mismatch",
            "message": "API seed must equal effective_config.seed",
        }
    ]


def test_unknown_and_camel_case_fields_are_rejected() -> None:
    with pytest.raises(ConfigError) as raised:
        parse_config(minimal_config(road={"lanesCount": 4}))

    assert raised.value.issues[0]["path"] == "road"
    assert raised.value.issues[0]["code"] == "unknown_field"


def test_all_versioned_presets_are_complete_exact_fixtures() -> None:
    assert {path.name for path in PRESET_ROOT.glob("*.json")} == EXPECTED_PRESETS

    for path in sorted(PRESET_ROOT.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert set(raw) == EXPECTED_TOP_LEVEL_FIELDS
        assert raw["observation"]["features"] == [
            "presence",
            "x",
            "y",
            "vx",
            "vy",
            "heading",
        ]
        assert raw["construction"]["warning_offsets_m"] == [120.0, 80.0, 40.0]
        assert parse_config(raw) == raw
        assert hashlib.sha256(rfc8785.dumps(raw)).hexdigest() == EXPECTED_PRESET_DIGESTS[path.name]


def test_preset_characteristics_are_distinct_and_explicit() -> None:
    presets = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in PRESET_ROOT.glob("*.json")
    }

    assert presets["congested-v1"]["traffic"]["vehicles_count"] == 24
    assert presets["congested-v1"]["traffic"]["max_speed_mps"] == 18.0
    assert presets["aggressive-v1"]["traffic"]["aggressive_fraction"] == 0.8
    assert presets["aggressive-v1"]["traffic"]["max_speed_mps"] == 33.0
    assert presets["dangerous-cut-in-v1"]["scenario_events"]["dangerous_cut_in"] is True
    assert presets["normal-v1"]["scenario_events"]["dangerous_cut_in"] is False
