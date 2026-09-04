from __future__ import annotations

import pytest

from highwaypilot_lab.episodes import ProjectEpisodeLibrary, SimulatedCrash


@pytest.mark.parametrize("stage", ["prepared", "renamed", "indexed"])
def test_journal_recovery_is_deterministic(tmp_path, replay_copy, stage):
    library = ProjectEpisodeLibrary(tmp_path)
    with pytest.raises(SimulatedCrash):
        library.save(replay_copy(), crash_after_stage=stage)

    recovered = ProjectEpisodeLibrary(tmp_path)
    recovered.recover()

    if stage == "prepared":
        assert recovered.list() == []
    else:
        assert recovered.get("episode-001")["episode_id"] == "episode-001"
    assert list((tmp_path / ".highwaypilot" / "episodes").glob("*.journal.json")) == []


def test_recovery_quarantines_a_conflicting_renamed_target(tmp_path, replay_copy):
    library = ProjectEpisodeLibrary(tmp_path)
    with pytest.raises(SimulatedCrash):
        library.save(replay_copy(), crash_after_stage="renamed")
    target = tmp_path / ".highwaypilot" / "episodes" / "episode-001.json"
    target.write_bytes(b'{"different":true}')

    recovered = ProjectEpisodeLibrary(tmp_path)
    recovered.recover()

    assert recovered.list() == []
    assert not target.exists()
    assert list(target.parent.glob("episode-001.json.quarantine-*"))
