from __future__ import annotations

import json

import pytest

from highwaypilot_lab.episodes import (
    EpisodeRecorder,
    ReplayValidationError,
    canonical_replay_bytes,
    parse_replay_json,
    validate_replay,
)


def test_replay_is_canonical_and_closed(replay_document, replay_copy):
    validated = validate_replay(replay_document)
    encoded = canonical_replay_bytes(validated)

    assert encoded == canonical_replay_bytes(parse_replay_json(encoded))
    assert encoded == json.dumps(
        replay_document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    invalid = replay_copy()
    invalid["surprise"] = True
    with pytest.raises(ReplayValidationError, match="unknown field"):
        validate_replay(invalid)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":"highwaypilot-replay/v1","schema_version":"again"}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'\xff',
    ],
)
def test_strict_json_rejects_ambiguous_inputs(raw):
    with pytest.raises(ReplayValidationError):
        parse_replay_json(raw)


def test_recorder_captures_authoritative_initial_state_and_outcome():
    recorder = EpisodeRecorder(
        session_id="session-a",
        project_id="project-a",
        initial_frame={"time": 0.0},
        strategy={"kind": "manual", "name": "human"},
        seed=7,
        effective_config={"duration": 20},
        rng_contract={"algorithm": "numpy-pcg64", "seed": 7},
        versions={
            "application": "0.1.0",
            "highway_env": "1.10.2",
            "gymnasium": "1.0.0",
            "python": "3.11.9",
            "git": "abc",
            "platform": "linux",
        },
        episode_id="episode-a",
        created_at="2026-08-25T01:00:00Z",
    )
    recorder.append("LANE_LEFT", {"time": 0.1}, {"lane": 0.25})
    replay = recorder.finish(result="terminated", termination_reason="collision")

    assert replay["initial_frame"] == {"time": 0.0}
    assert replay["actions"][0]["action"] == "LANE_LEFT"
    assert replay["reward_decomposition"] == {"lane": 0.25}
    assert replay["termination_reason"] == "collision"
    assert replay["versions"]["git"] == "abc"

    with pytest.raises(RuntimeError, match="finished"):
        recorder.append("IDLE", {}, {})
