from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from scenarioforge.core.canonical import CanonicalModel


@dataclass(frozen=True)
class TerminationEvidence(CanonicalModel):
    schema_version: str
    trigger: str
    process_group_id: int
    observed_pids: tuple[int, ...]
    signals_sent: tuple[str, ...]
    remaining_pids: tuple[int, ...]
    complete: bool


class ProcessTreeIsolationError(RuntimeError):
    pass


def _process_state_and_group(pid: int) -> tuple[str, int] | None:
    try:
        payload = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    closing_parenthesis = payload.rfind(")")
    if closing_parenthesis < 0:
        return None
    fields = payload[closing_parenthesis + 1 :].split()
    if len(fields) < 3:
        return None
    return fields[0], int(fields[2])


def live_process_group_members(process_group_id: int) -> tuple[int, ...]:
    """Return non-zombie Linux processes belonging to one process group."""
    members: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        record = _process_state_and_group(int(entry.name))
        if record is None:
            continue
        state, group = record
        if group == process_group_id and state != "Z":
            members.append(int(entry.name))
    return tuple(sorted(members))


def _wait_for_empty_group(process_group_id: int, timeout: float) -> tuple[int, ...]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = live_process_group_members(process_group_id)
        if not remaining or time.monotonic() >= deadline:
            return remaining
        time.sleep(0.01)


def terminate_process_tree(
    process: subprocess.Popen[object],
    *,
    trigger: str,
    terminate_timeout: float = 0.5,
    kill_timeout: float = 1.0,
) -> TerminationEvidence:
    """Terminate the new-session process group used by a single-run Worker."""
    process_group_id = process.pid
    observed = live_process_group_members(process_group_id)
    try:
        actual_process_group = os.getpgid(process.pid)
    except ProcessLookupError:
        actual_process_group = process_group_id if observed else None
    if actual_process_group is not None and actual_process_group != process_group_id:
        raise ProcessTreeIsolationError(
            "Worker was not launched in an isolated process group"
        )
    signals_sent: list[str] = []
    if actual_process_group is not None:
        try:
            os.killpg(process_group_id, signal.SIGTERM)
            signals_sent.append("SIGTERM")
        except ProcessLookupError:
            pass

    remaining = _wait_for_empty_group(process_group_id, terminate_timeout)
    if remaining:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
            signals_sent.append("SIGKILL")
        except ProcessLookupError:
            pass
        remaining = _wait_for_empty_group(process_group_id, kill_timeout)

    try:
        process.wait(timeout=kill_timeout)
    except subprocess.TimeoutExpired:
        remaining = live_process_group_members(process_group_id)

    return TerminationEvidence(
        schema_version="scenarioforge.process-tree-termination/v1",
        trigger=trigger,
        process_group_id=process_group_id,
        observed_pids=observed,
        signals_sent=tuple(signals_sent),
        remaining_pids=remaining,
        complete=not remaining,
    )
