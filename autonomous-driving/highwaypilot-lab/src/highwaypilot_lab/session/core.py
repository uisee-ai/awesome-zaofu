"""Python-authoritative session state machine for highwaypilot-ws/v1."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import secrets
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rfc8785

from highwaypilot_lab.protocol import PROTOCOL_VERSION, SessionCommand
from highwaypilot_lab.simulation import ConstructionSimulation, SimulationError
from highwaypilot_lab.model import ModelContractError
from highwaypilot_lab.strategies.policy import OnnxLearningPolicy, PolicyError, QualifiedRulePolicy, RandomPolicy
from highwaypilot_lab.episodes import EpisodeRecorder


MANUAL_ACTIONS = ["LANE_LEFT", "IDLE", "LANE_RIGHT", "FASTER", "SLOWER"]
CONTROL_MODES = {"manual", "random", "qualified_rule", "onnx"}
RESUME_WINDOW_SECONDS = 60.0


class ResumeError(RuntimeError):
    """Fail-closed resume response with a non-sensitive public code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RedactedCredential:
    """An in-memory-only credential handoff whose representations are redacted."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        self.__value = value

    def reveal(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return "RedactedCredential([REDACTED])"

    __str__ = __repr__


@dataclass(repr=False)
class CreatedSession:
    session: "Session"
    resume_token: RedactedCredential

    def __repr__(self) -> str:
        return f"CreatedSession(session_id={self.session.session_id!r}, resume_token=[REDACTED])"


@dataclass(frozen=True)
class _LedgerEntry:
    attachment_epoch: int
    simulation_generation: int
    canonical_command: bytes
    outcome: dict[str, Any]


@dataclass
class _PendingResume:
    attempt_id: str
    socket_id: str
    offer_id: str
    candidate_attachment_epoch: int
    new_token: str | None
    new_token_digest: str
    offer_template: dict[str, Any]
    restore_playing: bool


@dataclass(frozen=True)
class _CommittedResume:
    attempt_id: str
    socket_id: str
    offer_id: str
    result_template: dict[str, Any]


class _Outbox:
    """Bounded required delivery plus one coalescible playing snapshot."""

    def __init__(
        self,
        capacity: int,
        emergency_capacity: int,
        next_sequence: Callable[[], int],
    ) -> None:
        if capacity < 1:
            raise ValueError("outbox_capacity must be positive")
        if emergency_capacity < 0:
            raise ValueError("emergency_capacity must be non-negative")
        self.capacity = capacity
        self.emergency_capacity = emergency_capacity
        self._next_sequence = next_sequence
        self._required: list[dict[str, Any]] = []
        self._emergency: list[dict[str, Any]] = []
        self._lossy_snapshot: dict[str, Any] | None = None
        self._reservations = 0

    def _normal_used(self) -> int:
        return len(self._required) + self._reservations + int(self._lossy_snapshot is not None)

    def reserve(self, count: int = 1) -> bool:
        if count < 0:
            raise ValueError("reservation count must be non-negative")
        if self._normal_used() + count > self.capacity and self._lossy_snapshot is not None:
            self._lossy_snapshot = None
        if self._normal_used() + count > self.capacity:
            return False
        self._reservations += count
        return True

    def release(self, count: int) -> None:
        if count < 0 or count > self._reservations:
            raise RuntimeError("invalid outbox reservation release")
        self._reservations -= count

    @property
    def reservations(self) -> int:
        return self._reservations

    def _sequenced(self, template: Mapping[str, Any]) -> dict[str, Any]:
        message = copy.deepcopy(dict(template))
        message["server_seq"] = self._next_sequence()
        return message

    def emit_reserved(self, template: Mapping[str, Any]) -> dict[str, Any]:
        if self._reservations < 1:
            raise RuntimeError("required result slot was not reserved")
        self._reservations -= 1
        message = self._sequenced(template)
        self._required.append(message)
        return copy.deepcopy(message)

    def emit_required(self, template: Mapping[str, Any]) -> dict[str, Any] | None:
        if not self.reserve(1):
            return None
        return self.emit_reserved(template)

    def emit_emergency(self, template: Mapping[str, Any]) -> dict[str, Any] | None:
        if len(self._emergency) >= self.emergency_capacity:
            return None
        message = self._sequenced(template)
        self._emergency.append(message)
        return copy.deepcopy(message)

    def emit_lossy_snapshot(self, template: Mapping[str, Any]) -> bool:
        if self._lossy_snapshot is not None:
            self._lossy_snapshot = copy.deepcopy(dict(template))
            return True
        if self._normal_used() >= self.capacity:
            return False
        self._lossy_snapshot = copy.deepcopy(dict(template))
        return True

    def drain(self) -> list[dict[str, Any]]:
        messages = [*self._required, *self._emergency]
        if self._lossy_snapshot is not None:
            messages.append(self._sequenced(self._lossy_snapshot))
        messages.sort(key=lambda message: message["server_seq"])
        self._required = []
        self._emergency = []
        self._lossy_snapshot = None
        return copy.deepcopy(messages)


class Session:
    """Own one simulation generation and its serialized control boundary."""

    def __init__(
        self,
        effective_config: Mapping[str, Any],
        *,
        session_id: str,
        credential_digest: str,
        outbox_capacity: int,
        emergency_capacity: int,
        clock: Callable[[], float],
        entropy: Callable[[int], bytes],
        model_dir: str | Path | None,
    ) -> None:
        self.session_id = session_id
        self.socket_status = "attached"
        self.session_status = "active"
        self.simulation_status = "paused"
        self.playback_rate = 1.0
        self.control_mode = "manual"
        self._policy: Any = None
        self.simulation_generation = 0
        self.attachment_epoch = 0
        self.server_seq = 0
        self.state_seq = 0
        self.socket_open = True
        self.credential_digest: str | None = credential_digest

        self._simulation = ConstructionSimulation.from_config(effective_config)
        self._config = copy.deepcopy(self._simulation.effective_config)
        self._clock = clock
        self._created_at = clock()
        self._last_activity = self._created_at
        self._entropy = entropy
        self._model_dir = None if model_dir is None else Path(model_dir)
        self._lock = asyncio.Lock()
        self._ledger: dict[str, _LedgerEntry] = {}
        self._outbox = _Outbox(outbox_capacity, emergency_capacity, self._next_server_seq)
        self._detach_started_at: float | None = None
        self._restore_playing_intent = False
        self._pending: _PendingResume | None = None
        self._committed_resume: _CommittedResume | None = None

        self._playback_task: asyncio.Task[None] | None = None
        self._playback_ticks: asyncio.Queue[asyncio.Future[bool]] | None = None
        self._playback_release: asyncio.Event | None = None
        self._pending_manual_actions: deque[str] = deque()
        self._last_decision: dict[str, Any] | None = None
        initial = self._simulation.snapshot()
        self._episode_recorder = EpisodeRecorder(
            session_id=self.session_id,
            project_id="highwaypilot-lab-v7",
            initial_frame=initial,
            strategy={"id": "manual", "version": "manual-policy/v1", "model_version": None},
            seed=int(self._config["seed"]),
            effective_config=self._config,
            rng_contract=initial["rng"],
            versions={"application": "highwaypilot-lab/v1", "highway_env": "1.12.1", "gymnasium": "1.x", "python": "3.11+", "git": "working-tree", "platform": "local"},
        )

    @classmethod
    def create(
        cls,
        effective_config: Mapping[str, Any],
        *,
        outbox_capacity: int = 128,
        emergency_capacity: int = 1,
        clock: Callable[[], float] = time.monotonic,
        entropy: Callable[[int], bytes] = secrets.token_bytes,
        session_id: str | None = None,
        model_dir: str | Path | None = None,
    ) -> CreatedSession:
        token = cls._encode_secret(entropy(32))
        session = cls(
            effective_config,
            session_id=session_id or f"session-{uuid.uuid4().hex}",
            credential_digest=cls._digest(token),
            outbox_capacity=outbox_capacity,
            emergency_capacity=emergency_capacity,
            clock=clock,
            entropy=entropy,
            model_dir=model_dir,
        )
        return CreatedSession(session=session, resume_token=RedactedCredential(token))

    @staticmethod
    def _encode_secret(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    def _next_server_seq(self) -> int:
        self.server_seq += 1
        return self.server_seq

    @property
    def command_ids(self) -> frozenset[str]:
        return frozenset(self._ledger)

    @property
    def playback_task(self) -> asyncio.Task[None] | None:
        return self._playback_task

    @property
    def playback_task_running(self) -> bool:
        return self._playback_task is not None and not self._playback_task.done()

    @property
    def restore_playing_intent(self) -> bool:
        return self._restore_playing_intent

    @property
    def pending_plaintext_token(self) -> str | None:
        return None if self._pending is None else self._pending.new_token

    def credential_matches(self, token: str) -> bool:
        if self.credential_digest is None:
            return False
        return hmac.compare_digest(self.credential_digest, self._digest(token))

    def snapshot(self) -> dict[str, Any]:
        return self._simulation.snapshot()

    @property
    def effective_config(self) -> dict[str, Any]:
        return copy.deepcopy(self._config)

    def temporary_episode(self) -> dict[str, Any]:
        return self._episode_recorder.document()

    def _record_step(self, action: str, snapshot: Mapping[str, Any]) -> None:
        self._episode_recorder.append(action, snapshot, snapshot["reward"]["components"])
        status = snapshot.get("status", {})
        if status.get("terminated") or status.get("truncated"):
            self._episode_recorder.finish(
                result="terminated" if status.get("terminated") else "truncated",
                termination_reason=str(status.get("termination_reason") or "unknown"),
            )

    def export_diagnostics(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "socket_status": self.socket_status,
            "session_status": self.session_status,
            "simulation_status": self.simulation_status,
            "simulation_generation": self.simulation_generation,
            "attachment_epoch": self.attachment_epoch,
            "server_seq": self.server_seq,
            "state_seq": self.state_seq,
        }

    def _base_event(self, event_type: str) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "type": event_type,
            "session_id": self.session_id,
            "attachment_epoch": self.attachment_epoch,
            "simulation_generation": self.simulation_generation,
            "state_seq": self.state_seq,
            "playback_rate": self.playback_rate,
            "control_mode": self.control_mode,
        }

    def _command_result(self, command: SessionCommand, result: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **self._base_event("command.result"),
            "command_id": command.command_id,
            "result": copy.deepcopy(dict(result)),
        }

    def _command_error(
        self,
        command: SessionCommand,
        code: str,
        message: str,
        **details: Any,
    ) -> dict[str, Any]:
        return {
            **self._base_event("command.error"),
            "command_id": command.command_id,
            "error": {"code": code, "message": message, **copy.deepcopy(details)},
        }

    def _generic_error(self, code: str, message: str) -> dict[str, Any]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "type": "command.error",
            "error": {"code": code, "message": message},
        }

    async def submit(self, command: SessionCommand) -> dict[str, Any] | None:
        """Reserve first, then execute the frozen mutation ordering under one lock."""

        async with self._lock:
            self._last_activity = self._clock()
            if not self._outbox.reserve(1):
                backpressure = self._outbox.emit_emergency(
                    self._command_error(
                        command,
                        "BACKPRESSURE",
                        "command was not admitted; retry is safe",
                    )
                )
                if backpressure is not None:
                    return backpressure
                await self._detach_locked()
                return None

            if command.attachment_epoch != self.attachment_epoch:
                return self._outbox.emit_reserved(
                    self._command_error(
                        command,
                        "STALE_ATTACHMENT_EPOCH",
                        "attachment epoch is stale",
                    )
                )
            if command.simulation_generation != self.simulation_generation:
                return self._outbox.emit_reserved(
                    self._command_error(
                        command,
                        "STALE_SIMULATION_GENERATION",
                        "simulation generation is stale",
                    )
                )

            canonical = rfc8785.dumps(command.to_wire())
            ledger_entry = self._ledger.get(command.command_id)
            if ledger_entry is not None:
                if (
                    ledger_entry.attachment_epoch == command.attachment_epoch
                    and ledger_entry.simulation_generation == command.simulation_generation
                    and ledger_entry.canonical_command == canonical
                ):
                    return self._outbox.emit_reserved(ledger_entry.outcome)
                return self._outbox.emit_reserved(
                    self._command_error(
                        command,
                        "COMMAND_ID_REUSE",
                        "command_id was already bound to another canonical command",
                    )
                )

            if command.expected_state_seq != self.state_seq:
                outcome = self._command_error(
                    command,
                    "STALE_STATE",
                    "expected_state_seq does not match authoritative state",
                    current_state_seq=self.state_seq,
                )
                self._write_ledger(command, canonical, outcome)
                return self._outbox.emit_reserved(outcome)

            outcome = await self._execute_command_locked(command)
            self._write_ledger(command, canonical, outcome)
            return self._outbox.emit_reserved(outcome)

    def _write_ledger(
        self,
        command: SessionCommand,
        canonical: bytes,
        outcome: Mapping[str, Any],
    ) -> None:
        self._ledger[command.command_id] = _LedgerEntry(
            attachment_epoch=command.attachment_epoch,
            simulation_generation=command.simulation_generation,
            canonical_command=canonical,
            outcome=copy.deepcopy(dict(outcome)),
        )

    async def _execute_command_locked(self, command: SessionCommand) -> dict[str, Any]:
        if command.name == "control.set_mode":
            mode = command.payload.get("mode")
            if set(command.payload) != {"mode"} or mode not in CONTROL_MODES:
                return self._command_error(command, "INVALID_MODE", "mode must be manual, random, qualified_rule or onnx")
            try:
                policy = (
                    RandomPolicy(self._simulation.random_policy_generator())
                    if mode == "random" else QualifiedRulePolicy() if mode == "qualified_rule"
                    else OnnxLearningPolicy(self._model_dir) if mode == "onnx" and self._model_dir is not None
                    else None
                )
            except (ModelContractError, PolicyError, OSError) as error:
                return self._command_error(command, "MODEL_UNAVAILABLE", f"qualified ONNX model is unavailable: {error}")
            if mode == "onnx" and policy is None:
                return self._command_error(command, "MODEL_UNAVAILABLE", "qualified ONNX model directory is not configured")
            self.control_mode = str(mode)
            self._policy = policy
            self._pending_manual_actions.clear()
            strategy = self._policy
            self._episode_recorder.set_strategy({
                "id": getattr(strategy, "strategy_id", self.control_mode),
                "version": getattr(strategy, "strategy_version", f"{self.control_mode}-policy/v1"),
                "model_version": getattr(strategy, "model_version", None),
            })
            return self._command_result(command, {"control_mode": self.control_mode})

        if command.name in {"manual.action", "control.action"}:
            action = command.payload.get("action")
            available_actions = self.snapshot()["available_actions"]
            if (
                set(command.payload) != {"action"}
                or action not in MANUAL_ACTIONS
                or action not in available_actions
                or self.control_mode != "manual"
                or self.simulation_status not in {"paused", "playing"}
            ):
                return self._command_error(
                    command,
                    "INVALID_ACTION",
                    "action is not currently available",
                    available_actions=(available_actions if self.simulation_status in {"paused", "playing"} else []),
                )
            if self.simulation_status == "playing":
                self._queue_live_manual_action(action)
            else:
                try:
                    snapshot = self._simulation.step(action)
                except SimulationError:
                    return self._command_error(
                        command,
                        "INVALID_ACTION",
                        "action is not currently available",
                        available_actions=[],
                    )
                self._record_step(action, snapshot)
                self._last_decision = {"strategy_id": "manual", "action": action, "reason": "user_action"}
                self.state_seq += 1
            return self._command_result(
                command,
                {
                    "accepted_action": action,
                    "queued": self.simulation_status == "playing",
                    "available_actions": self.snapshot()["available_actions"],
                    "snapshot": self.snapshot(),
                },
            )

        if command.name == "simulation.set_rate":
            rate = command.payload.get("rate")
            if set(command.payload) != {"rate"} or rate not in {0.5, 1, 2, 4}:
                return self._command_error(command, "INVALID_RATE", "rate must be one of 0.5, 1, 2, 4")
            self.playback_rate = float(rate)
            return self._command_result(command, {"playback_rate": self.playback_rate})

        if command.payload:
            return self._command_error(
                command,
                "INVALID_COMMAND",
                "this command requires an empty payload",
            )

        if command.name == "simulation.play":
            if self.simulation_status == "terminated":
                return self._command_error(command, "INVALID_STATE", "simulation is terminal")
            if self.simulation_status != "playing":
                self._start_playback_locked(dormant=False)
                self.simulation_status = "playing"
            return self._command_result(
                command,
                {"simulation_status": self.simulation_status},
            )
        if command.name == "simulation.pause":
            await self._cancel_playback_locked()
            self.simulation_status = "paused"
            return self._command_result(command, {"simulation_status": "paused"})
        if command.name == "simulation.step":
            if self.simulation_status != "paused":
                return self._command_error(command, "INVALID_STATE", "pause before stepping")
            try:
                snapshot = self._simulation.step("IDLE")
            except SimulationError:
                self.simulation_status = "terminated"
                return self._command_error(command, "INVALID_STATE", "simulation is terminal")
            self.state_seq += 1
            self._record_step("IDLE", snapshot)
            return self._command_result(
                command,
                {"simulation_status": "paused", "snapshot": self.snapshot()},
            )
        if command.name == "simulation.reset":
            await self._cancel_playback_locked()
            self._pending_manual_actions.clear()
            self._simulation.close()
            self._simulation = ConstructionSimulation.from_config(self._config)
            initial = self._simulation.snapshot()
            if self.control_mode == "random":
                self._policy = RandomPolicy(self._simulation.random_policy_generator())
            elif self.control_mode == "qualified_rule":
                self._policy = QualifiedRulePolicy()
            elif self.control_mode == "onnx" and self._policy is not None:
                self._policy.reset()
            else:
                self._policy = None
            strategy = self._policy
            self._episode_recorder = EpisodeRecorder(
                session_id=self.session_id,
                project_id="highwaypilot-lab-v7",
                initial_frame=initial,
                strategy={
                    "id": getattr(strategy, "strategy_id", self.control_mode),
                    "version": getattr(strategy, "strategy_version", f"{self.control_mode}-policy/v1"),
                    "model_version": getattr(strategy, "model_version", None),
                },
                seed=int(self._config["seed"]),
                effective_config=self._config,
                rng_contract=initial["rng"],
                versions={"application": "highwaypilot-lab/v1", "highway_env": "1.12.1", "gymnasium": "1.x", "python": "3.11+", "git": "working-tree", "platform": "local"},
            )
            self.simulation_generation += 1
            self.state_seq = 0
            self.simulation_status = "paused"
            return self._command_result(
                command,
                {
                    "simulation_generation": self.simulation_generation,
                    "simulation_status": "paused",
                    "snapshot": self.snapshot(),
                },
            )
        if command.name == "session.close":
            await self._close_locked()
            return self._command_result(command, {"session_status": "closed"})
        return self._command_error(command, "INVALID_COMMAND", "unknown command")

    def _queue_live_manual_action(self, action: str) -> None:
        """Queue human intent without making a fresh click wait behind stale input.

        A lane command is latency-sensitive, so it becomes the next policy action
        and supersedes older lateral/hold commands. Reversing acceleration intent
        cancels queued commands in the opposite direction. Repeated commands in
        the same direction remain meaningful because each one advances one
        DiscreteMetaAction target-speed level.
        """

        lateral_or_hold = {"LANE_LEFT", "LANE_RIGHT", "IDLE"}
        if action in {"LANE_LEFT", "LANE_RIGHT"}:
            retained = [item for item in self._pending_manual_actions if item not in lateral_or_hold]
            self._pending_manual_actions.clear()
            self._pending_manual_actions.append(action)
            self._pending_manual_actions.extend(retained)
            return
        if action == "IDLE":
            self._pending_manual_actions.clear()
            self._pending_manual_actions.append(action)
            return
        opposite = "SLOWER" if action == "FASTER" else "FASTER"
        retained = [item for item in self._pending_manual_actions if item != opposite]
        self._pending_manual_actions.clear()
        self._pending_manual_actions.extend(retained)
        self._pending_manual_actions.append(action)

    def _start_playback_locked(self, *, dormant: bool) -> None:
        if self.playback_task_running:
            return
        ticks: asyncio.Queue[asyncio.Future[bool]] = asyncio.Queue()
        release = asyncio.Event()
        self._playback_ticks = ticks
        self._playback_release = release
        self._playback_task = asyncio.create_task(self._playback_loop(ticks, release))
        if not dormant:
            release.set()

    async def _playback_loop(
        self,
        ticks: asyncio.Queue[asyncio.Future[bool]],
        release: asyncio.Event,
    ) -> None:
        try:
            await release.wait()
            while True:
                acknowledgement = await ticks.get()
                async with self._lock:
                    if (
                        self._playback_task is not asyncio.current_task()
                        or self.simulation_status != "playing"
                        or self.socket_status != "attached"
                    ):
                        if not acknowledgement.done():
                            acknowledgement.set_result(False)
                        continue
                    if self.control_mode == "manual":
                        available_actions = set(self.snapshot()["available_actions"])
                        while (
                            self._pending_manual_actions
                            and self._pending_manual_actions[0] not in available_actions
                        ):
                            self._pending_manual_actions.popleft()
                        action = self._pending_manual_actions.popleft() if self._pending_manual_actions else "IDLE"
                        self._last_decision = {"strategy_id": "manual", "action": action, "reason": "queued_user_action"}
                    else:
                        decision = self._policy.decide(self.snapshot()) if self._policy is not None else None
                        action = decision.action if decision is not None else "IDLE"
                        self._last_decision = None if decision is None else decision.to_dict()
                    try:
                        snapshot = self._simulation.step(action)
                    except SimulationError:
                        self.simulation_status = "terminated"
                        result = False
                    else:
                        self._record_step(action, snapshot)
                        self.state_seq += 1
                        self.publish_snapshot(lossy_playing=True)
                        result = True
                    if not acknowledgement.done():
                        acknowledgement.set_result(result)
        except asyncio.CancelledError:
            raise
        finally:
            while not ticks.empty():
                acknowledgement = ticks.get_nowait()
                if not acknowledgement.done():
                    acknowledgement.set_result(False)

    async def _cancel_playback_locked(self) -> None:
        task = self._playback_task
        self._playback_task = None
        self._playback_ticks = None
        self._playback_release = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def tick_playback(self) -> bool:
        async with self._lock:
            if not self.playback_task_running or self._playback_ticks is None:
                return False
            acknowledgement: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._playback_ticks.put_nowait(acknowledgement)
        return await acknowledgement

    def publish_snapshot(self, *, lossy_playing: bool, reason: str = "playing") -> bool:
        template = {
            **self._base_event("simulation.snapshot"),
            "reason": reason,
            "simulation_status": self.simulation_status,
            "snapshot": self.snapshot(),
        }
        if self._last_decision is not None:
            template["decision"] = copy.deepcopy(self._last_decision)
        if lossy_playing:
            return self._outbox.emit_lossy_snapshot(template)
        return self._outbox.emit_required(template) is not None

    def drain_outbox(self) -> list[dict[str, Any]]:
        return self._outbox.drain()

    async def detach(self) -> None:
        async with self._lock:
            await self._detach_locked()

    def expired(self, now: float | None = None) -> bool:
        current = self._clock() if now is None else now
        if self.session_status == "closed":
            return True
        if self._detach_started_at is not None and current - self._detach_started_at >= RESUME_WINDOW_SECONDS:
            return True
        return current - self._last_activity >= 15 * 60 or current - self._created_at >= 2 * 60 * 60

    async def _detach_locked(self) -> None:
        already_detached = self.socket_status == "detached" and self._detach_started_at is not None
        was_playing = self.simulation_status == "playing" or self._restore_playing_intent
        await self._cancel_playback_locked()
        self._restore_playing_intent = was_playing
        self.simulation_status = "paused"
        self.socket_status = "detached"
        self.socket_open = False
        if not already_detached:
            self._detach_started_at = self._clock()

    def _resume_expired(self) -> bool:
        return (
            self._detach_started_at is None
            or self._clock() - self._detach_started_at > RESUME_WINDOW_SECONDS
        )

    async def resume_offer(
        self,
        resume_token: str,
        resume_attempt_id: str,
        socket_id: str,
    ) -> dict[str, Any]:
        async with self._lock:
            if len(resume_attempt_id) != 22 or "=" in resume_attempt_id:
                raise ResumeError("RESUME_INVALID")
            if self._resume_expired():
                await self._close_locked()
                raise ResumeError("RESUME_INVALID")
            if not self.credential_matches(resume_token):
                raise ResumeError("RESUME_INVALID")

            if self._pending is not None:
                if self._pending.attempt_id != resume_attempt_id:
                    raise ResumeError("RESUME_INVALID")
                replay = self._outbox.emit_required(self._pending.offer_template)
                if replay is None:
                    raise ResumeError("BACKPRESSURE")
                self._pending.socket_id = socket_id
                return replay

            required_slots = 2 + int(self._restore_playing_intent)
            if not self._outbox.reserve(required_slots):
                raise ResumeError("BACKPRESSURE")

            new_token = self._encode_secret(self._entropy(32))
            offer_id = f"offer-{uuid.uuid4().hex}"
            template = {
                **self._base_event("resume.offer"),
                "resume_attempt_id": resume_attempt_id,
                "offer_id": offer_id,
                "candidate_attachment_epoch": self.attachment_epoch + 1,
                "new_resume_token": new_token,
                "paused_snapshot": self.snapshot(),
                "restore_playing_intent": self._restore_playing_intent,
            }
            self._pending = _PendingResume(
                attempt_id=resume_attempt_id,
                socket_id=socket_id,
                offer_id=offer_id,
                candidate_attachment_epoch=self.attachment_epoch + 1,
                new_token=new_token,
                new_token_digest=self._digest(new_token),
                offer_template=copy.deepcopy(template),
                restore_playing=self._restore_playing_intent,
            )
            self.session_status = "resume_pending"
            return self._outbox.emit_reserved(template)

    async def resume_commit(
        self,
        resume_attempt_id: str,
        offer_id: str,
        socket_id: str,
    ) -> dict[str, Any]:
        async with self._lock:
            if self._committed_resume is not None:
                committed = self._committed_resume
                if (
                    committed.attempt_id == resume_attempt_id
                    and committed.offer_id == offer_id
                    and committed.socket_id == socket_id
                ):
                    replay = self._outbox.emit_required(committed.result_template)
                    if replay is None:
                        raise ResumeError("BACKPRESSURE")
                    return replay
                raise ResumeError("RESUME_INVALID")
            if self._resume_expired():
                await self._close_locked()
                raise ResumeError("RESUME_INVALID")
            pending = self._pending
            if (
                pending is None
                or pending.attempt_id != resume_attempt_id
                or pending.offer_id != offer_id
                or pending.socket_id != socket_id
                or pending.new_token is None
            ):
                raise ResumeError("RESUME_INVALID")

            self.attachment_epoch = pending.candidate_attachment_epoch
            self.credential_digest = pending.new_token_digest
            self.socket_status = "attached"
            self.socket_open = True
            self.session_status = "active"
            self.simulation_status = "paused"

            playing_restored = False
            if pending.restore_playing:
                try:
                    self._start_playback_locked(dormant=True)
                except Exception:
                    await self._cancel_playback_locked()
                else:
                    playing_restored = True

            result_template = {
                **self._base_event("resume.commit_result"),
                "resume_attempt_id": resume_attempt_id,
                "offer_id": offer_id,
                "committed": True,
                "playing_restored": playing_restored,
                "paused_snapshot": self.snapshot(),
            }
            result = self._outbox.emit_reserved(result_template)

            if playing_restored:
                self.simulation_status = "playing"
                self._outbox.emit_reserved(
                    {
                        **self._base_event("simulation.status"),
                        "simulation_status": "playing",
                    }
                )
                assert self._playback_release is not None
                self._playback_release.set()

            if self._outbox.reservations:
                self._outbox.release(self._outbox.reservations)
            pending.new_token = None
            self._pending = None
            self._restore_playing_intent = False
            self._committed_resume = _CommittedResume(
                attempt_id=resume_attempt_id,
                socket_id=socket_id,
                offer_id=offer_id,
                result_template=copy.deepcopy(result_template),
            )
            return result

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        await self._cancel_playback_locked()
        if self._outbox.reservations:
            self._outbox.release(self._outbox.reservations)
        if self._pending is not None:
            self._pending.new_token = None
        self._pending = None
        self._committed_resume = None
        self.credential_digest = None
        self.socket_status = "detached"
        self.socket_open = False
        self.session_status = "closed"
        self.simulation_status = "paused"
        self._simulation.close()


class SessionRegistry:
    """Session-scoped routing that hides cross-session existence."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, effective_config: Mapping[str, Any], **options: Any) -> CreatedSession:
        created = Session.create(effective_config, **options)
        self._sessions[created.session.session_id] = created.session
        return created

    async def submit(
        self,
        owner_session_id: str,
        command: SessionCommand,
    ) -> dict[str, Any] | None:
        session = self._sessions.get(owner_session_id)
        if session is None or command.session_id != owner_session_id:
            return {
                "protocol_version": PROTOCOL_VERSION,
                "type": "command.error",
                "error": {"code": "SESSION_NOT_FOUND", "message": "session is unavailable"},
            }
        return await session.submit(command)

    async def cleanup_expired(self) -> list[str]:
        expired: list[str] = []
        for session_id, session in list(self._sessions.items()):
            if session.expired():
                await session.close()
                self._sessions.pop(session_id, None)
                expired.append(session_id)
        return expired

    async def close_all(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
