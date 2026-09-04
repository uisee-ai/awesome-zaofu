from __future__ import annotations

import pytest

from highwaypilot_lab.episodes import EpisodeNotFound, LibraryError, TemporaryEpisodeStore


def test_temporary_episode_is_session_isolated_without_disclosure(replay_document):
    store = TemporaryEpisodeStore()
    store.put(replay_document)

    assert store.get("episode-001", session_id="session-a")["episode_id"] == "episode-001"

    wrong_session = pytest.raises(
        EpisodeNotFound,
        lambda: store.get("episode-001", session_id="session-b"),
    ).value
    missing = pytest.raises(
        EpisodeNotFound,
        lambda: store.get("missing", session_id="session-b"),
    ).value
    assert wrong_session.as_dict() == missing.as_dict() == {
        "code": "EPISODE_NOT_FOUND",
        "message": "episode is unavailable",
    }


def test_temporary_episode_id_cannot_be_replaced_by_another_session(replay_document, replay_copy):
    store = TemporaryEpisodeStore()
    store.put(replay_document)
    collision = replay_copy()
    collision["ownership"]["temporary_session_id"] = "session-b"

    with pytest.raises(LibraryError) as error:
        store.put(collision)
    assert error.value.code == "TEMPORARY_EPISODE_CONFLICT"
    assert store.get("episode-001", session_id="session-a")["ownership"]["temporary_session_id"] == "session-a"
