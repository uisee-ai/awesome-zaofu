from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.replay import ReplayProjectionError, build_participant_legend


ROOT = Path(__file__).resolve().parents[3]


def test_accessible_legend_distinguishes_all_p1_participant_roles() -> None:
    participants = [
        {"id": "ego", "role": "ego"},
        {"id": "challenger", "role": "controlled"},
        {"id": "traffic-1", "role": "social_vehicle"},
        {"id": "walker", "role": "pedestrian"},
    ]
    samples = [
        {"tick": 2, "participant_id": "ego", "speed_mps": 7.5, "brake": 0.4},
        {"tick": 2, "participant_id": "challenger", "speed_mps": 8.0, "brake": 0.0},
        {"tick": 2, "participant_id": "traffic-1", "speed_mps": 6.25, "brake": 0.0},
        {"tick": 2, "participant_id": "walker", "speed_mps": 1.4, "brake": 0.0},
    ]
    events = [
        {
            "event_id": "ego-brakes",
            "participant_id": "ego",
            "trigger_tick": 2,
            "end_tick": 4,
        }
    ]

    assert build_participant_legend(participants, samples, events, tick=2) == [
        {
            "participant_id": "ego",
            "role": "ego",
            "color": "#32d6c5",
            "shape": "vehicle",
            "visual_pattern": "solid",
            "speed_mps": 7.5,
            "brake_state": "braking",
            "key_event_state": "ego-brakes",
            "accessible_label": "ego · ego · 7.5 m/s · braking · event ego-brakes",
        },
        {
            "participant_id": "challenger",
            "role": "controlled_agent",
            "color": "#8ea7ff",
            "shape": "vehicle",
            "visual_pattern": "striped",
            "speed_mps": 8.0,
            "brake_state": "coasting",
            "key_event_state": "none",
            "accessible_label": (
                "challenger · controlled agent · 8.0 m/s · coasting · no key event"
            ),
        },
        {
            "participant_id": "traffic-1",
            "role": "social_vehicle",
            "color": "#ffb454",
            "shape": "vehicle",
            "visual_pattern": "outline",
            "speed_mps": 6.25,
            "brake_state": "coasting",
            "key_event_state": "none",
            "accessible_label": (
                "traffic-1 · social vehicle · 6.25 m/s · coasting · no key event"
            ),
        },
        {
            "participant_id": "walker",
            "role": "pedestrian",
            "color": "#f88bc4",
            "shape": "pedestrian",
            "visual_pattern": "upright",
            "speed_mps": 1.4,
            "brake_state": "not-applicable",
            "key_event_state": "none",
            "accessible_label": (
                "walker · pedestrian · 1.4 m/s · brake not applicable · no key event"
            ),
        },
    ]


def test_role_appearance_asset_is_complete_and_uses_no_color_only_distinction() -> None:
    manifest = json.loads(
        (ROOT / "assets/p1/replay/participant-appearance.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest == {
        "schema_version": "scenarioforge.replay-participant-appearance/v1",
        "roles": {
            "ego": {"color": "#32d6c5", "shape": "vehicle", "visual_pattern": "solid"},
            "controlled_agent": {"color": "#8ea7ff", "shape": "vehicle", "visual_pattern": "striped"},
            "social_vehicle": {"color": "#ffb454", "shape": "vehicle", "visual_pattern": "outline"},
            "pedestrian": {"color": "#f88bc4", "shape": "pedestrian", "visual_pattern": "upright"},
        },
    }
    assert len({item["visual_pattern"] for item in manifest["roles"].values()}) == 4


def test_legend_rejects_unknown_roles_missing_samples_and_duplicate_ids() -> None:
    with pytest.raises(ReplayProjectionError, match="participant role"):
        build_participant_legend(
            [{"id": "mystery", "role": "unknown"}],
            [{"tick": 0, "participant_id": "mystery", "speed_mps": 0.0, "brake": 0.0}],
            [],
            tick=0,
        )
    with pytest.raises(ReplayProjectionError, match="participant sample"):
        build_participant_legend([{"id": "ego", "role": "ego"}], [], [], tick=0)
    with pytest.raises(ReplayProjectionError, match="participants"):
        build_participant_legend(
            [{"id": "ego", "role": "ego"}, {"id": "ego", "role": "social"}],
            [{"tick": 0, "participant_id": "ego", "speed_mps": 0.0, "brake": 0.0}],
            [],
            tick=0,
        )
