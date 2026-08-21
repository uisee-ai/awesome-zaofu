from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scenarioforge.core import canonical_bytes, canonical_digest, strict_loads

from .contracts import Action, Observation, Termination, TrajectorySample

_ASSET_ROOT = Path(__file__).resolve().parents[3] / "assets" / "p1" / "smarts"
_MANIFEST_PATH = _ASSET_ROOT / "asset-manifest.json"
_ASSET_FIELDS = {
    "asset_id",
    "seed",
    "scenario_digest",
    "policy_digest",
    "parameters_digest",
    "map_dir",
    "map_sha256",
    "traffic_file",
    "traffic_sha256",
    "participants",
    "missions",
    "lane_aliases",
    "events",
    "default_actions",
    "external_actors",
}
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CANONICAL_SMARTS_SCENARIOS = (
    "competitive_lane_change",
    "cross_traffic_red_light_violation",
    "highway_merge",
    "pedestrian_red_light_crossing",
    "unprotected_left_turn",
)


def _rounded(value: Any) -> float:
    return round(float(value), 9)


def _road_geometry(road_map: Any, asset: Mapping[str, Any]) -> dict[str, Any]:
    """Sample the road geometry that the locked SMARTS map actually loaded."""
    from smarts.core.coordinates import RefLinePoint

    graph = getattr(road_map, "_graph", None)
    get_edges = getattr(graph, "getEdges", None)
    if not callable(get_edges):
        raise SmartsWorkerError("SMARTS road-map lane enumeration is unavailable")
    lanes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in sorted(get_edges(), key=lambda item: str(item.getID())):
        for native_lane in sorted(edge.getLanes(), key=lambda item: str(item.getID())):
            lane_id = str(native_lane.getID())
            if lane_id in seen:
                raise SmartsWorkerError("SMARTS road-map lane identity is duplicated")
            seen.add(lane_id)
            lane = road_map.lane_by_id(lane_id)
            length = float(lane.length)
            if not math.isfinite(length) or length <= 0:
                raise SmartsWorkerError("SMARTS road-map lane length is invalid")
            sample_count = min(129, max(2, math.ceil(length / 4.0) + 1))
            centerline: list[list[float]] = []
            left: list[list[float]] = []
            right: list[list[float]] = []
            previous_direction: tuple[float, float] | None = None
            for index in range(sample_count):
                offset = length * index / (sample_count - 1)
                if index == sample_count - 1:
                    offset = max(0.0, length - 1e-4)
                point = lane.from_lane_coord(RefLinePoint(s=offset))
                vector = lane.vector_at_offset(offset)
                direction_x = float(vector[0])
                direction_y = float(vector[1])
                norm = math.hypot(direction_x, direction_y)
                if norm <= 1e-8:
                    if previous_direction is None:
                        raise SmartsWorkerError(
                            "SMARTS road-map lane direction is invalid"
                        )
                    direction_x, direction_y = previous_direction
                else:
                    direction_x /= norm
                    direction_y /= norm
                    previous_direction = (direction_x, direction_y)
                raw_width = lane.width_at_offset(offset)
                width = float(raw_width[0] if isinstance(raw_width, tuple) else raw_width)
                if not math.isfinite(width) or width <= 0:
                    raise SmartsWorkerError("SMARTS road-map lane width is invalid")
                half_width = width / 2.0
                x = float(point.x)
                y = float(point.y)
                centerline.append([_rounded(x), _rounded(y)])
                left.append(
                    [
                        _rounded(x - direction_y * half_width),
                        _rounded(y + direction_x * half_width),
                    ]
                )
                right.append(
                    [
                        _rounded(x + direction_y * half_width),
                        _rounded(y - direction_x * half_width),
                    ]
                )
            lanes.append(
                {
                    "lane_id": lane_id,
                    "road_id": str(edge.getID()),
                    "kind": "connector" if lane_id.startswith(":") else "road",
                    "centerline_m": centerline,
                    "left_boundary_m": left,
                    "right_boundary_m": right,
                }
            )
    if not lanes:
        raise SmartsWorkerError("SMARTS road-map contains no renderable lanes")
    return {
        "schema_version": "scenarioforge.smarts-road-geometry/v1",
        "source": "scenarioforge.smarts/2.0.1:road-map",
        "coordinate_system": "right-handed-map-x-east-y-north-z-up",
        "traffic_rule": "right-hand-traffic",
        "topology_kind": (
            "intersection" if str(asset["map_dir"]) == "intersection" else "corridor"
        ),
        "lanes": lanes,
        "conflict_zones": [],
    }


class SmartsWorkerError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_path(relative: Any, *, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise SmartsWorkerError(f"{label} path is invalid")
    candidate = (_ASSET_ROOT / relative).resolve()
    try:
        candidate.relative_to(_ASSET_ROOT.resolve())
    except ValueError as error:
        raise SmartsWorkerError(f"{label} path escapes the SMARTS asset root") from error
    return candidate


def _load_manifest() -> Mapping[str, Any]:
    value = strict_loads(_MANIFEST_PATH.read_bytes())
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "scenarios"}:
        raise SmartsWorkerError("SMARTS asset manifest fields are invalid")
    if value["schema_version"] != "scenarioforge.smarts-assets/v1":
        raise SmartsWorkerError("SMARTS asset manifest schema is unsupported")
    scenarios = value["scenarios"]
    if not isinstance(scenarios, Mapping) or tuple(sorted(scenarios)) != CANONICAL_SMARTS_SCENARIOS:
        raise SmartsWorkerError("SMARTS asset manifest must bind the five canonical scenarios")
    asset_ids: set[str] = set()
    for scenario_id in CANONICAL_SMARTS_SCENARIOS:
        asset = scenarios[scenario_id]
        if not isinstance(asset, Mapping) or set(asset) != _ASSET_FIELDS:
            raise SmartsWorkerError(f"SMARTS asset fields are invalid: {scenario_id}")
        asset_id = asset["asset_id"]
        if (
            not isinstance(asset_id, str)
            or not _PUBLIC_ID_RE.fullmatch(asset_id)
            or asset_id in asset_ids
        ):
            raise SmartsWorkerError(f"SMARTS asset id is invalid or duplicate: {scenario_id}")
        asset_ids.add(asset_id)
        for field in (
            "scenario_digest",
            "policy_digest",
            "parameters_digest",
            "map_sha256",
            "traffic_sha256",
        ):
            if not isinstance(asset[field], str) or not _DIGEST_RE.fullmatch(asset[field]):
                raise SmartsWorkerError(f"SMARTS {field} is invalid: {scenario_id}")
        map_path = _asset_path(f"{asset['map_dir']}/map.net.xml", label="map")
        traffic_path = _asset_path(asset["traffic_file"], label="traffic")
        if not map_path.is_file() or _sha256(map_path) != asset["map_sha256"]:
            raise SmartsWorkerError(f"SMARTS map digest mismatch: {scenario_id}")
        if not traffic_path.is_file() or _sha256(traffic_path) != asset["traffic_sha256"]:
            raise SmartsWorkerError(f"SMARTS traffic digest mismatch: {scenario_id}")
    return value


def _scenario_asset(scenario_id: str) -> Mapping[str, Any]:
    if scenario_id not in CANONICAL_SMARTS_SCENARIOS:
        raise SmartsWorkerError(f"SMARTS scenario id is unsupported: {scenario_id}")
    scenarios = _load_manifest()["scenarios"]
    assert isinstance(scenarios, Mapping)
    asset = scenarios[scenario_id]
    assert isinstance(asset, Mapping)
    return asset


def _asset_from_execution(execution: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    asset_id = execution.get("scenario_asset_id")
    digest = execution.get("scenario_asset_digest")
    for scenario_id in CANONICAL_SMARTS_SCENARIOS:
        asset = _scenario_asset(scenario_id)
        if asset["asset_id"] != asset_id:
            continue
        if digest != canonical_digest(asset):
            raise SmartsWorkerError("SMARTS scenario asset digest mismatch")
        if execution.get("participants") != asset["participants"]:
            raise SmartsWorkerError("SMARTS participant binding does not match the asset")
        if execution.get("events") != asset["events"]:
            raise SmartsWorkerError("SMARTS event binding does not match the asset")
        return scenario_id, asset
    raise SmartsWorkerError("SMARTS scenario asset id is not registered")


def canonical_smarts_execution(
    scenario_id: str,
    *,
    max_episode_steps: int = 80,
) -> dict[str, Any]:
    if (
        isinstance(max_episode_steps, bool)
        or not isinstance(max_episode_steps, int)
        or max_episode_steps < 1
    ):
        raise SmartsWorkerError("SMARTS max_episode_steps must be a positive integer")
    asset = _scenario_asset(scenario_id)
    return {
        "schema_version": "scenarioforge.smarts-execution/v1",
        "seed": int(asset["seed"]),
        "scenario_asset_id": str(asset["asset_id"]),
        "scenario_asset_digest": canonical_digest(asset),
        "fixed_timestep_s": 0.1,
        "max_episode_steps": max_episode_steps,
        "participants": asset["participants"],
        "events": asset["events"],
    }


class SmartsEnvironment:
    """Worker-only wrapper for one pinned, content-bound SMARTS lifecycle."""

    action_mode = "lane_with_speed"

    engine_info = {
        "distribution": "smarts",
        "version": "2.0.1",
        "engine_class": "SMARTS",
    }

    def __init__(
        self,
        execution: Mapping[str, Any],
        scenario_id: str,
        asset: Mapping[str, Any],
    ) -> None:
        self._execution = execution
        self._scenario_id = scenario_id
        self._asset = asset
        self._simulator: Any | None = None
        self._scenario: Any | None = None
        self._tick = 0
        self.closed = False
        self._participant_roles = {
            str(item["id"]): str(item["role"])
            for item in asset["participants"]
        }
        self._social_ids = tuple(
            str(item["id"])
            for item in asset["participants"]
            if not bool(item["controllable"])
        )
        self.road_geometry: dict[str, Any] | None = None

    @classmethod
    def from_execution_snapshot(
        cls,
        execution: Mapping[str, Any],
    ) -> "SmartsEnvironment":
        scenario_id, asset = _asset_from_execution(execution)
        return cls(execution, scenario_id, asset)

    def reset(self, *, seed: int) -> Mapping[str, Any]:
        if self._simulator is not None:
            raise SmartsWorkerError("SMARTS environment is already started")
        if self.closed:
            raise SmartsWorkerError("SMARTS environment is closed")
        if seed != self._execution["seed"]:
            raise SmartsWorkerError("SMARTS reset seed does not match the execution")

        from smarts.core import seed as smarts_seed
        from smarts.core.agent_interface import AgentInterface, AgentType
        from smarts.core.local_traffic_provider import LocalTrafficProvider
        from smarts.core.scenario import Scenario
        from smarts.core.smarts import SMARTS
        from smarts.sstudio import types as studio_types

        smarts_seed(seed)
        map_root = _asset_path(str(self._asset["map_dir"]), label="map")
        traffic_path = _asset_path(self._asset["traffic_file"], label="traffic")
        road_map, _ = Scenario.build_map(str(map_root))
        if road_map is None:
            raise SmartsWorkerError("SMARTS scenario map could not be loaded")
        self.road_geometry = _road_geometry(road_map, self._asset)

        controllable_ids = [
            str(item["id"])
            for item in self._asset["participants"]
            if bool(item["controllable"])
        ]
        missions: dict[str, Any] = {}
        for agent_id in controllable_ids:
            mission = self._asset["missions"].get(agent_id)
            if not isinstance(mission, Mapping):
                raise SmartsWorkerError(f"SMARTS mission is missing: {agent_id}")
            route = studio_types.Route(
                begin=tuple(mission["begin"]),
                end=tuple(mission["end"]),
                via=tuple(str(item) for item in mission["via"]),
            )
            tactic = studio_types.TrapEntryTactic(
                start_time=0.0,
                wait_to_hijack_limit_s=0.0,
                exclusion_prefixes=self._social_ids,
                default_entry_speed=float(mission["start_speed_mps"]),
            )
            missions[agent_id] = Scenario._extract_mission(
                studio_types.Mission(route=route, entry_tactic=tactic),
                road_map,
            )

        interfaces = {
            agent_id: AgentInterface.from_type(
                AgentType.LanerWithSpeed,
                max_episode_steps=int(self._execution["max_episode_steps"]),
                signals=True,
                neighborhood_vehicle_states=True,
            )
            for agent_id in controllable_ids
        }
        scenario = Scenario(
            str(map_root),
            traffic_specs=[str(traffic_path)],
            missions=missions,
        )
        simulator = SMARTS(
            agent_interfaces=interfaces,
            traffic_sims=[LocalTrafficProvider()],
            envision=None,
            visdom=False,
            fixed_timestep_sec=float(self._execution["fixed_timestep_s"]),
            external_provider=bool(self._asset["external_actors"]),
        )
        self._scenario = scenario
        self._simulator = simulator
        try:
            observations = simulator.reset(scenario)
        except Exception:
            self.close()
            raise
        if not isinstance(observations, Mapping):
            self.close()
            raise SmartsWorkerError("SMARTS reset returned invalid observations")
        return observations

    def step(self, actions: Mapping[str, tuple[Any, ...]]) -> Any:
        if self._simulator is None:
            raise SmartsWorkerError("SMARTS environment is not started")
        self._tick += 1
        self._update_external_actors(self._tick)
        return self._simulator.step(dict(actions))

    def close(self) -> None:
        simulator = self._simulator
        self._simulator = None
        if simulator is not None:
            simulator.destroy()
        self.closed = True

    def canonical_agent_id(self, native_id: str) -> str:
        if native_id in self._participant_roles:
            return native_id
        for participant_id in self._social_ids:
            if native_id.startswith(f"{participant_id}-"):
                return participant_id
        return native_id

    def canonical_role(self, native_id: str) -> str:
        canonical_id = self.canonical_agent_id(native_id)
        return self._participant_roles.get(canonical_id, "social_vehicle")

    def canonical_road_id(self, native_id: str) -> str:
        aliases = self._asset["lane_aliases"]
        return str(aliases.get(native_id, native_id))

    def canonical_lane_id(self, native_id: str) -> str:
        aliases = self._asset["lane_aliases"]
        return str(aliases.get(native_id, native_id))

    def _update_external_actors(self, tick: int) -> None:
        if not self._asset["external_actors"]:
            return
        assert self._simulator is not None
        import numpy as np
        from smarts.core.actor import ActorRole
        from smarts.core.coordinates import Heading, Pose, RefLinePoint
        from smarts.core.utils.core_math import vec_to_radians
        from smarts.core.vehicle import VEHICLE_CONFIGS
        from smarts.core.vehicle_state import VehicleState

        states: list[Any] = []
        for actor in self._asset["external_actors"]:
            start_tick = int(actor["start_tick"])
            if tick < start_tick:
                continue
            road_id, lane_index, start_offset = actor["begin"]
            start_road = self._scenario.road_map.road_by_id(str(road_id))
            start_lane = start_road.lane_at_index(int(lane_index))
            end_road_id, end_lane_index, end_offset = actor["end"]
            end_road = self._scenario.road_map.road_by_id(str(end_road_id))
            end_lane = end_road.lane_at_index(int(end_lane_index))
            elapsed = (tick - start_tick) * float(self._execution["fixed_timestep_s"])
            speed = float(actor["speed_mps"])
            start_position = start_lane.from_lane_coord(
                RefLinePoint(
                    s=min(float(start_lane.length) - 1e-6, float(start_offset))
                )
            )
            end_position = end_lane.from_lane_coord(
                RefLinePoint(s=min(float(end_lane.length) - 1e-6, float(end_offset)))
            )
            start_vector = np.asarray(
                (float(start_position.x), float(start_position.y), 0.0),
                dtype=float,
            )
            end_vector = np.asarray(
                (float(end_position.x), float(end_position.y), 0.0),
                dtype=float,
            )
            travel = end_vector - start_vector
            distance = float(np.linalg.norm(travel[:2]))
            if distance <= 1e-8:
                raise SmartsWorkerError("SMARTS external actor path is degenerate")
            direction = travel / distance
            position = start_vector + direction * min(distance, speed * elapsed)
            heading = Heading(vec_to_radians(direction[:2]))
            states.append(
                VehicleState(
                    actor_id=str(actor["id"]),
                    actor_type="pedestrian",
                    source="scenarioforge.smarts-scripted-actor",
                    role=ActorRole.External,
                    pose=Pose.from_center(position, heading),
                    dimensions=VEHICLE_CONFIGS["pedestrian"].dimensions,
                    vehicle_config_type="pedestrian",
                    speed=speed,
                    linear_velocity=np.asarray(
                        (direction[0] * speed, direction[1] * speed, 0.0)
                    ),
                    angular_velocity=np.asarray((0.0, 0.0, 0.0)),
                    linear_acceleration=np.asarray((0.0, 0.0, 0.0)),
                    angular_acceleration=np.asarray((0.0, 0.0, 0.0)),
                )
            )
        self._simulator.external_provider.state_update(
            states,
            float(self._execution["fixed_timestep_s"]),
        )


def _minimum_ttc(trajectory: Sequence[Mapping[str, Any]]) -> float | None:
    by_tick: dict[int, list[Mapping[str, Any]]] = {}
    for sample in trajectory:
        by_tick.setdefault(int(sample["tick"]), []).append(sample)
    values: list[float] = []
    for states in by_tick.values():
        for left_index, left in enumerate(states):
            for right in states[left_index + 1 :]:
                dx = float(right["position_m"][0]) - float(left["position_m"][0])
                dy = float(right["position_m"][1]) - float(left["position_m"][1])
                left_heading = math.radians(float(left["heading_deg"]))
                right_heading = math.radians(float(right["heading_deg"]))
                dvx = float(right["speed_mps"]) * math.cos(right_heading) - float(
                    left["speed_mps"]
                ) * math.cos(left_heading)
                dvy = float(right["speed_mps"]) * math.sin(right_heading) - float(
                    left["speed_mps"]
                ) * math.sin(left_heading)
                closing = dx * dvx + dy * dvy
                distance_squared = dx * dx + dy * dy
                if closing < -1e-12 and distance_squared > 1e-12:
                    values.append(distance_squared / -closing)
    return round(min(values), 12) if values else None


def _trajectory_dict(sample: TrajectorySample) -> dict[str, Any]:
    value = sample.to_dict()
    return {
        "agent_id": value["agent_id"],
        "tick": value["tick"],
        "position_m": value["position_m"],
        "speed_mps": value["speed_mps"],
        "heading_deg": value["heading_deg"],
        "collision": bool(value["values"].get("collision_ids")),
        "signals": value["values"].get("signals", []),
    }


def _initial_trajectory(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for observation in observations:
        values = observation.values
        position = values["position_m"]
        samples.append(
            {
                "agent_id": observation.agent_id,
                "tick": observation.tick,
                "position_m": [float(position[0]), float(position[1]), float(position[2])],
                "speed_mps": float(values["speed_mps"]),
                "heading_deg": float(values["heading_deg"]),
                "collision": bool(values["collision_ids"]),
                "signals": values.get("signals", []),
            }
        )
    return samples


def _terminal_reason(
    terminations: Sequence[Termination],
    completed_steps: int,
    max_episode_steps: int,
) -> str:
    reasons = {item.reason for item in terminations if item.terminated or item.truncated}
    for reason in ("collision", "goal", "off_road", "off_route", "wrong_way"):
        if reason in reasons:
            return reason
    if "max_episode_steps" in reasons or completed_steps >= max_episode_steps - 1:
        return "max_episode_steps"
    return "backend_terminated"


def run_canonical_smarts_scenario(
    scenario_id: str,
    *,
    run_id: str,
    max_episode_steps: int = 80,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not _PUBLIC_ID_RE.fullmatch(run_id):
        raise SmartsWorkerError("SMARTS run_id is invalid")
    from .smarts_adapter import SmartsAdapter

    execution = canonical_smarts_execution(
        scenario_id,
        max_episode_steps=max_episode_steps,
    )
    asset = _scenario_asset(scenario_id)
    environment = SmartsEnvironment.from_execution_snapshot(execution)
    adapter = SmartsAdapter(environment_factory=lambda _: environment)
    declared_events = {
        int(event["tick"]): event for event in asset["events"]
    }
    default_actions = asset["default_actions"]
    active = tuple(
        str(item["id"])
        for item in execution["participants"]
        if bool(item["controllable"])
    )
    emitted_events: list[dict[str, Any]] = []
    terminations: tuple[Termination, ...] = ()
    completed_steps = 0
    try:
        initial = adapter.start(execution)
        trajectory = _initial_trajectory(initial)
        for tick in range(1, max_episode_steps + 1):
            if not active:
                break
            event = declared_events.get(tick)
            actions: list[Action] = []
            for agent_id in active:
                values = default_actions[agent_id]
                active_controller_events = (
                    item
                    for item in asset["events"]
                    if item["agent_id"] == agent_id
                    and int(item["tick"]) <= tick
                    < int(item["tick"]) + int(item.get("duration_ticks", 1))
                    and "controller_action" in item
                )
                controller_event = next(active_controller_events, None)
                if controller_event is not None:
                    values = controller_event["controller_action"]
                actions.append(
                    Action(
                        schema_version="scenarioforge.action/v1",
                        agent_id=agent_id,
                        tick=tick,
                        values=values,
                    )
                )
            step = adapter.step(tuple(actions))
            completed_steps = tick
            trajectory.extend(_trajectory_dict(sample) for sample in step.trajectory)
            terminations = step.terminations
            active = tuple(
                item.agent_id
                for item in terminations
                if not item.terminated and not item.truncated
            )
            if event is not None:
                emitted_events.append(
                    {
                        "event_id": str(event["event_id"]),
                        "agent_id": str(event["agent_id"]),
                        "tick": tick,
                        "action": dict(event["action"]),
                        "duration_ticks": int(event.get("duration_ticks", 1)),
                    }
                )
            if any(
                item.agent_id == "ego" and (item.terminated or item.truncated)
                for item in terminations
            ):
                break
    finally:
        adapter.close()

    reason = _terminal_reason(terminations, completed_steps, max_episode_steps)
    evidence = {
        "schema_version": "scenarioforge.smarts-run-evidence/v1",
        "scenario_id": scenario_id,
        "run_id": run_id,
        "execution_snapshot_digest": canonical_digest(execution),
        "backend": {"id": "scenarioforge.smarts", "version": "2.0.1"},
        "scenario_digest": str(asset["scenario_digest"]),
        "policy_digest": str(asset["policy_digest"]),
        "seed": int(execution["seed"]),
        "parameters_digest": str(asset["parameters_digest"]),
        "fixed_timestep_s": float(execution["fixed_timestep_s"]),
        "participants": [dict(item) for item in execution["participants"]],
        "events": emitted_events,
        "terminal_state": {"status": "completed", "reason": reason},
        "metrics": {
            "min_ttc_s": _minimum_ttc(trajectory),
            "completed_steps": completed_steps,
        },
        "trajectory": trajectory,
        "road_geometry": environment.road_geometry,
    }
    configured_root = os.environ.get("SCENARIOFORGE_SMARTS_EVIDENCE_DIR")
    if configured_root:
        publish_smarts_evidence(evidence, Path(configured_root))
    return evidence


def publish_smarts_evidence(
    evidence: Mapping[str, Any],
    output_root: Path,
) -> Path:
    run_id = evidence.get("run_id")
    if not isinstance(run_id, str) or not _PUBLIC_ID_RE.fullmatch(run_id):
        raise SmartsWorkerError("SMARTS evidence run_id is invalid")
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / f"{run_id}.json"
    output.write_bytes(canonical_bytes(evidence))
    return output


__all__ = [
    "CANONICAL_SMARTS_SCENARIOS",
    "SmartsEnvironment",
    "SmartsWorkerError",
    "canonical_smarts_execution",
    "publish_smarts_evidence",
    "run_canonical_smarts_scenario",
]
