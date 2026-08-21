from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.replay import ReplayProjectionError, validate_right_hand_traffic


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "p1" / "traffic"


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("wrong_way.json", "wrong-way traffic sample"),
        ("left_side_driving.json", "left-side carriageway"),
        ("wrong_turn_entry.json", "wrong turn entry lane"),
        ("wrong_receiving_lane.json", "wrong receiving lane"),
    ],
)
def test_invalid_right_hand_fixtures_fail_closed(name: str, message: str) -> None:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    with pytest.raises(ReplayProjectionError, match=message):
        validate_right_hand_traffic(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("traffic_side", "left", "right-hand traffic"),
        ("coordinate_system", "screen-pixels", "coordinate system"),
    ],
)
def test_untrusted_traffic_contract_metadata_fails_closed(
    field: str, value: str, message: str
) -> None:
    payload = json.loads(
        (FIXTURES / "right_hand_valid.json").read_text(encoding="utf-8")
    )
    payload[field] = value

    with pytest.raises(ReplayProjectionError, match=message):
        validate_right_hand_traffic(payload)
