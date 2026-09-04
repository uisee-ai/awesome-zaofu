from __future__ import annotations

import gzip

import pytest

from highwaypilot_lab.episodes import (
    EpisodeNotFound,
    LibraryError,
    ProjectEpisodeLibrary,
    TemporaryEpisodeStore,
    parse_replay_json,
)


def test_explicit_save_makes_episode_project_shared(tmp_path, replay_document):
    temporary = TemporaryEpisodeStore()
    temporary.put(replay_document)
    library = ProjectEpisodeLibrary(tmp_path)

    item = library.save_temporary(
        temporary,
        "episode-001",
        session_id="session-a",
        name="First drive",
    )

    assert item["name"] == "First drive"
    assert library.get("episode-001")["ownership"]["temporary_session_id"] == "session-a"
    assert library.list()[0]["episode_id"] == "episode-001"
    assert library.rename("episode-001", "Renamed")["name"] == "Renamed"
    assert parse_replay_json(library.export("episode-001"))["episode_id"] == "episode-001"
    assert parse_replay_json(gzip.decompress(library.export("episode-001", gzip_transport=True)))["episode_id"] == "episode-001"

    with pytest.raises(LibraryError, match="confirmation"):
        library.delete("episode-001", confirm=False)
    library.delete("episode-001", confirm=True)
    with pytest.raises(EpisodeNotFound):
        library.get("episode-001")


def test_decimal_byte_and_count_quotas_are_rechecked(tmp_path, replay_copy):
    library = ProjectEpisodeLibrary(tmp_path, max_episodes=1, max_total_bytes=5_000_000)
    first = replay_copy()
    library.save(first)

    second = replay_copy()
    second["episode_id"] = "episode-002"
    with pytest.raises(LibraryError) as error:
        library.save(second)
    assert error.value.code == "LIBRARY_QUOTA_EXCEEDED"

    too_small = ProjectEpisodeLibrary(tmp_path / "small", max_replay_bytes=20)
    with pytest.raises(LibraryError) as error:
        too_small.save(first)
    assert error.value.code == "LIBRARY_REPLAY_TOO_LARGE"


def test_save_never_overwrites_different_hash(tmp_path, replay_copy):
    library = ProjectEpisodeLibrary(tmp_path)
    library.save(replay_copy())
    changed = replay_copy()
    changed["result"] = "terminated"

    with pytest.raises(LibraryError) as error:
        library.save(changed)
    assert error.value.code == "LIBRARY_CONFLICT"
    assert library.get("episode-001")["result"] == "completed"
