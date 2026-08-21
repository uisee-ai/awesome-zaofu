from __future__ import annotations

import hashlib
import re
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scenarioforge.application import ScenarioForgeApplication
from scenarioforge.core import canonical_bytes, canonical_digest, strict_loads
from scenarioforge.runtime.smarts_worker import (
    CANONICAL_SMARTS_SCENARIOS,
    run_canonical_smarts_scenario,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
class CoordinatorError(RuntimeError):
    pass


class InvalidIdentifierError(CoordinatorError):
    pass


class UnknownScenarioError(CoordinatorError):
    pass


class UnknownRunError(CoordinatorError):
    pass


class RunExecutionError(CoordinatorError):
    pass


class SlotOccupiedError(CoordinatorError):
    status_code = 409

    def __init__(self, active_reference: RunReference) -> None:
        super().__init__("single-run execution slot is occupied")
        self.active_reference = active_reference


@dataclass(frozen=True)
class RunReference:
    schema_version: str
    scenario_id: str
    run_id: str
    attempt_id: str
    published_ref: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "published_ref": self.published_ref,
        }


@dataclass(frozen=True)
class ExecutionState:
    schema_version: str
    scenario_id: str
    run_id: str
    attempt_id: str
    state: str
    terminal: bool = False

    def __post_init__(self) -> None:
        if self.state not in {"starting", "running", "stopping"} or self.terminal:
            raise ValueError("ExecutionState accepts only non-terminal active states")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "state": self.state,
            "terminal": self.terminal,
        }


class _Application(Protocol):
    def run_single(
        self,
        scenario_path: Path | str,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: int,
    ) -> object: ...


@dataclass
class _RunRecord:
    idempotency_key: str
    reference: RunReference
    state: ExecutionState | None
    done: threading.Event
    error: BaseException | None = None


@dataclass
class _P1RunRecord:
    idempotency_key: str
    reference: RunReference
    state: ExecutionState | None
    done: threading.Event
    error: BaseException | None = None
    evidence_digest: str | None = None


def _validated_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise InvalidIdentifierError(f"invalid {label}")
    return value


class RunCoordinator:
    """Process-local single slot around the existing synchronous P0-A pipeline."""

    def __init__(
        self,
        *,
        workspace: Path,
        project_root: Path,
        timeout_seconds: int = 120,
        application: _Application | None = None,
        history_limit: int = 256,
        catalog_profile: str = "p0b",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if history_limit <= 0:
            raise ValueError("history_limit must be positive")
        self.workspace = Path(workspace)
        self.project_root = Path(project_root).resolve()
        from .catalog import registered_scenario_ids, registered_scenario_path

        scenario_paths: dict[str, Path] = {}
        for scenario_id in registered_scenario_ids(profile=catalog_profile):
            relative_path = registered_scenario_path(
                scenario_id,
                profile=catalog_profile,
            )
            scenario_path = (self.project_root / relative_path).resolve()
            try:
                scenario_path.relative_to(self.project_root)
            except ValueError as error:
                raise ValueError("registered scenario escaped project root") from error
            if scenario_path.is_symlink() or not scenario_path.is_file():
                raise ValueError("registered scenario is unavailable")
            scenario_paths[scenario_id] = scenario_path

        self.timeout_seconds = timeout_seconds
        self.history_limit = history_limit
        self._scenario_paths = scenario_paths
        self._application = application or ScenarioForgeApplication(
            workspace=self.workspace,
            project_root=self.project_root,
        )
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._records: OrderedDict[str, _RunRecord] = OrderedDict()
        self._idempotency: OrderedDict[str, str] = OrderedDict()

    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference:
        scenario_id = _validated_identifier(scenario_id, "scenario_id")
        idempotency_key = _validated_identifier(idempotency_key, "idempotency_key")
        if scenario_id not in self._scenario_paths:
            raise UnknownScenarioError("unknown scenario_id")

        with self._lock:
            prior_run_id = self._idempotency.get(idempotency_key)
            if prior_run_id is not None:
                return self._records[prior_run_id].reference
            if self._active_run_id is not None:
                active = self._records[self._active_run_id].reference
                raise SlotOccupiedError(active)

            run_id = self._new_identifier("run")
            attempt_id = self._new_identifier("attempt")
            reference = RunReference(
                schema_version="scenarioforge.run-reference/v1",
                scenario_id=scenario_id,
                run_id=run_id,
                attempt_id=attempt_id,
                published_ref=f"published/{run_id}/{attempt_id}",
            )
            record = _RunRecord(
                idempotency_key=idempotency_key,
                reference=reference,
                state=ExecutionState(
                    schema_version="scenarioforge.execution-state/v1",
                    scenario_id=scenario_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    state="starting",
                ),
                done=threading.Event(),
            )
            self._records[run_id] = record
            self._idempotency[idempotency_key] = run_id
            self._active_run_id = run_id
            self._prune_history()
            worker = threading.Thread(
                target=self._execute,
                args=(record,),
                name=f"scenarioforge-{run_id}",
            )
            worker.start()
            return reference

    def active_state(self, run_id: str) -> ExecutionState | None:
        run_id = _validated_identifier(run_id, "run_id")
        with self._lock:
            return self._record(run_id).state

    def reference(self, run_id: str) -> RunReference:
        run_id = _validated_identifier(run_id, "run_id")
        with self._lock:
            return self._record(run_id).reference

    def wait_for_terminal(self, run_id: str, *, timeout: float | None = None) -> RunReference:
        run_id = _validated_identifier(run_id, "run_id")
        with self._lock:
            record = self._record(run_id)
        if not record.done.wait(timeout=timeout):
            raise TimeoutError("run did not reach terminal publication before timeout")
        if record.error is not None:
            raise RunExecutionError("run ended without immutable terminal publication") from record.error
        return record.reference

    def interrupt_active_for_shutdown(self) -> bool:
        """Request service-owned interruption; this is not a Web run control."""
        with self._lock:
            if self._active_run_id is None:
                return False
            record = self._records[self._active_run_id]
            reference = record.reference
            record.state = ExecutionState(
                schema_version="scenarioforge.execution-state/v1",
                scenario_id=reference.scenario_id,
                run_id=reference.run_id,
                attempt_id=reference.attempt_id,
                state="stopping",
            )
        interrupt = getattr(self._application, "interrupt_active_for_shutdown", None)
        if interrupt is None:
            raise RunExecutionError("application has no service-shutdown interruption seam")
        interrupted = bool(interrupt())
        if not interrupted:
            with self._lock:
                if self._active_run_id == reference.run_id:
                    record.state = ExecutionState(
                        schema_version="scenarioforge.execution-state/v1",
                        scenario_id=reference.scenario_id,
                        run_id=reference.run_id,
                        attempt_id=reference.attempt_id,
                        state="running",
                    )
        return interrupted

    def _record(self, run_id: str) -> _RunRecord:
        try:
            return self._records[run_id]
        except KeyError as error:
            raise UnknownRunError("unknown run_id") from error

    def _new_identifier(self, prefix: str) -> str:
        while True:
            value = f"{prefix}-{secrets.token_hex(12)}"
            if value not in self._records:
                return value

    def _execute(self, record: _RunRecord) -> None:
        reference = record.reference
        with self._lock:
            record.state = ExecutionState(
                schema_version="scenarioforge.execution-state/v1",
                scenario_id=reference.scenario_id,
                run_id=reference.run_id,
                attempt_id=reference.attempt_id,
                state="running",
            )
        try:
            self._application.run_single(
                self._scenario_paths[reference.scenario_id],
                run_id=reference.run_id,
                attempt_id=reference.attempt_id,
                timeout_seconds=self.timeout_seconds,
            )
        except BaseException as error:
            record.error = error
        finally:
            with self._lock:
                record.state = None
                if self._active_run_id == reference.run_id:
                    self._active_run_id = None
                record.done.set()

    def _prune_history(self) -> None:
        while len(self._records) > self.history_limit:
            removable = next(
                (
                    run_id
                    for run_id, record in self._records.items()
                    if record.done.is_set() and run_id != self._active_run_id
                ),
                None,
            )
            if removable is None:
                return
            record = self._records.pop(removable)
            self._idempotency.pop(record.idempotency_key, None)


P1Runner = Callable[..., dict[str, Any]]


class P1RunCoordinator:
    """Single-slot real SMARTS runner with immutable, Web-readable publication."""

    def __init__(
        self,
        *,
        workspace: Path,
        max_episode_steps: int = 220,
        runner: P1Runner = run_canonical_smarts_scenario,
        history_limit: int = 256,
    ) -> None:
        if (
            isinstance(max_episode_steps, bool)
            or not isinstance(max_episode_steps, int)
            or max_episode_steps < 1
        ):
            raise ValueError("max_episode_steps must be positive")
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self.workspace = Path(workspace)
        self.publish_root = self.workspace / "p1-smarts-runs"
        self.max_episode_steps = max_episode_steps
        self.history_limit = history_limit
        self._runner = runner
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._records: OrderedDict[str, _P1RunRecord] = OrderedDict()
        self._idempotency: OrderedDict[str, str] = OrderedDict()

    def start(self, scenario_id: str, *, idempotency_key: str) -> RunReference:
        scenario_id = _validated_identifier(scenario_id, "scenario_id")
        idempotency_key = _validated_identifier(idempotency_key, "idempotency_key")
        if scenario_id not in CANONICAL_SMARTS_SCENARIOS:
            raise UnknownScenarioError("unknown P1 SMARTS scenario_id")
        with self._lock:
            prior_run_id = self._idempotency.get(idempotency_key)
            if prior_run_id is not None:
                prior = self._records[prior_run_id].reference
                if prior.scenario_id != scenario_id:
                    raise InvalidIdentifierError(
                        "idempotency_key is already bound to another scenario"
                    )
                return prior
            if self._active_run_id is not None:
                raise SlotOccupiedError(
                    self._records[self._active_run_id].reference
                )
            run_id = self._new_identifier("p1-run")
            attempt_id = self._new_identifier("attempt")
            reference = RunReference(
                schema_version="scenarioforge.p1-run-reference/v1",
                scenario_id=scenario_id,
                run_id=run_id,
                attempt_id=attempt_id,
                published_ref=f"p1-smarts-runs/{run_id}/{attempt_id}",
            )
            record = _P1RunRecord(
                idempotency_key=idempotency_key,
                reference=reference,
                state=ExecutionState(
                    schema_version="scenarioforge.p1-execution-state/v1",
                    scenario_id=scenario_id,
                    run_id=run_id,
                    attempt_id=attempt_id,
                    state="starting",
                ),
                done=threading.Event(),
            )
            self._records[run_id] = record
            self._idempotency[idempotency_key] = run_id
            self._active_run_id = run_id
            self._prune_history()
            threading.Thread(
                target=self._execute,
                args=(record,),
                name=f"scenarioforge-smarts-{run_id}",
            ).start()
            return reference

    def active_state(self, run_id: str) -> ExecutionState | None:
        run_id = _validated_identifier(run_id, "run_id")
        with self._lock:
            return self._record(run_id).state

    def reference(self, run_id: str) -> RunReference:
        run_id = _validated_identifier(run_id, "run_id")
        with self._lock:
            return self._record(run_id).reference

    def wait_for_terminal(
        self, run_id: str, *, timeout: float | None = None
    ) -> RunReference:
        run_id = _validated_identifier(run_id, "run_id")
        with self._lock:
            record = self._record(run_id)
        if not record.done.wait(timeout):
            raise TimeoutError("P1 SMARTS run did not reach terminal publication")
        if record.error is not None:
            raise RunExecutionError(
                "P1 SMARTS run ended without immutable terminal publication"
            ) from record.error
        return record.reference

    def terminal(self, run_id: str) -> dict[str, object]:
        reference, evidence, evidence_digest = self._opened_evidence(run_id)
        playback = self._playback(reference, evidence)
        metrics = evidence["metrics"]
        terminal_state = evidence["terminal_state"]
        completed_steps = int(metrics["completed_steps"])
        return {
            "schema_version": "scenarioforge.p1-terminal-evidence/v1",
            "scenario_id": reference.scenario_id,
            "run_id": reference.run_id,
            "attempt_id": reference.attempt_id,
            "terminal": True,
            "immutable": True,
            "execution_status": str(terminal_state["status"]),
            "scenario_outcome": "recorded",
            "termination_reason": str(terminal_state["reason"]),
            "failure_stage": None,
            "playable": True,
            "playback_reason": None,
            "seed": int(evidence["seed"]),
            "policy": {
                "id": "scenarioforge.p1.canonical-policy",
                "version": str(evidence["policy_digest"])[:12],
            },
            "backend": {
                "id": "scenarioforge.smarts",
                "version": "2.0.1",
                "engine_class": "SMARTS",
            },
            "logical_ref": reference.published_ref,
            "digests": {
                "run_manifest": str(evidence["execution_snapshot_digest"]),
                "artifact_index": evidence_digest,
                "evidence": evidence_digest,
                "trajectory": str(playback["trajectory_digest"]),
            },
            "metrics": {
                "collision": any(
                    bool(point.get("collision"))
                    for point in evidence["trajectory"]
                ),
                "collision_participants": sorted(
                    {
                        str(point["agent_id"])
                        for point in evidence["trajectory"]
                        if bool(point.get("collision"))
                    }
                ),
                "min_ttc_s": metrics["min_ttc_s"],
                "completion_time_s": round(
                    completed_steps * float(evidence["fixed_timestep_s"]), 9
                ),
                "completed_steps": completed_steps,
                "terminal_tick": int(playback["terminal_tick"]),
            },
            "events": deepcopy(playback["events"]),
            "evidence": [
                {
                    "ref": f"{reference.published_ref}/smarts_evidence.json",
                    "status": "present",
                    "validation": "verified",
                    "digest": evidence_digest,
                }
            ],
        }

    def playback(self, run_id: str) -> dict[str, object]:
        reference, evidence, _ = self._opened_evidence(run_id)
        return self._playback(reference, evidence)

    def interrupt_active_for_shutdown(self) -> bool:
        # SMARTS is short-lived and currently has no safe cross-thread stop API.
        return False

    def _execute(self, record: _P1RunRecord) -> None:
        reference = record.reference
        with self._lock:
            record.state = ExecutionState(
                schema_version="scenarioforge.p1-execution-state/v1",
                scenario_id=reference.scenario_id,
                run_id=reference.run_id,
                attempt_id=reference.attempt_id,
                state="running",
            )
        try:
            evidence = self._runner(
                reference.scenario_id,
                run_id=reference.run_id,
                max_episode_steps=self.max_episode_steps,
            )
            record.evidence_digest = self._publish(reference, evidence)
        except BaseException as error:
            record.error = error
        finally:
            with self._lock:
                record.state = None
                if self._active_run_id == reference.run_id:
                    self._active_run_id = None
                record.done.set()

    def _publish(
        self, reference: RunReference, evidence: Mapping[str, Any]
    ) -> str:
        if evidence.get("run_id") != reference.run_id:
            raise RunExecutionError("SMARTS evidence run identity is invalid")
        if evidence.get("scenario_id") != reference.scenario_id:
            raise RunExecutionError("SMARTS evidence scenario identity is invalid")
        if evidence.get("backend") != {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
        }:
            raise RunExecutionError("SMARTS evidence backend identity is invalid")
        if evidence.get("road_geometry") is None:
            raise RunExecutionError("SMARTS evidence lacks recorded road geometry")
        destination = (
            self.publish_root / reference.run_id / reference.attempt_id
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            raise RunExecutionError("immutable SMARTS publication already exists")
        staging = destination.with_name(
            f".{reference.attempt_id}.tmp-{secrets.token_hex(8)}"
        )
        staging.mkdir()
        payload = canonical_bytes(evidence)
        try:
            (staging / "smarts_evidence.json").write_bytes(payload)
            staging.rename(destination)
        finally:
            if staging.exists():
                for child in staging.iterdir():
                    child.unlink()
                staging.rmdir()
        return hashlib.sha256(payload).hexdigest()

    def _opened_evidence(
        self, run_id: str
    ) -> tuple[RunReference, dict[str, Any], str]:
        run_id = _validated_identifier(run_id, "run_id")
        with self._lock:
            record = self._record(run_id)
            reference = record.reference
            active = record.state
            error = record.error
            expected_digest = record.evidence_digest
        if active is not None:
            raise RunExecutionError("P1 SMARTS run is not terminal")
        if error is not None:
            raise RunExecutionError("P1 SMARTS run failed") from error
        path = (
            self.publish_root
            / reference.run_id
            / reference.attempt_id
            / "smarts_evidence.json"
        )
        if path.is_symlink() or not path.is_file():
            raise RunExecutionError("immutable SMARTS evidence is unavailable")
        payload = path.read_bytes()
        value = strict_loads(payload)
        if not isinstance(value, dict) or canonical_bytes(value) != payload:
            raise RunExecutionError("immutable SMARTS evidence is not canonical")
        if value.get("run_id") != reference.run_id:
            raise RunExecutionError("immutable SMARTS evidence identity drifted")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if expected_digest is None or actual_digest != expected_digest:
            raise RunExecutionError("immutable SMARTS evidence digest drifted")
        return reference, value, actual_digest

    @staticmethod
    def _playback(
        reference: RunReference, evidence: Mapping[str, Any]
    ) -> dict[str, object]:
        raw_events = evidence["events"]
        trajectory = []
        for point in evidence["trajectory"]:
            participant_id = str(point["agent_id"])
            tick = int(point["tick"])
            active_event = next(
                (
                    item
                    for item in raw_events
                    if str(item["agent_id"]) == participant_id
                    and int(item["tick"]) <= tick
                    < int(item["tick"]) + int(item.get("duration_ticks", 1))
                ),
                None,
            )
            action = {} if active_event is None else active_event["action"]
            longitudinal = float(action.get("throttle_brake", 0.0))
            trajectory.append(
                {
                    "schema_version": "scenarioforge.p1-trajectory-point/v1",
                    "participant_id": participant_id,
                    "tick": tick,
                    "position_m": [
                        float(point["position_m"][0]),
                        float(point["position_m"][1]),
                    ],
                    "heading_deg": float(point["heading_deg"]),
                    "speed_mps": float(point["speed_mps"]),
                    "brake": max(0.0, -longitudinal),
                    "collision": bool(point.get("collision")),
                    "signals": deepcopy(point.get("signals", [])),
                }
            )
        terminal_tick = max(int(item["tick"]) for item in trajectory)
        events = [
            {
                "event_id": str(item["event_id"]),
                "participant_id": str(item["agent_id"]),
                "trigger_tick": int(item["tick"]),
                "effect_state_tick": int(item["tick"]),
                "duration_ticks": int(item.get("duration_ticks", 1)),
                "action": deepcopy(item["action"]),
            }
            for item in raw_events
        ]
        geometry = deepcopy(evidence["road_geometry"])
        participants = [
            {"id": str(item["id"]), "role": str(item["role"])}
            for item in evidence["participants"]
        ]
        return {
            "schema_version": "scenarioforge.p1-playback/v1",
            "scenario_id": reference.scenario_id,
            "run_id": reference.run_id,
            "attempt_id": reference.attempt_id,
            "execution_status": "completed",
            "scenario_outcome": "recorded",
            "termination_reason": str(evidence["terminal_state"]["reason"]),
            "logical_ref": f"{reference.published_ref}/smarts_evidence.json",
            "trajectory_digest": canonical_digest(trajectory),
            "coordinate_system": str(geometry["coordinate_system"]),
            "traffic_rule": str(geometry["traffic_rule"]),
            "road": {
                "schema_version": "scenarioforge.p1-road/v1",
                "topology_kind": str(geometry["topology_kind"]),
                "geometry": geometry,
            },
            "participants": participants,
            "sample_interval_s": float(evidence["fixed_timestep_s"]),
            "terminal_tick": terminal_tick,
            "events": events,
            "trajectory": trajectory,
            "camera": {
                "default_mode": "ego-follow",
                "available_modes": ["ego-follow", "overview", "fixed", "free"],
                "target_participant_id": "ego",
                "pose_source": "recorded-trajectory",
            },
        }

    def _record(self, run_id: str) -> _P1RunRecord:
        try:
            return self._records[run_id]
        except KeyError as error:
            raise UnknownRunError("unknown P1 SMARTS run_id") from error

    def _new_identifier(self, prefix: str) -> str:
        while True:
            value = f"{prefix}-{secrets.token_hex(12)}"
            if value not in self._records:
                return value

    def _prune_history(self) -> None:
        while len(self._records) > self.history_limit:
            removable = next(
                (
                    run_id
                    for run_id, record in self._records.items()
                    if record.done.is_set() and run_id != self._active_run_id
                ),
                None,
            )
            if removable is None:
                return
            record = self._records.pop(removable)
            self._idempotency.pop(record.idempotency_key, None)
