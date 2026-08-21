from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from scenarioforge.core.canonical import (
    CanonicalModel,
    JSONValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)

from .defensive import DEFENSIVE_CONSTANTS


BASELINE_POLICY_ID = "scenarioforge.deterministic-control"
BASELINE_POLICY_VERSION = "2.0.0"
CANDIDATE_POLICY_ID = "scenarioforge.defensive-control"
CANDIDATE_POLICY_VERSION = "1.0.0"
POLICY_BINDING_SCHEMA_VERSION = "scenarioforge.policy-binding/v1"
BOUND_EXECUTION_SCHEMA_VERSION = "scenarioforge.bound-policy-execution/v1"
BUILTIN_PROVIDER = "scenarioforge.builtin-policy/v1"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ACTION_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["steering", "throttle_brake"],
        "properties": {
            "steering": {"type": "number", "minimum": -1.0, "maximum": 1.0},
            "throttle_brake": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
            },
        },
    }
)
BASELINE_CONFIG_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["default_action", "participant_actions"],
        "properties": {
            "default_action": _ACTION_SCHEMA,
            "participant_actions": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "participant_id",
                        "steering",
                        "throttle_brake",
                    ],
                    "properties": {
                        "participant_id": {"type": "string", "minLength": 1},
                        "steering": {
                            "type": "number",
                            "minimum": -1.0,
                            "maximum": 1.0,
                        },
                        "throttle_brake": {
                            "type": "number",
                            "minimum": -1.0,
                            "maximum": 1.0,
                        },
                    },
                },
            },
        },
    }
)
CANDIDATE_CONFIG_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["profile"],
        "properties": {"profile": {"const": "defensive-v1"}},
    }
)
CANDIDATE_CONFIG: Mapping[str, str] = MappingProxyType(
    {"profile": "defensive-v1"}
)


class PolicyAdmissionError(ValueError):
    pass


def _action(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != {"steering", "throttle_brake"}:
        raise PolicyAdmissionError(f"{label} has an unknown or missing field")
    for field in ("steering", "throttle_brake"):
        number = value[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise PolicyAdmissionError(f"{label}.{field} must be numeric")
        if not math.isfinite(float(number)) or not -1.0 <= float(number) <= 1.0:
            raise PolicyAdmissionError(f"{label}.{field} is outside [-1, 1]")


def _baseline_config(value: Any) -> Mapping[str, JSONValue]:
    if not isinstance(value, Mapping) or set(value) != {
        "default_action",
        "participant_actions",
    }:
        raise PolicyAdmissionError("baseline config has an unknown or missing field")
    _action(value["default_action"], "baseline default_action")
    participant_actions = value["participant_actions"]
    if not isinstance(participant_actions, (list, tuple)) or len(participant_actions) > 16:
        raise PolicyAdmissionError("baseline participant_actions is invalid")
    seen: set[str] = set()
    for index, item in enumerate(participant_actions):
        if not isinstance(item, Mapping) or set(item) != {
            "participant_id",
            "steering",
            "throttle_brake",
        }:
            raise PolicyAdmissionError("baseline participant action is invalid")
        participant_id = item["participant_id"]
        if not isinstance(participant_id, str) or not participant_id or participant_id in seen:
            raise PolicyAdmissionError("baseline participant identity is invalid")
        _action(
            {
                "steering": item["steering"],
                "throttle_brake": item["throttle_brake"],
            },
            f"baseline participant_actions[{index}]",
        )
        seen.add(participant_id)
    frozen = freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


def _candidate_config(value: Any) -> Mapping[str, JSONValue]:
    if value != {"profile": "defensive-v1"}:
        raise PolicyAdmissionError("candidate config must be exactly defensive-v1")
    frozen = freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


@lru_cache(maxsize=2)
def _implementation_digest(role: str) -> str:
    package_root = Path(__file__).resolve().parents[1]
    path = (
        package_root / "runtime" / "policy.py"
        if role == "baseline"
        else Path(__file__).resolve().with_name("defensive.py")
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PolicyBinding(CanonicalModel):
    schema_version: str
    role: str
    id: str
    version: str
    provider: str
    config_schema: Mapping[str, JSONValue]
    config_schema_digest: str
    config: Mapping[str, JSONValue]
    configuration_digest: str
    constants: Mapping[str, JSONValue]
    constants_digest: str
    implementation_code_digest: str
    dynamic_code: bool
    network_access: bool
    runtime_override: bool

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyBinding":
        fields = {
            "schema_version",
            "role",
            "id",
            "version",
            "provider",
            "config_schema",
            "config_schema_digest",
            "config",
            "configuration_digest",
            "constants",
            "constants_digest",
            "implementation_code_digest",
            "dynamic_code",
            "network_access",
            "runtime_override",
        }
        if set(value) != fields:
            raise PolicyAdmissionError("PolicyBinding has an unknown or missing field")
        if value["schema_version"] != POLICY_BINDING_SCHEMA_VERSION:
            raise PolicyAdmissionError("unsupported PolicyBinding schema_version")
        if value["role"] not in {"baseline", "candidate"}:
            raise PolicyAdmissionError("unsupported PolicyBinding role")
        if not isinstance(value["config_schema"], Mapping):
            raise PolicyAdmissionError("PolicyBinding config_schema must be an object")
        if not isinstance(value["config"], Mapping):
            raise PolicyAdmissionError("PolicyBinding config must be an object")
        if not isinstance(value["constants"], Mapping):
            raise PolicyAdmissionError("PolicyBinding constants must be an object")
        for field in (
            "config_schema_digest",
            "configuration_digest",
            "constants_digest",
            "implementation_code_digest",
        ):
            if not isinstance(value[field], str) or not _DIGEST.fullmatch(value[field]):
                raise PolicyAdmissionError(f"PolicyBinding {field} is not locked")
        for field in ("dynamic_code", "network_access", "runtime_override"):
            if not isinstance(value[field], bool):
                raise PolicyAdmissionError(f"PolicyBinding {field} must be boolean")
        config_schema = freeze_json(value["config_schema"])
        config = freeze_json(value["config"])
        constants = freeze_json(value["constants"])
        assert isinstance(config_schema, Mapping)
        assert isinstance(config, Mapping)
        assert isinstance(constants, Mapping)
        return cls(
            schema_version=str(value["schema_version"]),
            role=str(value["role"]),
            id=str(value["id"]),
            version=str(value["version"]),
            provider=str(value["provider"]),
            config_schema=config_schema,
            config_schema_digest=str(value["config_schema_digest"]),
            config=config,
            configuration_digest=str(value["configuration_digest"]),
            constants=constants,
            constants_digest=str(value["constants_digest"]),
            implementation_code_digest=str(value["implementation_code_digest"]),
            dynamic_code=bool(value["dynamic_code"]),
            network_access=bool(value["network_access"]),
            runtime_override=bool(value["runtime_override"]),
        )


def _binding(
    *,
    role: str,
    policy_id: str,
    version: str,
    config_schema: Mapping[str, Any],
    config: Mapping[str, Any],
    constants: Mapping[str, Any],
) -> PolicyBinding:
    frozen_schema = freeze_json(config_schema)
    frozen_config = freeze_json(config)
    frozen_constants = freeze_json(constants)
    assert isinstance(frozen_schema, Mapping)
    assert isinstance(frozen_config, Mapping)
    assert isinstance(frozen_constants, Mapping)
    return PolicyBinding(
        schema_version=POLICY_BINDING_SCHEMA_VERSION,
        role=role,
        id=policy_id,
        version=version,
        provider=BUILTIN_PROVIDER,
        config_schema=frozen_schema,
        config_schema_digest=canonical_digest(frozen_schema),
        config=frozen_config,
        configuration_digest=canonical_digest(frozen_config),
        constants=frozen_constants,
        constants_digest=canonical_digest(frozen_constants),
        implementation_code_digest=_implementation_digest(role),
        dynamic_code=False,
        network_access=False,
        runtime_override=False,
    )


def trusted_policy_pair(
    baseline_config: Mapping[str, Any],
) -> tuple[PolicyBinding, PolicyBinding]:
    validated_baseline = _baseline_config(baseline_config)
    validated_candidate = _candidate_config(CANDIDATE_CONFIG)
    return (
        _binding(
            role="baseline",
            policy_id=BASELINE_POLICY_ID,
            version=BASELINE_POLICY_VERSION,
            config_schema=BASELINE_CONFIG_SCHEMA,
            config=validated_baseline,
            constants={},
        ),
        _binding(
            role="candidate",
            policy_id=CANDIDATE_POLICY_ID,
            version=CANDIDATE_POLICY_VERSION,
            config_schema=CANDIDATE_CONFIG_SCHEMA,
            config=validated_candidate,
            constants=DEFENSIVE_CONSTANTS,
        ),
    )


def admit_policy_pair(
    bindings: Sequence[PolicyBinding],
) -> tuple[PolicyBinding, PolicyBinding]:
    if len(bindings) != 2:
        raise PolicyAdmissionError("ordered policy admission requires exactly two bindings")
    baseline, candidate = bindings
    if (baseline.role, candidate.role) != ("baseline", "candidate"):
        raise PolicyAdmissionError("policy bindings are identical or reversed")
    expected = trusted_policy_pair(baseline.config)
    for observed, trusted in zip((baseline, candidate), expected, strict=True):
        if observed.to_dict() != trusted.to_dict():
            raise PolicyAdmissionError(
                f"untrusted or unlocked {trusted.role} PolicyBinding"
            )
    return baseline, candidate


def _validated_baseline_policy(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(value) != {"schema_version", "id", "version", "determinism", "config"}:
        raise PolicyAdmissionError("baseline policy has an unknown or missing field")
    if (
        value["schema_version"] != "scenarioforge.deterministic-policy/v2"
        or value["id"] != BASELINE_POLICY_ID
        or value["version"] != BASELINE_POLICY_VERSION
        or value["determinism"]
        != {
            "fixed_seed_required": True,
            "decision_order": "participant_order",
            "floating_point_contract": "backend_bound",
        }
    ):
        raise PolicyAdmissionError("baseline policy identity or determinism is invalid")
    _baseline_config(value["config"])
    return value


def bind_policy_execution(
    baseline_policy: Mapping[str, Any],
    binding: PolicyBinding,
) -> dict[str, Any]:
    _validated_baseline_policy(baseline_policy)
    trusted = trusted_policy_pair(baseline_policy["config"])
    expected = trusted[0 if binding.role == "baseline" else 1]
    if binding.to_dict() != expected.to_dict():
        raise PolicyAdmissionError("binding does not match the immutable baseline plan")
    return {
        "schema_version": BOUND_EXECUTION_SCHEMA_VERSION,
        "baseline_policy": thaw_json(freeze_json(baseline_policy)),
        "binding": binding.to_dict(),
    }


def validate_bound_policy_execution(
    value: Mapping[str, Any],
) -> tuple[Mapping[str, Any], PolicyBinding]:
    if set(value) != {"schema_version", "baseline_policy", "binding"}:
        raise PolicyAdmissionError("bound policy execution has an unknown or missing field")
    if value["schema_version"] != BOUND_EXECUTION_SCHEMA_VERSION:
        raise PolicyAdmissionError("unsupported bound policy execution schema_version")
    baseline_policy = value["baseline_policy"]
    binding_value = value["binding"]
    if not isinstance(baseline_policy, Mapping) or not isinstance(binding_value, Mapping):
        raise PolicyAdmissionError("bound policy execution is invalid")
    _validated_baseline_policy(baseline_policy)
    binding = PolicyBinding.from_dict(binding_value)
    trusted = trusted_policy_pair(baseline_policy["config"])
    expected = trusted[0 if binding.role == "baseline" else 1]
    if binding.to_dict() != expected.to_dict():
        raise PolicyAdmissionError("bound execution contains an untrusted binding")
    return baseline_policy, binding


def policy_contract() -> dict[str, Any]:
    return {
        "schema_version": "scenarioforge.p0-policy-contract/v1",
        "binding_schema_version": POLICY_BINDING_SCHEMA_VERSION,
        "execution_schema_version": BOUND_EXECUTION_SCHEMA_VERSION,
        "provider": BUILTIN_PROVIDER,
        "ordered_policy_identities": [
            f"{BASELINE_POLICY_ID}@{BASELINE_POLICY_VERSION}",
            f"{CANDIDATE_POLICY_ID}@{CANDIDATE_POLICY_VERSION}",
        ],
        "baseline_config_schema": thaw_json(BASELINE_CONFIG_SCHEMA),
        "candidate_config_schema": thaw_json(CANDIDATE_CONFIG_SCHEMA),
        "candidate_config": thaw_json(CANDIDATE_CONFIG),
        "candidate_constants": thaw_json(DEFENSIVE_CONSTANTS),
        "security": {
            "dynamic_code": False,
            "network_access": False,
            "runtime_override": False,
        },
    }
