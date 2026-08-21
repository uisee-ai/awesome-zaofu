from __future__ import annotations

from pathlib import Path

import pytest

from scenarioforge.security.errors import SecurityViolation
from scenarioforge.security.resources import (
    RELEASE_RESOURCE_LIMITS,
    DelegatedCgroupV2,
)


def _delegated_root(tmp_path: Path) -> Path:
    root = tmp_path / "delegated"
    root.mkdir()
    (root / "cgroup.controllers").write_text("cpu memory pids\n", encoding="utf-8")
    (root / "cgroup.subtree_control").write_text("cpu memory pids\n", encoding="utf-8")
    return root


def test_release_profile_is_exact_and_applied_before_attachment(tmp_path: Path) -> None:
    root = _delegated_root(tmp_path)
    controller = DelegatedCgroupV2(root)

    group = controller.create("experiment-0001-attempt-0001", RELEASE_RESOURCE_LIMITS)
    group.attach(4321)

    assert (group.path / "cpu.max").read_text(encoding="utf-8") == "100000 100000\n"
    assert (group.path / "memory.max").read_text(encoding="utf-8") == "4294967296\n"
    assert (group.path / "pids.max").read_text(encoding="utf-8") == "32\n"
    assert (group.path / "cgroup.procs").read_text(encoding="utf-8") == "4321\n"
    assert group.limits.to_dict() == {
        "cpu_max_quota": 100_000,
        "cpu_max_period": 100_000,
        "memory_mib": 4_096,
        "pids": 32,
        "timeout_seconds": 120,
        "log_bytes": 1_048_576,
        "artifact_bytes": 10_485_760,
    }


@pytest.mark.parametrize(
    "controllers",
    ["cpu memory", "cpu pids", "memory pids", ""],
)
def test_release_cgroup_fails_closed_without_complete_delegation(
    tmp_path: Path,
    controllers: str,
) -> None:
    root = tmp_path / "delegated"
    root.mkdir()
    (root / "cgroup.controllers").write_text(f"{controllers}\n", encoding="utf-8")
    (root / "cgroup.subtree_control").write_text(
        f"{controllers}\n", encoding="utf-8"
    )

    with pytest.raises(SecurityViolation, match="delegated cgroup v2"):
        DelegatedCgroupV2(root).create("attempt-0001", RELEASE_RESOURCE_LIMITS)


def test_release_cgroup_rejects_unsafe_group_identity(tmp_path: Path) -> None:
    with pytest.raises(SecurityViolation, match="cgroup identity"):
        DelegatedCgroupV2(_delegated_root(tmp_path)).create(
            "../escape", RELEASE_RESOURCE_LIMITS
        )
