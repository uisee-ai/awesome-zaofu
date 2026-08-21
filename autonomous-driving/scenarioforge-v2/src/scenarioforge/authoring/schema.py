from __future__ import annotations


AUTHORING_SCHEMA_VERSION = "scenarioforge.authoring/v1"

_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 64,
    "pattern": "^[a-z][a-z0-9_-]*$",
}

_BOUNDED_JSON_VALUE = {
    "anyOf": [
        {"type": "null"},
        {"type": "boolean"},
        {"type": "integer"},
        {"type": "number"},
        {"type": "string", "maxLength": 256},
        {
            "type": "array",
            "maxItems": 32,
            "items": {"$ref": "#/$defs/boundedJsonValue"},
        },
        {
            "type": "object",
            "maxProperties": 32,
            "additionalProperties": {"$ref": "#/$defs/boundedJsonValue"},
        },
    ]
}


AUTHORING_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://scenarioforge.local/schema/authoring/v1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "title",
        "description",
        "seed",
        "road",
        "routes",
        "actors",
        "static_obstacles",
        "environment",
        "events",
        "constraints",
        "parameters",
        "policy",
        "required_capabilities",
    ],
    "properties": {
        "schema_version": {"const": AUTHORING_SCHEMA_VERSION},
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
        "description": {"type": "string", "maxLength": 2000},
        "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
        "road": {"$ref": "#/$defs/road"},
        "routes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {"$ref": "#/$defs/route"},
        },
        "actors": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": {"$ref": "#/$defs/actor"},
        },
        "static_obstacles": {
            "type": "array",
            "maxItems": 128,
            "items": {"$ref": "#/$defs/staticObstacle"},
        },
        "environment": {"$ref": "#/$defs/environment"},
        "events": {
            "type": "array",
            "maxItems": 128,
            "items": {"$ref": "#/$defs/event"},
        },
        "constraints": {"$ref": "#/$defs/constraints"},
        "parameters": {
            "type": "array",
            "maxItems": 64,
            "items": {"$ref": "#/$defs/parameter"},
        },
        "policy": {"$ref": "#/$defs/policy"},
        "required_capabilities": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "minLength": 1,
                "maxLength": 96,
                "pattern": "^[a-z][a-z0-9.-]*$",
            },
        },
    },
    "$defs": {
        "id": _ID,
        "point": {
            "type": "object",
            "additionalProperties": False,
            "required": ["x_m", "y_m"],
            "properties": {
                "x_m": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
                "y_m": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
            },
        },
        "units": {
            "type": "object",
            "additionalProperties": False,
            "required": ["distance", "speed", "heading", "time"],
            "properties": {
                "distance": {"const": "m"},
                "speed": {"const": "m/s"},
                "heading": {"const": "deg"},
                "time": {"const": "s"},
            },
        },
        "lane": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "kind",
                "length_m",
                "width_m",
                "speed_limit_mps",
                "centerline",
                "predecessor_lane_ids",
                "successor_lane_ids",
            ],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "kind": {
                    "enum": [
                        "travel",
                        "merge",
                        "ramp",
                        "turn",
                        "crosswalk",
                        "shoulder",
                        "closed",
                    ]
                },
                "length_m": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 100000.0},
                "width_m": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 20.0},
                "speed_limit_mps": {"type": "number", "minimum": 0.1, "maximum": 80.0},
                "centerline": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 256,
                    "items": {"$ref": "#/$defs/point"},
                },
                "predecessor_lane_ids": {
                    "type": "array",
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/id"},
                },
                "successor_lane_ids": {
                    "type": "array",
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/id"},
                },
            },
        },
        "conflictZone": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "lane_ids", "polygon"],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "lane_ids": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/id"},
                },
                "polygon": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 64,
                    "items": {"$ref": "#/$defs/point"},
                },
            },
        },
        "road": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "topology_kind",
                "coordinate_system",
                "units",
                "lanes",
                "conflict_zones",
            ],
            "properties": {
                "topology_kind": {
                    "enum": ["straight", "corridor", "intersection", "merge"]
                },
                "coordinate_system": {"const": "right-handed-x-forward-y-left"},
                "units": {"$ref": "#/$defs/units"},
                "lanes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {"$ref": "#/$defs/lane"},
                },
                "conflict_zones": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"$ref": "#/$defs/conflictZone"},
                },
            },
        },
        "routeGoal": {
            "type": "object",
            "additionalProperties": False,
            "required": ["lane_id", "longitudinal_m"],
            "properties": {
                "lane_id": {"$ref": "#/$defs/id"},
                "longitudinal_m": {"type": "number", "minimum": 0.0, "maximum": 100000.0},
            },
        },
        "route": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "kind", "lane_ids", "goal"],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "kind": {"enum": ["vehicle", "pedestrian"]},
                "lane_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": {"$ref": "#/$defs/id"},
                },
                "goal": {"$ref": "#/$defs/routeGoal"},
            },
        },
        "dimensions": {
            "type": "object",
            "additionalProperties": False,
            "required": ["length_m", "width_m", "height_m"],
            "properties": {
                "length_m": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 30.0},
                "width_m": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 10.0},
                "height_m": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 10.0},
            },
        },
        "spawn": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "lane_id",
                "longitudinal_m",
                "lateral_m",
                "speed_mps",
                "heading_deg",
            ],
            "properties": {
                "lane_id": {"$ref": "#/$defs/id"},
                "longitudinal_m": {"type": "number", "minimum": 0.0, "maximum": 100000.0},
                "lateral_m": {"type": "number", "minimum": -20.0, "maximum": 20.0},
                "speed_mps": {"type": "number", "minimum": 0.0, "maximum": 80.0},
                "heading_deg": {"type": "number", "minimum": -180.0, "maximum": 180.0},
            },
        },
        "behavior": {
            "type": "object",
            "additionalProperties": False,
            "required": ["profile"],
            "properties": {
                "profile": {
                    "enum": [
                        "deterministic",
                        "conservative",
                        "normal",
                        "aggressive",
                        "walking",
                        "standing",
                    ]
                }
            },
        },
        "actor": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "kind",
                "role",
                "dimensions",
                "spawn",
                "route_id",
                "behavior",
            ],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "kind": {"enum": ["vehicle", "pedestrian"]},
                "role": {"enum": ["ego", "social", "vulnerable_road_user"]},
                "dimensions": {"$ref": "#/$defs/dimensions"},
                "spawn": {"$ref": "#/$defs/spawn"},
                "route_id": {"$ref": "#/$defs/id"},
                "behavior": {"$ref": "#/$defs/behavior"},
            },
        },
        "staticObstacle": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "kind",
                "lane_id",
                "longitudinal_m",
                "lateral_m",
                "dimensions",
            ],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "kind": {"enum": ["barrier", "cone", "debris", "parked_vehicle"]},
                "lane_id": {"$ref": "#/$defs/id"},
                "longitudinal_m": {"type": "number", "minimum": 0.0, "maximum": 100000.0},
                "lateral_m": {"type": "number", "minimum": -20.0, "maximum": 20.0},
                "dimensions": {"$ref": "#/$defs/dimensions"},
            },
        },
        "environment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["weather", "time_of_day", "road_surface", "visibility_m"],
            "properties": {
                "weather": {"enum": ["clear", "rain", "fog", "snow"]},
                "time_of_day": {"enum": ["dawn", "day", "dusk", "night"]},
                "road_surface": {"enum": ["dry", "wet", "icy"]},
                "visibility_m": {"type": "number", "minimum": 1.0, "maximum": 10000.0},
            },
        },
        "trigger": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "time_s"],
            "properties": {
                "kind": {"const": "simulation_time"},
                "time_s": {"type": "number", "minimum": 0.0, "maximum": 86400.0},
            },
        },
        "action": {
            "oneOf": [
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "throttle_brake", "steering"],
                    "properties": {
                        "kind": {"const": "vehicle_control"},
                        "throttle_brake": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                        "steering": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                    },
                },
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "speed_mps"],
                    "properties": {
                        "kind": {"const": "pedestrian_speed"},
                        "speed_mps": {"type": "number", "minimum": 0.0, "maximum": 15.0},
                    },
                },
            ]
        },
        "event": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "sequence", "actor_id", "trigger", "action"],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "sequence": {"type": "integer", "minimum": 0, "maximum": 127},
                "actor_id": {"$ref": "#/$defs/id"},
                "trigger": {"$ref": "#/$defs/trigger"},
                "action": {"$ref": "#/$defs/action"},
            },
        },
        "condition": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "kind", "actor_ids", "route_id", "threshold"],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "kind": {
                    "enum": [
                        "route_completed",
                        "collision",
                        "time_limit",
                        "minimum_separation",
                        "speed_below",
                    ]
                },
                "actor_ids": {
                    "type": "array",
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"$ref": "#/$defs/id"},
                },
                "route_id": {
                    "oneOf": [{"type": "null"}, {"$ref": "#/$defs/id"}]
                },
                "threshold": {
                    "oneOf": [
                        {"type": "null"},
                        {"type": "number", "minimum": 0.0, "maximum": 100000.0},
                    ]
                },
            },
        },
        "safety": {
            "type": "object",
            "additionalProperties": False,
            "required": ["minimum_separation_m", "max_deceleration_mps2"],
            "properties": {
                "minimum_separation_m": {"type": "number", "minimum": 0.0, "maximum": 1000.0},
                "max_deceleration_mps2": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 30.0},
            },
        },
        "constraints": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "duration_s",
                "collision_is_failure",
                "success_conditions",
                "failure_conditions",
                "safety",
            ],
            "properties": {
                "duration_s": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 86400.0},
                "collision_is_failure": {"type": "boolean"},
                "success_conditions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": {"$ref": "#/$defs/condition"},
                },
                "failure_conditions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": {"$ref": "#/$defs/condition"},
                },
                "safety": {"$ref": "#/$defs/safety"},
            },
        },
        "fixedDistribution": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "value"],
            "properties": {
                "kind": {"const": "fixed"},
                "value": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
            },
        },
        "uniformDistribution": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "minimum", "maximum"],
            "properties": {
                "kind": {"const": "uniform"},
                "minimum": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
                "maximum": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
            },
        },
        "normalDistribution": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "mean", "standard_deviation", "minimum", "maximum"],
            "properties": {
                "kind": {"const": "normal"},
                "mean": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
                "standard_deviation": {"type": "number", "exclusiveMinimum": 0.0, "maximum": 100000.0},
                "minimum": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
                "maximum": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
            },
        },
        "choiceDistribution": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "values"],
            "properties": {
                "kind": {"const": "choice"},
                "values": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "uniqueItems": True,
                    "items": {"type": "number", "minimum": -100000.0, "maximum": 100000.0},
                },
            },
        },
        "distribution": {
            "oneOf": [
                {"$ref": "#/$defs/fixedDistribution"},
                {"$ref": "#/$defs/uniformDistribution"},
                {"$ref": "#/$defs/normalDistribution"},
                {"$ref": "#/$defs/choiceDistribution"},
            ]
        },
        "parameter": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "target_path", "value_type", "distribution"],
            "properties": {
                "id": {"$ref": "#/$defs/id"},
                "target_path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 160,
                    "pattern": "^\\$\\.(actors|environment|events|constraints)(\\[[0-9]+\\]|\\.[a-z][a-z0-9_]*)+$",
                },
                "value_type": {"enum": ["integer", "number"]},
                "distribution": {"$ref": "#/$defs/distribution"},
            },
        },
        "boundedJsonValue": _BOUNDED_JSON_VALUE,
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "version", "config"],
            "properties": {
                "id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 96,
                    "pattern": "^[a-z][a-z0-9.-]*$",
                },
                "version": {
                    "type": "string",
                    "minLength": 5,
                    "maxLength": 32,
                    "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
                },
                "config": {
                    "type": "object",
                    "maxProperties": 32,
                    "additionalProperties": {"$ref": "#/$defs/boundedJsonValue"},
                },
            },
        },
    },
}
