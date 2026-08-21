from __future__ import annotations

import copy
import json
from pathlib import Path

from scenarioforge.replay import validate_right_hand_traffic


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "p1" / "traffic"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_valid_right_hand_fixture_freezes_complete_lane_and_route_semantics() -> None:
    payload = _fixture("right_hand_valid.json")
    original = copy.deepcopy(payload)

    result = validate_right_hand_traffic(payload)

    assert payload == original
    assert result == {
        "schema_version": "scenarioforge.right-hand-traffic-validation/v1",
        "traffic_side": "right",
        "coordinate_system": "right-handed-x-forward-y-left",
        "lane_ids": [
            "eastbound-in",
            "east-to-north-connector",
            "northbound-out",
        ],
        "carriageway_ids": ["eastbound", "northbound"],
        "intersection_connectors": [
            {
                "lane_id": "east-to-north-connector",
                "predecessor_lane_ids": ["eastbound-in"],
                "successor_lane_ids": ["northbound-out"],
            }
        ],
        "route_bindings": [
            {
                "participant_id": "ego",
                "role": "ego",
                "lane_ids": [
                    "eastbound-in",
                    "east-to-north-connector",
                    "northbound-out",
                ],
                "receiving_lane_id": "northbound-out",
            }
        ],
        "tolerances": {
            "model_scale_relative_error_max": 0.02,
            "lane_center_error_m_max": 0.25,
            "yellow_line_footprint_epsilon_m_max": 0.02,
            "heading_tangent_error_deg_max": 10.0,
        },
        "observed": {
            "model_scale_relative_error_max": 0.0,
            "lane_center_error_m_max": 0.0,
            "yellow_line_footprint_epsilon_m": 0.02,
            "heading_tangent_error_deg_max": 0.0,
        },
    }


def test_thresholds_are_inclusive_at_two_percent_quarter_metre_and_two_cm() -> None:
    payload = _fixture("right_hand_valid.json")
    model = payload["model_instances"][0]
    model["render_dimensions_m"]["length"] = 4.704
    for sample in payload["samples"]:
        sample["position_m"][1] += 0.25

    result = validate_right_hand_traffic(payload)

    assert result["observed"] == {
        "model_scale_relative_error_max": 0.02,
        "lane_center_error_m_max": 0.25,
        "yellow_line_footprint_epsilon_m": 0.02,
        "heading_tangent_error_deg_max": 0.0,
    }
