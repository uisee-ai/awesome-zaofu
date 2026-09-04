from __future__ import annotations

import gzip
import threading

import pytest

from highwaypilot_lab.episodes import LibraryError, ProjectEpisodeLibrary, canonical_replay_bytes


def test_import_accepts_single_or_concatenated_gzip_members(tmp_path, replay_document):
    raw = canonical_replay_bytes(replay_document)
    library = ProjectEpisodeLibrary(tmp_path)
    assert library.import_replay(gzip.compress(raw))["episode_id"] == "episode-001"

    replay_document["episode_id"] = "episode-002"
    raw = canonical_replay_bytes(replay_document)
    split = len(raw) // 2
    concatenated = gzip.compress(raw[:split]) + gzip.compress(raw[split:])
    assert library.import_replay(concatenated)["episode_id"] == "episode-002"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: gzip.compress(gzip.compress(raw)),
        lambda raw: gzip.compress(raw) + b"trailing-data",
    ],
)
def test_import_rejects_nested_compression_and_trailing_data(tmp_path, replay_document, mutate):
    library = ProjectEpisodeLibrary(tmp_path)
    with pytest.raises(LibraryError) as error:
        library.import_replay(mutate(canonical_replay_bytes(replay_document)))
    assert error.value.code == "LIBRARY_IMPORT_INVALID"
    assert library.list() == []


def test_import_enforces_compressed_and_decompressed_stream_limits(tmp_path, replay_document):
    raw = canonical_replay_bytes(replay_document)
    compressed_limit = ProjectEpisodeLibrary(tmp_path / "compressed", max_replay_bytes=10)
    with pytest.raises(LibraryError) as error:
        compressed_limit.import_replay(gzip.compress(raw))
    assert error.value.code == "LIBRARY_REPLAY_TOO_LARGE"

    decompressed_limit = ProjectEpisodeLibrary(tmp_path / "decompressed", max_replay_bytes=len(raw) - 1)
    with pytest.raises(LibraryError) as error:
        decompressed_limit.import_replay(gzip.compress(raw))
    assert error.value.code == "LIBRARY_REPLAY_TOO_LARGE"


def test_only_one_import_transaction_is_admitted_per_project(tmp_path, replay_document):
    first = ProjectEpisodeLibrary(tmp_path)
    second = ProjectEpisodeLibrary(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def occupy():
        with first.import_transaction():
            entered.set()
            release.wait(2)

    thread = threading.Thread(target=occupy)
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(LibraryError) as error:
            second.import_replay(canonical_replay_bytes(replay_document))
        assert error.value.as_dict() == {
            "code": "LIBRARY_IMPORT_BUSY",
            "message": "another import is in progress",
            "status": 409,
            "retryable": True,
        }
    finally:
        release.set()
        thread.join()
