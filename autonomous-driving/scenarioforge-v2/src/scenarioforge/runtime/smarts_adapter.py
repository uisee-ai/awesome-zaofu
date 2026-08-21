from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from scenarioforge.core import canonical_digest

from .contracts import (
    Action,
    AdapterDescriptor,
    AdapterStep,
    Observation,
    Reward,
    Termination,
    TrajectorySample,
)

_EXECUTION_FIELDS = frozenset(
    {
        "schema_version",
        "seed",
        "scenario_asset_id",
        "scenario_asset_digest",
        "fixed_timestep_s",
        "max_episode_steps",
        "participants",
        "events",
    }
)
_ROLES = {
    "ego": "ego",
    "controlled": "controlled",
    "social": "social_vehicle",
    "social_vehicle": "social_vehicle",
    "vulnerable_road_user": "pedestrian",
    "pedestrian": "pedestrian",
}
_EVENT_FIELDS = (
    "agents_alive_done",
    "interest_done",
    "not_moving",
    "off_road",
    "off_route",
    "on_shoulder",
    "reached_goal",
    "reached_max_episode_steps",
    "wrong_way",
)


class SmartsAdapterError(RuntimeError):
    pass


class _Environment(Protocol):
    action_mode: str

    def reset(self, *, seed: int) -> Any: ...

    def step(self, actions: Mapping[str, tuple[Any, ...]]) -> Any: ...

    def close(self) -> None: ...


EnvironmentFactory = Callable[[Mapping[str, Any]], _Environment]


def _default_environment_factory(execution: Mapping[str, Any]) -> _Environment:
    # Keep simulator imports behind the worker-only lifecycle seam.
    from .smarts_worker import SmartsEnvironment

    return SmartsEnvironment.from_execution_snapshot(execution)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise SmartsAdapterError(f"{label} must be finite")
    return result


def _position(value: Any) -> tuple[float, float, float]:
    raw = tuple(value)
    if len(raw) not in {2, 3}:
        raise SmartsAdapterError("SMARTS position must have two or three coordinates")
    coordinates = tuple(_finite(item, "position coordinate") for item in raw)
    if len(coordinates) == 2:
        return coordinates[0], coordinates[1], 0.0
    return coordinates


def _cartesian_heading_deg(value: Any) -> float:
    """Project SMARTS' north-zero heading onto map x/y mathematical degrees."""
    native = math.degrees(_finite(value, "heading"))
    projected = (native + 270.0) % 360.0 - 180.0
    return 0.0 if projected == -0.0 else projected


def _collision_ids(
    events: Any,
    canonicalize: Callable[[str], str] | None = None,
) -> list[str]:
    result: list[str] = []
    for collision in _field(events, "collisions", ()) or ():
        collision_id = _field(collision, "collidee_id", _field(collision, "id"))
        if collision_id is not None:
            value = str(collision_id)
            result.append(canonicalize(value) if canonicalize is not None else value)
    return sorted(set(result))


def _event_values(events: Any) -> dict[str, bool]:
    return {field: bool(_field(events, field, False)) for field in _EVENT_FIELDS}


def _signal_values(signals: Any) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for signal in signals or ():
        state = _field(signal, "state", "unknown")
        if hasattr(state, "name"):
            state = state.name
        stop_point = _field(signal, "stop_point")
        item: dict[str, Any] = {
            "signal_id": str(_field(signal, "id", _field(signal, "signal_id", "unknown"))),
            "state": str(state).lower(),
        }
        if stop_point is not None:
            item["stop_point_m"] = list(_position(stop_point))
        projected.append(item)
    return sorted(projected, key=lambda item: item["signal_id"])


class SmartsAdapter:
    """Versioned ScenarioForge DTO boundary around one SMARTS 2.0.1 run."""

    _identity = {"id": "scenarioforge.smarts", "version": "2.0.1"}
    descriptor = AdapterDescriptor(
        schema_version="scenarioforge.adapter-descriptor/v1",
        adapter_id=_identity["id"],
        adapter_version=_identity["version"],
        adapter_digest=canonical_digest(_identity),
    )

    def __init__(self, environment_factory: EnvironmentFactory | None = None) -> None:
        self._environment_factory = environment_factory or _default_environment_factory
        self._environment: _Environment | None = None
        self._tick = 0
        self._closed = False
        self._participant_order: tuple[str, ...] = ()
        self._roles: dict[str, str] = {}
        self._controllable: tuple[str, ...] = ()
        self._active_controllable: tuple[str, ...] = ()
        self._last_native_observations: dict[str, Any] = {}

    def start(self, execution_snapshot: Mapping[str, Any]) -> tuple[Observation, ...]:
        if self._environment is not None:
            raise SmartsAdapterError("SMARTS adapter is already started")
        if self._closed:
            raise SmartsAdapterError("SMARTS adapter is closed")
        execution = self._validate_execution(execution_snapshot)
        self._environment = self._environment_factory(execution)
        reset_result = self._environment.reset(seed=int(execution["seed"]))
        native_observations = reset_result[0] if isinstance(reset_result, tuple) else reset_result
        if not isinstance(native_observations, Mapping):
            self.close()
            raise SmartsAdapterError("SMARTS reset did not return agent observations")
        self._last_native_observations = dict(native_observations)
        return self._project_observations(native_observations, tick=0)

    def step(self, actions: tuple[Action, ...]) -> AdapterStep:
        if self._environment is None:
            raise SmartsAdapterError("SMARTS adapter is not started")
        target_tick = self._tick + 1
        expected = set(self._active_controllable)
        actual = {action.agent_id for action in actions}
        if len(actions) != len(actual) or actual != expected:
            raise SmartsAdapterError(
                "SMARTS requires exactly one action for every active controllable agent"
            )
        if any(action.tick != target_tick for action in actions):
            raise SmartsAdapterError(f"SMARTS actions must bind tick {target_tick}")

        native_actions = {
            action.agent_id: self._native_action(action) for action in actions
        }
        result = self._environment.step(native_actions)
        if not isinstance(result, tuple) or len(result) not in {4, 5}:
            raise SmartsAdapterError("SMARTS step returned an unsupported result")
        if len(result) == 5:
            native_observations, rewards, terminated, truncated, _ = result
        else:
            native_observations, rewards, dones, _ = result
            terminated = dones
            truncated = {agent_id: False for agent_id in expected}
        if not all(
            isinstance(item, Mapping)
            for item in (native_observations, rewards, terminated, truncated)
        ):
            raise SmartsAdapterError("SMARTS step mappings are invalid")

        self._tick = target_tick
        self._last_native_observations.update(native_observations)
        projected_observations = self._project_observations(
            native_observations, tick=target_tick
        )
        projected_rewards = tuple(
            Reward(
                schema_version="scenarioforge.reward/v1",
                agent_id=agent_id,
                tick=target_tick,
                value=_finite(rewards.get(agent_id, 0.0), "SMARTS reward"),
                components={
                    "smarts_reward": _finite(
                        rewards.get(agent_id, 0.0), "SMARTS reward"
                    )
                },
            )
            for agent_id in self._active_controllable
        )
        projected_terminations = tuple(
            self._termination(
                agent_id,
                tick=target_tick,
                terminated=bool(terminated.get(agent_id, False)),
                truncated=bool(truncated.get(agent_id, False)),
                native_observation=native_observations.get(
                    agent_id, self._last_native_observations.get(agent_id)
                ),
            )
            for agent_id in self._active_controllable
        )
        self._active_controllable = tuple(
            termination.agent_id
            for termination in projected_terminations
            if not termination.terminated and not termination.truncated
        )
        trajectory = tuple(
            self._trajectory_from_observation(item) for item in projected_observations
        )
        return AdapterStep(
            schema_version="scenarioforge.adapter-step/v1",
            tick=target_tick,
            observations=projected_observations,
            actions=tuple(actions),
            rewards=projected_rewards,
            terminations=projected_terminations,
            trajectory=trajectory,
        )

    def close(self) -> None:
        environment = self._environment
        self._environment = None
        if environment is not None:
            environment.close()
        self._closed = True

    def _validate_execution(self, value: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise SmartsAdapterError("SMARTS execution snapshot must be an object")
        unexpected = sorted(set(value) - _EXECUTION_FIELDS)
        if unexpected:
            raise SmartsAdapterError(
                f"unsupported execution field: {unexpected[0]}"
            )
        required = {
            "schema_version",
            "seed",
            "scenario_asset_id",
            "fixed_timestep_s",
            "max_episode_steps",
            "participants",
        }
        if required - set(value):
            raise SmartsAdapterError("SMARTS execution snapshot is incomplete")
        if value["schema_version"] != "scenarioforge.smarts-execution/v1":
            raise SmartsAdapterError("SMARTS execution schema is unsupported")
        if isinstance(value["seed"], bool) or not isinstance(value["seed"], int):
            raise SmartsAdapterError("SMARTS seed must be an integer")
        if not isinstance(value["scenario_asset_id"], str) or not value["scenario_asset_id"]:
            raise SmartsAdapterError("SMARTS scenario asset id is invalid")
        timestep = _finite(value["fixed_timestep_s"], "fixed timestep")
        if timestep <= 0:
            raise SmartsAdapterError("fixed timestep must be positive")
        max_steps = value["max_episode_steps"]
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
            raise SmartsAdapterError("max episode steps must be positive")

        participants = value["participants"]
        if not isinstance(participants, Sequence) or isinstance(
            participants, (str, bytes)
        ):
            raise SmartsAdapterError("SMARTS participants are invalid")
        order: list[str] = []
        roles: dict[str, str] = {}
        controllable: list[str] = []
        for participant in participants:
            if not isinstance(participant, Mapping):
                raise SmartsAdapterError("SMARTS participant is invalid")
            agent_id = participant.get("id")
            source_role = participant.get("role")
            if not isinstance(agent_id, str) or not agent_id or agent_id in roles:
                raise SmartsAdapterError("SMARTS participant id is invalid or duplicate")
            if source_role not in _ROLES:
                raise SmartsAdapterError("SMARTS participant role is unsupported")
            order.append(agent_id)
            roles[agent_id] = _ROLES[str(source_role)]
            if participant.get("controllable") is True:
                controllable.append(agent_id)
            elif participant.get("controllable") is not False:
                raise SmartsAdapterError("SMARTS controllable flag must be boolean")
        if len(controllable) < 2:
            raise SmartsAdapterError("SMARTS requires at least two controllable agents")
        if not any(roles[item] == "ego" for item in controllable):
            raise SmartsAdapterError("SMARTS controllable agents require one ego")

        self._participant_order = tuple(order)
        self._roles = roles
        self._controllable = tuple(controllable)
        self._active_controllable = self._controllable
        return value

    def _project_observations(
        self, native_observations: Mapping[str, Any], *, tick: int
    ) -> tuple[Observation, ...]:
        projected: dict[str, Observation] = {}
        for agent_id in self._controllable:
            native = native_observations.get(agent_id)
            if native is None:
                continue
            ego_state = _field(native, "ego_vehicle_state")
            if ego_state is None:
                raise SmartsAdapterError(
                    f"SMARTS observation lacks ego vehicle state: {agent_id}"
                )
            projected[agent_id] = self._observation(
                agent_id,
                self._roles[agent_id],
                tick,
                ego_state,
                native=native,
                under_control=True,
            )
            for social_state in _field(native, "neighborhood_vehicle_states", ()) or ():
                native_social_id = str(_field(social_state, "id", ""))
                social_id = self._canonical_agent_id(native_social_id)
                if not social_id or social_id in projected or social_id in self._controllable:
                    continue
                projected[social_id] = self._observation(
                    social_id,
                    self._canonical_role(native_social_id),
                    tick,
                    social_state,
                    native=None,
                    under_control=False,
                )
        order = {agent_id: index for index, agent_id in enumerate(self._participant_order)}
        return tuple(
            sorted(
                projected.values(),
                key=lambda item: (order.get(item.agent_id, len(order)), item.agent_id),
            )
        )

    def _observation(
        self,
        agent_id: str,
        role: str,
        tick: int,
        state: Any,
        *,
        native: Any | None,
        under_control: bool,
    ) -> Observation:
        events = _field(native, "events") if native is not None else None
        values: dict[str, Any] = {
            "collision_ids": _collision_ids(events, self._canonical_agent_id),
            "distance_travelled_m": _finite(
                _field(native, "distance_travelled", 0.0), "distance travelled"
            ),
            "elapsed_sim_time_s": _finite(
                _field(native, "elapsed_sim_time", 0.0), "elapsed simulation time"
            ),
            "events": _event_values(events),
            "heading_deg": _cartesian_heading_deg(_field(state, "heading", 0.0)),
            "lane_id": self._canonical_lane_id(
                str(_field(state, "lane_id", "unknown"))
            ),
            "lane_index": int(_field(state, "lane_index", -1)),
            "position_m": list(_position(_field(state, "position"))),
            "road_id": self._canonical_road_id(
                str(_field(state, "road_id", "unknown"))
            ),
            "speed_mps": _finite(_field(state, "speed", 0.0), "speed"),
            "steering_rad": _finite(_field(state, "steering", 0.0), "steering"),
            "under_agent_control": bool(
                _field(native, "under_this_agent_control", under_control)
            ),
            "yaw_rate_radps": _finite(_field(state, "yaw_rate", 0.0), "yaw rate"),
        }
        signals = _signal_values(_field(native, "signals", ())) if native is not None else []
        if signals:
            values["signals"] = signals
        return Observation(
            schema_version="scenarioforge.observation/v1",
            agent_id=agent_id,
            role=role,
            tick=tick,
            values=values,
        )

    @staticmethod
    def _trajectory_from_observation(observation: Observation) -> TrajectorySample:
        values = observation.values
        position = values["position_m"]
        return TrajectorySample(
            schema_version="scenarioforge.trajectory-sample/v1",
            agent_id=observation.agent_id,
            role=observation.role,
            tick=observation.tick,
            position_m=(float(position[0]), float(position[1]), float(position[2])),
            heading_deg=float(values["heading_deg"]),
            speed_mps=float(values["speed_mps"]),
            values={
                "collision_ids": values["collision_ids"],
                "events": values["events"],
                "lane_id": values["lane_id"],
                "lane_index": values["lane_index"],
                "road_id": values["road_id"],
                "signals": values.get("signals", []),
            },
        )

    def _native_action(self, action: Action) -> tuple[Any, ...]:
        values = action.values
        if getattr(self._environment, "action_mode", "continuous") == "lane_with_speed":
            if set(values) != {"target_speed_mps", "lane_change"}:
                raise SmartsAdapterError(
                    "SMARTS lane-following action fields are unsupported"
                )
            target_speed = _finite(values["target_speed_mps"], "target_speed_mps")
            lane_change = values["lane_change"]
            if target_speed < 0.0 or target_speed > 70.0:
                raise SmartsAdapterError(
                    "SMARTS target speed must be between 0 and 70 m/s"
                )
            if (
                isinstance(lane_change, bool)
                or not isinstance(lane_change, int)
                or lane_change not in {-1, 0, 1}
            ):
                raise SmartsAdapterError(
                    "SMARTS lane change must be -1, 0, or 1"
                )
            return target_speed, lane_change
        if set(values) == {"throttle_brake", "steering"}:
            longitudinal = _finite(values["throttle_brake"], "throttle_brake")
            throttle = max(0.0, longitudinal)
            brake = max(0.0, -longitudinal)
        elif set(values) == {"throttle", "brake", "steering"}:
            throttle = _finite(values["throttle"], "throttle")
            brake = _finite(values["brake"], "brake")
        else:
            raise SmartsAdapterError("SMARTS action fields are unsupported")
        steering = _finite(values["steering"], "steering")
        if any(value < 0.0 or value > 1.0 for value in (throttle, brake)):
            raise SmartsAdapterError("SMARTS throttle and brake must be between 0 and 1")
        if steering < -1.0 or steering > 1.0:
            raise SmartsAdapterError("SMARTS steering must be between -1 and 1")
        return throttle, brake, steering

    def _termination(
        self,
        agent_id: str,
        *,
        tick: int,
        terminated: bool,
        truncated: bool,
        native_observation: Any,
    ) -> Termination:
        events = _field(native_observation, "events")
        if _collision_ids(events, self._canonical_agent_id):
            reason = "collision"
        elif bool(_field(events, "reached_goal", False)):
            reason = "goal"
        elif bool(_field(events, "off_road", False)):
            reason = "off_road"
        elif bool(_field(events, "off_route", False)):
            reason = "off_route"
        elif bool(_field(events, "wrong_way", False)):
            reason = "wrong_way"
        elif bool(_field(events, "reached_max_episode_steps", False)) or truncated:
            reason = "max_episode_steps"
        elif terminated:
            reason = "backend_terminated"
        else:
            reason = "running"
        return Termination(
            schema_version="scenarioforge.termination/v1",
            agent_id=agent_id,
            tick=tick,
            terminated=terminated,
            truncated=truncated,
            reason=reason,
        )

    def _canonical_agent_id(self, native_id: str) -> str:
        environment = self._environment
        projector = getattr(environment, "canonical_agent_id", None)
        return str(projector(native_id)) if callable(projector) else native_id

    def _canonical_role(self, native_id: str) -> str:
        environment = self._environment
        projector = getattr(environment, "canonical_role", None)
        if callable(projector):
            return str(projector(native_id))
        canonical_id = self._canonical_agent_id(native_id)
        return self._roles.get(canonical_id, "social_vehicle")

    def _canonical_road_id(self, native_id: str) -> str:
        environment = self._environment
        projector = getattr(environment, "canonical_road_id", None)
        return str(projector(native_id)) if callable(projector) else native_id

    def _canonical_lane_id(self, native_id: str) -> str:
        environment = self._environment
        projector = getattr(environment, "canonical_lane_id", None)
        return str(projector(native_id)) if callable(projector) else native_id


__all__ = ["SmartsAdapter", "SmartsAdapterError"]
