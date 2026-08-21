from __future__ import annotations

import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .errors import SecurityViolation


_SAFE_CGROUP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


_POLICY_FIELDS = {
    "wall_clock_timeout_s",
    "memory_limit_mb",
    "pid_limit",
    "log_limit_bytes",
    "artifact_limit_bytes",
}


@dataclass(frozen=True)
class ResourcePolicy:
    wall_clock_timeout_s: float
    memory_limit_mb: int
    pid_limit: int
    log_limit_bytes: int
    artifact_limit_bytes: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ResourcePolicy":
        if set(value) != _POLICY_FIELDS:
            raise SecurityViolation(
                "resource policy fields do not match the frozen contract",
                code="invalid_resource_policy",
            )
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value.values()):
            raise SecurityViolation(
                "resource policy values must be numeric",
                code="invalid_resource_policy",
            )
        if any(float(item) <= 0 for item in value.values()):
            raise SecurityViolation(
                "resource policy values must be positive",
                code="invalid_resource_policy",
            )
        integer_fields = _POLICY_FIELDS - {"wall_clock_timeout_s"}
        if any(
            isinstance(value[field], bool) or not isinstance(value[field], int)
            for field in integer_fields
        ):
            raise SecurityViolation(
                "count and byte resource policy values must be integers",
                code="invalid_resource_policy",
            )
        return cls(
            wall_clock_timeout_s=float(value["wall_clock_timeout_s"]),
            memory_limit_mb=int(value["memory_limit_mb"]),
            pid_limit=int(value["pid_limit"]),
            log_limit_bytes=int(value["log_limit_bytes"]),
            artifact_limit_bytes=int(value["artifact_limit_bytes"]),
        )


@dataclass(frozen=True)
class HardResourceLimits:
    cpu_max_quota: int
    cpu_max_period: int
    memory_mib: int
    pids: int
    timeout_seconds: int
    log_bytes: int
    artifact_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "cpu_max_quota": self.cpu_max_quota,
            "cpu_max_period": self.cpu_max_period,
            "memory_mib": self.memory_mib,
            "pids": self.pids,
            "timeout_seconds": self.timeout_seconds,
            "log_bytes": self.log_bytes,
            "artifact_bytes": self.artifact_bytes,
        }


RELEASE_RESOURCE_LIMITS = HardResourceLimits(
    cpu_max_quota=100_000,
    cpu_max_period=100_000,
    memory_mib=4096,
    pids=32,
    timeout_seconds=120,
    log_bytes=1024 * 1024,
    artifact_bytes=10 * 1024 * 1024,
)


@dataclass(frozen=True)
class CgroupHandle:
    path: Path
    limits: HardResourceLimits

    def _write(self, name: str, value: str) -> None:
        try:
            (self.path / name).write_text(value, encoding="utf-8")
        except OSError as error:
            raise SecurityViolation(
                "delegated cgroup v2 hard enforcement is unavailable",
                code="cgroup_v2_unavailable",
            ) from error

    def attach(self, pid: int) -> None:
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise SecurityViolation("Worker pid is invalid", code="invalid_worker_pid")
        expected = {
            "cpu.max": f"{self.limits.cpu_max_quota} {self.limits.cpu_max_period}\n",
            "memory.max": f"{self.limits.memory_mib * 1024 * 1024}\n",
            "pids.max": f"{self.limits.pids}\n",
        }
        try:
            observed = {
                name: (self.path / name).read_text(encoding="utf-8")
                for name in expected
            }
        except OSError as error:
            raise SecurityViolation(
                "delegated cgroup v2 hard enforcement is unavailable",
                code="cgroup_v2_unavailable",
            ) from error
        if observed != expected:
            raise SecurityViolation(
                "delegated cgroup v2 limits were not applied",
                code="cgroup_v2_limit_mismatch",
            )
        self._write("cgroup.procs", f"{pid}\n")

    def remove(self) -> None:
        try:
            self.path.rmdir()
        except FileNotFoundError:
            return
        except OSError as error:
            raise SecurityViolation(
                "delegated cgroup v2 cleanup failed",
                code="cgroup_v2_cleanup_failed",
            ) from error


class DelegatedCgroupV2:
    """Fail-closed controller for one pre-delegated cgroup v2 subtree."""

    REQUIRED_CONTROLLERS = frozenset({"cpu", "memory", "pids"})

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @staticmethod
    def _controllers(path: Path) -> frozenset[str]:
        try:
            return frozenset(path.read_text(encoding="utf-8").split())
        except OSError as error:
            raise SecurityViolation(
                "delegated cgroup v2 hard enforcement is unavailable",
                code="cgroup_v2_unavailable",
            ) from error

    def create(self, identity: str, limits: HardResourceLimits) -> CgroupHandle:
        if not isinstance(identity, str) or _SAFE_CGROUP_ID.fullmatch(identity) is None:
            raise SecurityViolation(
                "cgroup identity is invalid",
                code="invalid_cgroup_identity",
            )
        available = self._controllers(self.root / "cgroup.controllers")
        delegated = self._controllers(self.root / "cgroup.subtree_control")
        if not self.REQUIRED_CONTROLLERS.issubset(available & delegated):
            raise SecurityViolation(
                "delegated cgroup v2 controllers are incomplete",
                code="cgroup_v2_unavailable",
            )
        path = self.root / identity
        try:
            path.mkdir(mode=0o700)
        except OSError as error:
            raise SecurityViolation(
                "delegated cgroup v2 hard enforcement is unavailable",
                code="cgroup_v2_unavailable",
            ) from error
        handle = CgroupHandle(path=path, limits=limits)
        try:
            handle._write(
                "cpu.max", f"{limits.cpu_max_quota} {limits.cpu_max_period}\n"
            )
            handle._write("memory.max", f"{limits.memory_mib * 1024 * 1024}\n")
            handle._write("pids.max", f"{limits.pids}\n")
        except BaseException:
            for child in path.iterdir():
                child.unlink(missing_ok=True)
            path.rmdir()
            raise
        return handle


@dataclass(frozen=True)
class ResourceObservation:
    elapsed_seconds: float
    memory_bytes: int
    process_count: int
    log_bytes: int
    artifact_bytes: int

    def __post_init__(self) -> None:
        if isinstance(self.elapsed_seconds, bool) or not isinstance(
            self.elapsed_seconds, (int, float)
        ):
            raise SecurityViolation(
                "elapsed resource observation must be numeric",
                code="invalid_resource_observation",
            )
        for value in (
            self.memory_bytes,
            self.process_count,
            self.log_bytes,
            self.artifact_bytes,
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise SecurityViolation(
                    "count and byte resource observations must be integers",
                    code="invalid_resource_observation",
                )
        if any(
            value < 0
            for value in (
                self.elapsed_seconds,
                self.memory_bytes,
                self.process_count,
                self.log_bytes,
                self.artifact_bytes,
            )
        ):
            raise SecurityViolation(
                "resource observations cannot be negative",
                code="invalid_resource_observation",
            )


def enforce_resource_policy(policy: ResourcePolicy, observed: ResourceObservation) -> None:
    checks = (
        (
            observed.elapsed_seconds > policy.wall_clock_timeout_s,
            "wall_clock_limit_exceeded",
        ),
        (
            observed.memory_bytes > policy.memory_limit_mb * 1024 * 1024,
            "memory_limit_exceeded",
        ),
        (observed.process_count > policy.pid_limit, "pid_limit_exceeded"),
        (observed.log_bytes > policy.log_limit_bytes, "log_limit_exceeded"),
        (observed.artifact_bytes > policy.artifact_limit_bytes, "artifact_limit_exceeded"),
    )
    for exceeded, code in checks:
        if exceeded:
            raise SecurityViolation("Worker exceeded a frozen resource limit", code=code)


def _process_group_and_rss(pid: int) -> tuple[str, int, int] | None:
    try:
        process_stat = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        resident_pages = int(
            (Path("/proc") / str(pid) / "statm").read_text(encoding="utf-8").split()[1]
        )
    except (FileNotFoundError, PermissionError, ProcessLookupError, IndexError, ValueError):
        return None
    closing_parenthesis = process_stat.rfind(")")
    if closing_parenthesis < 0:
        return None
    fields = process_stat[closing_parenthesis + 1 :].split()
    if len(fields) < 3:
        return None
    return fields[0], int(fields[2]), resident_pages * int(os.sysconf("SC_PAGE_SIZE"))


def _artifact_bytes(root: Path) -> int:
    if root.is_symlink() or not root.is_dir():
        raise SecurityViolation(
            "OutputStaging is not a regular directory",
            code="link_or_special_file",
        )
    total = 0
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if path.is_symlink() or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise SecurityViolation(
                "OutputStaging contains a link or special file",
                code="link_or_special_file",
            )
        if stat.S_ISREG(mode):
            total += path.stat().st_size
    return total


def observe_process_group(
    process_group_id: int,
    *,
    started_at: float,
    log_bytes: int,
    artifact_root: Path,
) -> ResourceObservation:
    process_count = 0
    memory_bytes = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        record = _process_group_and_rss(int(entry.name))
        if record is None:
            continue
        state, group, resident_bytes = record
        if group == process_group_id and state != "Z":
            process_count += 1
            memory_bytes += resident_bytes
    return ResourceObservation(
        elapsed_seconds=max(0.0, time.monotonic() - started_at),
        memory_bytes=memory_bytes,
        process_count=process_count,
        log_bytes=log_bytes,
        artifact_bytes=_artifact_bytes(Path(artifact_root)),
    )
