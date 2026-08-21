from __future__ import annotations


SCENARIO_SPEC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://scenarioforge.local/schema/scenario/v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "scenario_id",
        "seed",
        "road",
        "participants",
        "parameters",
        "events",
        "constraints",
        "policy",
        "required_capabilities",
        "backend_extensions",
    ],
    "properties": {
        "schema_version": {"const": "scenarioforge.scenario/v1"},
        "scenario_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[a-z0-9-]+$"},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
        "road": {"$ref": "#/$defs/road"},
        "participants": {
            "type": "array",
            "minItems": 2,
            "maxItems": 16,
            "items": {"$ref": "#/$defs/participant"},
        },
        "parameters": {"$ref": "#/$defs/parameters"},
        "events": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {"$ref": "#/$defs/event"},
        },
        "constraints": {"$ref": "#/$defs/constraints"},
        "policy": {"$ref": "#/$defs/policy"},
        "required_capabilities": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 96, "pattern": "^[a-z0-9.-]+$"},
        },
        "backend_extensions": {"$ref": "#/$defs/backendExtensions"},
    },
    "$defs": {
        "road": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "template",
                "lane_count",
                "lane_width_m",
                "length_m",
                "coordinate_system",
                "units",
            ],
            "properties": {
                "template": {"const": "straight"},
                "lane_count": {"type": "integer", "minimum": 1, "maximum": 8},
                "lane_width_m": {"type": "number", "exclusiveMinimum": 2.0, "maximum": 5.0},
                "length_m": {"type": "number", "minimum": 50.0, "maximum": 10000.0},
                "coordinate_system": {"const": "right-handed-x-forward-y-left"},
                "units": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["distance", "speed", "heading", "time"],
                    "properties": {
                        "distance": {"const": "m"},
                        "speed": {"const": "m/s"},
                        "heading": {"const": "deg"},
                        "time": {"const": "tick"},
                    },
                },
            },
        },
        "state": {
            "type": "object",
            "additionalProperties": False,
            "required": ["lane", "longitudinal_m", "speed_mps", "heading_deg"],
            "properties": {
                "lane": {"type": "integer", "minimum": 0, "maximum": 1},
                "longitudinal_m": {"type": "number", "minimum": 0.0, "maximum": 10000.0},
                "speed_mps": {"type": "number", "minimum": 0.0, "maximum": 80.0},
                "heading_deg": {"type": "number", "minimum": -180.0, "maximum": 180.0},
            },
        },
        "target": {
            "type": "object",
            "additionalProperties": False,
            "required": ["lane", "longitudinal_m"],
            "properties": {
                "lane": {"type": "integer", "minimum": 0, "maximum": 1},
                "longitudinal_m": {"type": "number", "minimum": 0.0, "maximum": 10000.0},
            },
        },
        "participant": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "role", "initial", "target"],
            "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[a-z][a-z0-9-]*$"},
                "role": {"enum": ["ego", "social"]},
                "initial": {"$ref": "#/$defs/state"},
                "target": {"$ref": "#/$defs/target"},
            },
        },
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["initial_gap_m", "vehicle_speed_mps", "brake_tick", "brake_intensity"],
            "properties": {
                "initial_gap_m": {"type": "number", "minimum": 1.0, "maximum": 200.0},
                "vehicle_speed_mps": {"type": "number", "minimum": 0.1, "maximum": 80.0},
                "brake_tick": {"type": "integer", "minimum": 0, "maximum": 10000},
                "brake_intensity": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 1.0},
            },
        },
        "event": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "participant_id", "trigger", "action"],
            "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 32, "pattern": "^[a-z][a-z0-9-]*$"},
                "type": {"const": "vehicle_brake"},
                "participant_id": {"type": "string", "minLength": 1, "maxLength": 32},
                "trigger": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "tick"],
                    "properties": {
                        "kind": {"const": "tick"},
                        "tick": {"type": "integer", "minimum": 0, "maximum": 10000},
                    },
                },
                "action": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["brake"],
                    "properties": {"brake": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 1.0}},
                },
            },
        },
        "constraints": {
            "type": "object",
            "additionalProperties": False,
            "required": ["max_steps", "collision_is_failure", "success"],
            "properties": {
                "max_steps": {"type": "integer", "minimum": 1, "maximum": 10000},
                "collision_is_failure": {"const": True},
                "success": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind"],
                    "properties": {"kind": {"const": "horizon_completed"}},
                },
            },
        },
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "version", "config"],
            "properties": {
                "id": {"const": "scenarioforge.constant-lane"},
                "version": {"const": "1.0.0"},
                "config": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["steering", "throttle_brake"],
                    "properties": {
                        "steering": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                        "throttle_brake": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                    },
                },
            },
        },
        "extensionValue": {
            "oneOf": [
                {"type": "null"},
                {"type": "boolean"},
                {"type": "integer"},
                {"type": "number"},
                {"type": "string", "maxLength": 256},
                {"type": "array", "maxItems": 16, "items": {"$ref": "#/$defs/extensionValue"}},
                {
                    "type": "object",
                    "maxProperties": 16,
                    "additionalProperties": {"$ref": "#/$defs/extensionValue"},
                },
            ]
        },
        "extension": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "options"],
            "properties": {
                "schema_version": {"type": "string", "minLength": 1, "maxLength": 96},
                "options": {"type": "object", "maxProperties": 16, "additionalProperties": {"$ref": "#/$defs/extensionValue"}},
            },
        },
        "backendExtensions": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "extensions"],
            "properties": {
                "schema_version": {"const": "scenarioforge.backend-extensions/v1"},
                "extensions": {
                    "type": "object",
                    "maxProperties": 8,
                    "propertyNames": {"pattern": "^[a-z][a-z0-9_-]*$"},
                    "additionalProperties": {"$ref": "#/$defs/extension"},
                },
            },
        },
    },
}


# The v1 resource above is intentionally retained verbatim.  The public
# validator selects a versioned branch, so adding v2 cannot relax or reinterpret
# any document whose schema_version is scenarioforge.scenario/v1.
SCENARIO_SPEC_V1_SCHEMA = SCENARIO_SPEC_SCHEMA

_SCENARIO_SPEC_V1_BRANCH = {
    key: value
    for key, value in SCENARIO_SPEC_V1_SCHEMA.items()
    if key not in {"$schema", "$id", "$defs"}
}

_SCENARIO_SPEC_V2_BRANCH = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "scenario_id",
        "seed",
        "road",
        "participants",
        "parameters",
        "events",
        "constraints",
        "policy",
        "required_capabilities",
        "backend_extensions",
    ],
    "properties": {
        "schema_version": {"const": "scenarioforge.scenario/v2"},
        "scenario_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[a-z][a-z0-9_-]*$",
        },
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
        "road": {"$ref": "#/$defs/v2Topology"},
        "participants": {
            "type": "array",
            "minItems": 2,
            "maxItems": 16,
            "items": {"$ref": "#/$defs/v2Participant"},
        },
        # These bounded parameters remain available as prototype/calibration
        # inputs.  P0C-02, rather than the shared contract, freezes their final
        # values.
        "parameters": {"$ref": "#/$defs/parameters"},
        "events": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {"$ref": "#/$defs/v2Event"},
        },
        "constraints": {"$ref": "#/$defs/v2OutcomeContract"},
        "policy": {"$ref": "#/$defs/v2Policy"},
        "required_capabilities": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 96,
                "pattern": "^[a-z0-9.-]+$",
            },
        },
        "backend_extensions": {"$ref": "#/$defs/v2BackendExtensions"},
    },
}

_V2_DEFS = {
    "v2Id": {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "pattern": "^[a-z][a-z0-9_-]*$",
    },
    "v2EngineLaneIndex": {
        "type": "object",
        "additionalProperties": False,
        "required": ["start_node", "end_node", "lane_index"],
        "properties": {
            "start_node": {
                "type": "string",
                "minLength": 1,
                "maxLength": 96,
                "pattern": "^[A-Za-z0-9_<>.$:-]+$",
            },
            "end_node": {
                "type": "string",
                "minLength": 1,
                "maxLength": 96,
                "pattern": "^[A-Za-z0-9_<>.$:-]+$",
            },
            "lane_index": {"type": "integer", "minimum": 0, "maximum": 15},
        },
    },
    "v2Lane": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "road_id",
            "engine_lane_index",
            "kind",
            "length_m",
            "predecessor_lane_ids",
            "successor_lane_ids",
        ],
        "properties": {
            "id": {"$ref": "#/$defs/v2Id"},
            "road_id": {"$ref": "#/$defs/v2Id"},
            "engine_lane_index": {"$ref": "#/$defs/v2EngineLaneIndex"},
            "kind": {
                "enum": ["travel", "merge", "ramp", "turn", "closing", "closed"]
            },
            "length_m": {"type": "number", "minimum": 20.0, "maximum": 10000.0},
            "predecessor_lane_ids": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/v2Id"},
            },
            "successor_lane_ids": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/v2Id"},
            },
        },
    },
    "v2ConflictZone": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "lane_ids", "start_m", "end_m"],
        "properties": {
            "id": {"$ref": "#/$defs/v2Id"},
            "lane_ids": {
                "type": "array",
                "minItems": 2,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/v2Id"},
            },
            "start_m": {"type": "number", "minimum": 0.0, "maximum": 10000.0},
            "end_m": {"type": "number", "minimum": 0.0, "maximum": 10000.0},
        },
    },
    "v2Topology": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "topology_kind",
            "map_block_sequence",
            "lane_width_m",
            "coordinate_system",
            "units",
            "lanes",
            "conflict_zones",
        ],
        "properties": {
            "schema_version": {"const": "scenarioforge.topology/v2"},
            "topology_kind": {
                "enum": [
                    "straight",
                    "lane_closure",
                    "corridor_merge",
                    "ramp_merge",
                    "intersection",
                ]
            },
            "map_block_sequence": {
                "type": "string",
                "minLength": 1,
                "maxLength": 32,
                "pattern": "^[A-Za-z0-9]+$",
            },
            "lane_width_m": {"type": "number", "exclusiveMinimum": 2.0, "maximum": 5.0},
            "coordinate_system": {"const": "right-handed-x-forward-y-left"},
            "units": {
                "type": "object",
                "additionalProperties": False,
                "required": ["distance", "speed", "heading", "time"],
                "properties": {
                    "distance": {"const": "m"},
                    "speed": {"const": "m/s"},
                    "heading": {"const": "deg"},
                    "time": {"const": "tick"},
                },
            },
            "lanes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"$ref": "#/$defs/v2Lane"},
            },
            "conflict_zones": {
                "type": "array",
                "maxItems": 16,
                "items": {"$ref": "#/$defs/v2ConflictZone"},
            },
        },
    },
    "v2Spawn": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "lane_id",
            "longitudinal_m",
            "lateral_m",
            "speed_mps",
            "heading_deg",
        ],
        "properties": {
            "schema_version": {"const": "scenarioforge.actor-spawn/v2"},
            "lane_id": {"$ref": "#/$defs/v2Id"},
            "longitudinal_m": {"type": "number", "minimum": 0.0, "maximum": 10000.0},
            "lateral_m": {"type": "number", "minimum": -20.0, "maximum": 20.0},
            "speed_mps": {"type": "number", "minimum": 0.0, "maximum": 80.0},
            "heading_deg": {"type": "number", "minimum": -180.0, "maximum": 180.0},
        },
    },
    "v2Route": {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "id", "lane_ids", "goal"],
        "properties": {
            "schema_version": {"const": "scenarioforge.route/v2"},
            "id": {"$ref": "#/$defs/v2Id"},
            "lane_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"$ref": "#/$defs/v2Id"},
            },
            "goal": {
                "type": "object",
                "additionalProperties": False,
                "required": ["lane_id", "longitudinal_m"],
                "properties": {
                    "lane_id": {"$ref": "#/$defs/v2Id"},
                    "longitudinal_m": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 10000.0,
                    },
                },
            },
        },
    },
    "v2Participant": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "role", "actor_type", "spawn", "route"],
        "properties": {
            "id": {"$ref": "#/$defs/v2Id"},
            "role": {"enum": ["ego", "social"]},
            "actor_type": {"const": "vehicle"},
            "spawn": {"$ref": "#/$defs/v2Spawn"},
            "route": {"$ref": "#/$defs/v2Route"},
        },
    },
    "v2Trigger": {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "kind", "tick"],
        "properties": {
            "schema_version": {"const": "scenarioforge.trigger/v2"},
            "kind": {"const": "tick"},
            "tick": {"type": "integer", "minimum": 0, "maximum": 10000},
        },
    },
    "v2ControlAction": {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "steering", "throttle_brake"],
        "properties": {
            "schema_version": {"const": "scenarioforge.control-action/v2"},
            "steering": {"type": "number", "minimum": -1.0, "maximum": 1.0},
            "throttle_brake": {"type": "number", "minimum": -1.0, "maximum": 1.0},
        },
    },
    "v2Event": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "sequence",
            "type",
            "participant_id",
            "trigger",
            "action",
        ],
        "properties": {
            "id": {"$ref": "#/$defs/v2Id"},
            "sequence": {"type": "integer", "minimum": 0, "maximum": 31},
            "type": {"const": "control_override"},
            "participant_id": {"$ref": "#/$defs/v2Id"},
            "trigger": {"$ref": "#/$defs/v2Trigger"},
            "duration_ticks": {"type": "integer", "minimum": 1, "maximum": 1000},
            "action": {"$ref": "#/$defs/v2ControlAction"},
        },
    },
    "v2Predicate": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "kind", "participant_ids", "lane_ids"],
        "properties": {
            "id": {"$ref": "#/$defs/v2Id"},
            "kind": {
                "enum": [
                    "route_completed",
                    "merge_completed",
                    "yield_completed",
                    "collision",
                    "boundary_violation",
                    "wrong_lane",
                    "closed_region_entry",
                    "timeout",
                    "execution_incomplete",
                ]
            },
            "participant_ids": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/v2Id"},
            },
            "lane_ids": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/v2Id"},
            },
        },
    },
    "v2MetricDefinition": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "definition_id",
            "metric",
            "unit",
            "applies_to",
            "threshold",
            "null_semantics",
            "evidence_field",
        ],
        "properties": {
            "definition_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 96,
                "pattern": "^[a-z0-9./-]+$",
            },
            "metric": {
                "enum": [
                    "collision",
                    "hard_braking",
                    "minimum_ttc",
                    "completion_time",
                    "termination_reason",
                ]
            },
            "unit": {"enum": ["boolean", "m/s^2", "s", "category"]},
            "applies_to": {
                "type": "object",
                "additionalProperties": False,
                "required": ["participant_ids", "topology_kinds"],
                "properties": {
                    "participant_ids": {
                        "type": "array",
                        "maxItems": 16,
                        "uniqueItems": True,
                        "items": {"$ref": "#/$defs/v2Id"},
                    },
                    "topology_kinds": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 5,
                        "uniqueItems": True,
                        "items": {
                            "enum": [
                                "straight",
                                "lane_closure",
                                "corridor_merge",
                                "ramp_merge",
                                "intersection",
                            ]
                        },
                    },
                },
            },
            "threshold": {
                "oneOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["operator", "value"],
                        "properties": {
                            "operator": {"enum": ["lt", "lte", "gt", "gte", "eq"]},
                            "value": {"type": "number"},
                        },
                    },
                ]
            },
            "null_semantics": {"type": "string", "minLength": 1, "maxLength": 96},
            "evidence_field": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
                "pattern": "^[a-z][a-z0-9_]*$",
            },
        },
    },
    "v2OutcomeContract": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "max_steps",
            "duration_s",
            "collision_is_failure",
            "target_outcome",
            "success_predicates",
            "failure_predicates",
            "expected_events",
            "metric_definitions",
        ],
        "properties": {
            "schema_version": {"const": "scenarioforge.outcome-contract/v2"},
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 10000},
            "duration_s": {"type": "number", "minimum": 10.0, "maximum": 20.0},
            "collision_is_failure": {"const": True},
            "target_outcome": {
                "enum": ["safe_pass", "near_miss", "collision_failure"]
            },
            "success_predicates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"$ref": "#/$defs/v2Predicate"},
            },
            "failure_predicates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"$ref": "#/$defs/v2Predicate"},
            },
            "expected_events": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"$ref": "#/$defs/v2Id"},
            },
            "metric_definitions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {"$ref": "#/$defs/v2MetricDefinition"},
            },
        },
    },
    "v2Policy": {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "id", "version", "determinism", "config"],
        "properties": {
            "schema_version": {"const": "scenarioforge.deterministic-policy/v2"},
            "id": {"const": "scenarioforge.deterministic-control"},
            "version": {"const": "2.0.0"},
            "determinism": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "fixed_seed_required",
                    "decision_order",
                    "floating_point_contract",
                ],
                "properties": {
                    "fixed_seed_required": {"const": True},
                    "decision_order": {"const": "participant_order"},
                    "floating_point_contract": {"const": "backend_bound"},
                },
            },
            "config": {
                "type": "object",
                "additionalProperties": False,
                "required": ["default_action", "participant_actions"],
                "properties": {
                    "default_action": {
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
                    },
                    "participant_actions": {
                        "type": "array",
                        "maxItems": 16,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["participant_id", "steering", "throttle_brake"],
                            "properties": {
                                "participant_id": {"$ref": "#/$defs/v2Id"},
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
            },
        },
    },
    "v2BackendExtensions": {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "extensions"],
        "properties": {
            "schema_version": {"const": "scenarioforge.backend-extensions/v2"},
            "extensions": {
                "type": "object",
                "maxProperties": 8,
                "propertyNames": {"pattern": "^[a-z][a-z0-9_-]*$"},
                "additionalProperties": {"$ref": "#/$defs/extension"},
            },
        },
    },
}

SCENARIO_SPEC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://scenarioforge.local/schema/scenario",
    "if": {
        "type": "object",
        "properties": {
            "schema_version": {"const": "scenarioforge.scenario/v1"},
        },
        "required": ["schema_version"],
    },
    "then": _SCENARIO_SPEC_V1_BRANCH,
    "else": _SCENARIO_SPEC_V2_BRANCH,
    "$defs": {**SCENARIO_SPEC_V1_SCHEMA["$defs"], **_V2_DEFS},
}
