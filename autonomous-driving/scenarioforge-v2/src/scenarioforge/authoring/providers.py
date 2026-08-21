from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from scenarioforge.core.canonical import CanonicalModel, JSONValue

from .scenario_spec import NormalizedScenarioSpec, normalize_scenario_spec


class ProviderError(RuntimeError):
    pass


class ProviderIntentError(ProviderError):
    pass


class ProviderDisabled(ProviderError):
    pass


class ScenarioDraftProvider(Protocol):
    provider_id: str

    def create_draft(self, prompt: str) -> "ProviderDraft": ...


@dataclass(frozen=True)
class ProviderDraft(CanonicalModel):
    schema_version: str
    provider_id: str
    intent_id: str
    intent_digest: str
    status: str
    normalized_spec: NormalizedScenarioSpec


_INTENTS = (
    (
        "brake_lead",
        (
            "lead vehicle braking",
            "lead vehicle brakes",
            "emergency braking",
            "前车突然急刹",
            "前车急刹",
        ),
        "Lead vehicle emergency braking",
        "corridor",
        False,
    ),
    (
        "pedestrian_red_light_crossing",
        ("pedestrian", "crosswalk", "行人"),
        "Pedestrian red-light crossing",
        "intersection",
        True,
    ),
    (
        "cross_traffic_red_light",
        ("cross traffic", "running a red", "闯红灯"),
        "Cross-traffic red-light violation",
        "intersection",
        False,
    ),
    (
        "unprotected_left_turn",
        ("unprotected left", "left turn", "无保护左转"),
        "Unprotected left turn",
        "intersection",
        False,
    ),
    (
        "competitive_lane_change",
        ("competitive lane", "lane change", "竞争换道"),
        "Competitive lane change",
        "corridor",
        False,
    ),
    (
        "highway_merge",
        ("highway merge", "joining", "高速汇入", "merge"),
        "Highway merge",
        "corridor",
        False,
    ),
)


def _benchmark_template(
    *, title: str, topology_kind: str, pedestrian: bool
) -> dict[str, Any]:
    secondary_kind = "pedestrian" if pedestrian else "vehicle"
    secondary_role = "vulnerable_road_user" if pedestrian else "social"
    secondary_profile = "walking" if pedestrian else "normal"
    secondary_dimensions = (
        {"length_m": 0.5, "width_m": 0.5, "height_m": 1.7}
        if pedestrian
        else {"length_m": 4.5, "width_m": 1.8, "height_m": 1.5}
    )
    return {
        "title": title,
        "road": {
            "topology_kind": topology_kind,
            "coordinate_system": "right-handed-x-forward-y-left",
            "units": {"distance": "m", "speed": "m/s", "heading": "deg", "time": "s"},
            "lanes": [{
                "id": "main",
                "kind": "travel",
                "length_m": 200.0,
                "width_m": 3.5,
                "speed_limit_mps": 22.0,
                "centerline": [{"x_m": 0.0, "y_m": 0.0}, {"x_m": 200.0, "y_m": 0.0}],
                "predecessor_lane_ids": [],
                "successor_lane_ids": [],
            }],
            "conflict_zones": [],
        },
        "routes": [
            {
                "id": "ego-route",
                "kind": "vehicle",
                "lane_ids": ["main"],
                "goal": {"lane_id": "main", "longitudinal_m": 180.0},
            },
            {
                "id": "secondary-route",
                "kind": secondary_kind,
                "lane_ids": ["main"],
                "goal": {"lane_id": "main", "longitudinal_m": 160.0},
            },
        ],
        "actors": [
            {
                "id": "ego",
                "kind": "vehicle",
                "role": "ego",
                "dimensions": {"length_m": 4.8, "width_m": 1.9, "height_m": 1.6},
                "spawn": {
                    "lane_id": "main",
                    "longitudinal_m": 10.0,
                    "lateral_m": 0.0,
                    "speed_mps": 12.0,
                    "heading_deg": 0.0,
                },
                "route_id": "ego-route",
                "behavior": {"profile": "deterministic"},
            },
            {
                "id": "secondary",
                "kind": secondary_kind,
                "role": secondary_role,
                "dimensions": secondary_dimensions,
                "spawn": {
                    "lane_id": "main",
                    "longitudinal_m": 45.0,
                    "lateral_m": 0.0,
                    "speed_mps": 1.2 if pedestrian else 10.0,
                    "heading_deg": 0.0,
                },
                "route_id": "secondary-route",
                "behavior": {"profile": secondary_profile},
            },
        ],
        "constraints": {
            "collision_is_failure": True,
            "success_conditions": [{
                "id": "ego-arrives",
                "kind": "route_completed",
                "actor_ids": ["ego"],
                "route_id": "ego-route",
                "threshold": None,
            }],
            "failure_conditions": [{
                "id": "collision",
                "kind": "collision",
                "actor_ids": ["ego", "secondary"],
                "route_id": None,
                "threshold": None,
            }],
            "safety": {"minimum_separation_m": 1.0, "max_deceleration_mps2": 10.0},
        },
        "required_capabilities": [
            "actor.vehicle",
            "actor.pedestrian" if pedestrian else "route.stable-id",
        ],
    }


class OfflineReferenceProvider:
    provider_id = "scenarioforge.offline-reference"

    def create_draft(self, prompt: str) -> ProviderDraft:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderIntentError("prompt must identify a supported benchmark intent")
        lowered = prompt.casefold()
        match = next(
            (item for item in _INTENTS if any(token in lowered for token in item[1])),
            None,
        )
        if match is None:
            raise ProviderIntentError("prompt does not identify a supported benchmark intent")
        intent_id, _tokens, title, topology_kind, pedestrian = match
        value = _benchmark_template(
            title=title,
            topology_kind=topology_kind,
            pedestrian=pedestrian,
        )
        leaves = _leaf_paths(value)
        explicit = {"$.title", "$.road.topology_kind"}
        normalized = normalize_scenario_spec(
            value,
            explicit_paths=explicit,
            inferred_paths=leaves - explicit,
        )
        return ProviderDraft(
            schema_version="scenarioforge.provider-draft/v1",
            provider_id=self.provider_id,
            intent_id=intent_id,
            intent_digest=hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest(),
            status=(
                "needs_correction"
                if normalized.missing_fields
                else "needs_confirmation"
            ),
            normalized_spec=normalized,
        )


class ProviderRegistry:
    def __init__(self, providers: tuple[ScenarioDraftProvider, ...]) -> None:
        registrations = {provider.provider_id: provider for provider in providers}
        if not registrations or len(registrations) != len(providers):
            raise ValueError("Provider registrations must be non-empty and unique")
        if any(not provider_id for provider_id in registrations):
            raise ValueError("Provider IDs must be non-empty")
        self._providers = registrations

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def create_draft(self, provider_id: str, prompt: str) -> ProviderDraft:
        try:
            provider = self._providers[provider_id]
        except KeyError as error:
            raise ProviderIntentError(
                f"Provider is disabled or not registered: {provider_id}"
            ) from error
        return provider.create_draft(prompt)


def _leaf_paths(value: object, path: str = "$") -> set[str]:
    if isinstance(value, Mapping):
        if not value:
            return {path}
        result: set[str] = set()
        for key, item in value.items():
            result.update(_leaf_paths(item, f"{path}.{key}"))
        return result
    if isinstance(value, (list, tuple)):
        if not value:
            return {path}
        result = set()
        for index, item in enumerate(value):
            result.update(_leaf_paths(item, f"{path}[{index}]"))
        return result
    return {path}


_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9+.-])/(?:[^\s,;\"']+)")
_SECRET = re.compile(r"(?i)\b(?:sk|key|token|bearer)[-_][A-Za-z0-9._-]{4,}\b")
_LABELED_SECRET = re.compile(
    r"(?i)\b(?:authorization|cookie|password|secret|token)\s*[:=]\s*\S+"
)


def _redact_provider_text(value: str) -> str:
    sanitized = _ABSOLUTE_PATH.sub("<redacted-path>", value)
    sanitized = _LABELED_SECRET.sub("<redacted-secret>", sanitized)
    sanitized = _SECRET.sub("<redacted-secret>", sanitized)
    environment_values = sorted(
        {item for item in os.environ.values() if len(item) >= 8},
        key=len,
        reverse=True,
    )
    for environment_value in environment_values:
        sanitized = sanitized.replace(
            environment_value, "<redacted-environment-value>"
        )
    return sanitized


@dataclass(frozen=True)
class CloudProviderPolicy:
    provider_id: str
    enabled: bool = False
    allowed_fields: tuple[str, ...] = ()

    @property
    def displayed_send_scope(self) -> tuple[str, ...]:
        return self.allowed_fields

    def prepare_egress(self, value: Mapping[str, Any]) -> dict[str, JSONValue]:
        if not self.enabled:
            raise ProviderDisabled(f"cloud Provider is disabled: {self.provider_id}")
        payload: dict[str, JSONValue] = {}
        for field in self.allowed_fields:
            item = value.get(field)
            if item is None or isinstance(item, (bool, int, float)):
                payload[field] = item
            elif isinstance(item, str):
                payload[field] = _redact_provider_text(item)
            else:
                raise ProviderError(
                    f"cloud Provider field is not a bounded scalar: {field}"
                )
        return payload


__all__ = [
    "CloudProviderPolicy",
    "OfflineReferenceProvider",
    "ProviderDisabled",
    "ProviderDraft",
    "ProviderError",
    "ProviderIntentError",
    "ProviderRegistry",
    "ScenarioDraftProvider",
]
