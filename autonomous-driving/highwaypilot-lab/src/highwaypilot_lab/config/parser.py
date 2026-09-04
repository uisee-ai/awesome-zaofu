"""Parse and expand the frozen ``construction-config/v1`` contract."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, NoReturn

from jsonschema import Draft202012Validator


UINT32_MAX = 4_294_967_295
SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "schemas"
    / "construction-config"
    / "v1.schema.json"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": "construction-config/v1",
    "scenario_id": "construction-v0",
    "road": {
        "lanes_count": 3,
        "lane_width_m": 4.0,
        "length_m": 1000.0,
        "speed_limit_mps": 30.0,
    },
    "construction": {
        "side": "right",
        "closed_lane_index": 2,
        "target_lane_index": 1,
        "zone_start_m": 260.0,
        "zone_end_m": 340.0,
        "warning_offsets_m": [120.0, 80.0, 40.0],
        "cone_spacing_m": 8.0,
    },
    "ego": {"initial_position_m": 40.0, "initial_speed_mps": 22.0},
    "traffic": {
        "vehicles_count": 12,
        "min_speed_mps": 18.0,
        "max_speed_mps": 28.0,
        "density": 1.0,
        "aggressive_fraction": 0.15,
    },
    "scenario_events": {
        "dangerous_cut_in": False,
        "cut_in_trigger_distance_m": 90.0,
        "cut_in_vehicle_speed_mps": 20.0,
    },
    "simulation": {
        "duration_s": 30.0,
        "simulation_frequency_hz": 15,
        "policy_frequency_hz": 5,
    },
    "observation": {
        "vehicles_count": 8,
        "features": ["presence", "x", "y", "vx", "vy", "heading"],
        "absolute": True,
        "normalize": False,
        "order": "sorted",
    },
    "reward": {
        "collision": -2.0,
        "speed": 0.4,
        "safe_lane": 0.25,
        "lane_change": -0.05,
        "merge_success": 2.0,
        "ttc": -0.5,
        "comfort": -0.02,
    },
}


class ConfigError(ValueError):
    """A deterministic list of field-level configuration issues."""

    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{i['path']}: {i['message']}" for i in issues))


class _DuplicateKey(ValueError):
    pass


def _raise(path: str, code: str, message: str) -> NoReturn:
    raise ConfigError([{"path": path, "code": code, "message": message}])


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite number {value}")


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _path(parts: list[object]) -> str:
    return ".".join(str(part) for part in parts) if parts else "$"


def _validate_schema(value: object) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if not errors:
        return
    issues = []
    for error in errors:
        code = "unknown_field" if error.validator == "additionalProperties" else "schema_invalid"
        issues.append(
            {
                "path": _path(list(error.absolute_path)),
                "code": code,
                "message": error.message,
            }
        )
    raise ConfigError(issues)


def _merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _validate_seed(seed: object, *, path: str = "seed") -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        _raise(path, "seed_type", "seed must be a JSON integer")
    if not 0 <= seed <= UINT32_MAX:
        _raise(path, "seed_range", f"seed must be between 0 and {UINT32_MAX}")
    return seed


def _validate_finite_numbers(value: object, path: str = "$") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _raise(path, "non_finite_number", "numbers must be finite")
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = str(key) if path == "$" else f"{path}.{key}"
            _validate_finite_numbers(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_numbers(child, f"{path}.{index}")


def _validate_semantics(config: dict[str, Any]) -> None:
    road = config["road"]
    construction = config["construction"]
    ego = config["ego"]
    traffic = config["traffic"]
    simulation = config["simulation"]

    if construction["zone_start_m"] >= construction["zone_end_m"]:
        _raise("construction.zone_end_m", "construction_zone_order", "zone_end_m must be greater than zone_start_m")
    if construction["zone_end_m"] > road["length_m"]:
        _raise("construction.zone_end_m", "construction_out_of_road", "construction zone must end within the road")
    if ego["initial_position_m"] >= construction["zone_start_m"]:
        _raise("ego.initial_position_m", "ego_after_warning", "ego must start before the construction zone")
    if traffic["min_speed_mps"] > traffic["max_speed_mps"]:
        _raise("traffic.max_speed_mps", "traffic_speed_order", "max_speed_mps must be at least min_speed_mps")
    if simulation["simulation_frequency_hz"] % simulation["policy_frequency_hz"]:
        _raise("simulation.policy_frequency_hz", "frequency_ratio", "simulation frequency must be divisible by policy frequency")
    offsets = construction["warning_offsets_m"]
    if offsets != sorted(set(offsets), reverse=True):
        _raise("construction.warning_offsets_m", "warning_offset_order", "warning offsets must be unique and strictly descending")
    if offsets and max(offsets) >= construction["zone_start_m"]:
        _raise("construction.warning_offsets_m", "warning_before_road", "warning markers must remain on the road")


def parse_config(config: Mapping[str, Any], *, api_seed: object | None = None) -> dict[str, Any]:
    """Validate input, expand every default, and enforce construction semantics."""

    if not isinstance(config, Mapping):
        _raise("$", "schema_invalid", "configuration must be a JSON object")
    if "seed" not in config:
        _raise("seed", "seed_required", "an explicit seed is required")
    _validate_finite_numbers(config)
    seed = _validate_seed(config["seed"])
    if api_seed is not None:
        external_seed = _validate_seed(api_seed, path="api_seed")
        if external_seed != seed:
            _raise("seed", "seed_mismatch", "API seed must equal effective_config.seed")

    _validate_schema(config)
    effective = _merge(DEFAULT_CONFIG, config)

    lanes_count = effective["road"]["lanes_count"]
    construction_patch = config.get("construction", {})
    side = effective["construction"]["side"]
    expected_closed = 0 if side == "left" else lanes_count - 1
    expected_target = 1 if side == "left" else lanes_count - 2
    for field, expected in (
        ("closed_lane_index", expected_closed),
        ("target_lane_index", expected_target),
    ):
        if field in construction_patch and construction_patch[field] != expected:
            _raise(
                f"construction.{field}",
                "construction_lane_mismatch",
                f"{field} is inconsistent with side and lanes_count",
            )
        effective["construction"][field] = expected

    _validate_schema(effective)
    _validate_semantics(effective)
    return effective


def parse_config_json(payload: str | bytes, *, api_seed: object | None = None) -> dict[str, Any]:
    """Strictly decode UTF-8 JSON before applying the configuration contract."""

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _raise("$", "invalid_utf8", "input is not valid UTF-8")
    if payload.startswith("\ufeff"):
        _raise("$", "invalid_json", "UTF-8 BOM is not accepted")
    try:
        parsed = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except _DuplicateKey as error:
        _raise("$", "duplicate_key", f"duplicate JSON key: {error.args[0]}")
    except (json.JSONDecodeError, ValueError):
        _raise("$", "invalid_json", "input is not strict JSON")
    return parse_config(parsed, api_seed=api_seed)
