from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .contracts import Action, AdapterDescriptor, AdapterStep, Observation
from .policy import apply_declared_route_control, resolve_tick_actions


EngineLaneIndex = tuple[str, str, int]


class AdapterRegistryError(RuntimeError):
    pass


@runtime_checkable
class SimulatorAdapter(Protocol):
    """Backend-neutral lifecycle; engine-native objects stay behind this seam."""

    descriptor: AdapterDescriptor

    def start(self, execution_snapshot: Mapping[str, Any]) -> tuple[Observation, ...]: ...

    def step(self, actions: tuple[Action, ...]) -> AdapterStep: ...

    def close(self) -> None: ...


AdapterFactory = Callable[[], object]


class AdapterRegistry:
    """Server-owned registry that never interprets request data as import paths."""

    def __init__(self) -> None:
        self._registrations: dict[str, tuple[AdapterDescriptor, AdapterFactory]] = {}

    def register(self, descriptor: AdapterDescriptor, factory: AdapterFactory) -> None:
        if descriptor.adapter_id in self._registrations:
            raise AdapterRegistryError(f"adapter is already registered: {descriptor.adapter_id}")
        if not callable(factory):
            raise AdapterRegistryError("adapter factory is invalid")
        self._registrations[descriptor.adapter_id] = (descriptor, factory)

    def descriptor(self, adapter_id: str) -> AdapterDescriptor:
        registration = self._registrations.get(adapter_id)
        if registration is None:
            raise AdapterRegistryError(f"adapter id is invalid or not registered: {adapter_id}")
        return registration[0]

    def create(self, adapter_id: str) -> object:
        descriptor, factory = self._registration(adapter_id)
        adapter = factory()
        if getattr(adapter, "descriptor", None) != descriptor:
            raise AdapterRegistryError("registered adapter descriptor mismatch")
        return adapter

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def _registration(self, adapter_id: str) -> tuple[AdapterDescriptor, AdapterFactory]:
        registration = self._registrations.get(adapter_id)
        if registration is None:
            raise AdapterRegistryError(f"adapter id is invalid or not registered: {adapter_id}")
        return registration


def _engine_lane_index(binding: Mapping[str, Any]) -> EngineLaneIndex:
    return (
        str(binding["start_node"]),
        str(binding["end_node"]),
        int(binding["lane_index"]),
    )


def _angular_distance_deg(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


class MetaDriveAdapter:
    """Worker-only adapter for one real headless MultiAgentMetaDrive run."""

    def __init__(self, plan: Mapping[str, Any]) -> None:
        self.plan = plan
        self._environment: Any | None = None
        self._participant_to_agent = {
            participant["id"]: f"agent{index}"
            for index, participant in enumerate(plan["participants"])
        }
        self._stable_to_engine: dict[str, EngineLaneIndex] = {}
        self._engine_to_stable: dict[EngineLaneIndex, str] = {}
        if plan["schema_version"] == "scenarioforge.execution-plan/v2":
            for lane in plan["simulation"]["topology"]["lanes"]:
                stable_id = str(lane["id"])
                engine_index = _engine_lane_index(lane["engine_lane_index"])
                self._stable_to_engine[stable_id] = engine_index
                self._engine_to_stable[engine_index] = stable_id

    def _config(self) -> dict[str, Any]:
        simulation = self.plan["simulation"]
        is_v2 = self.plan["schema_version"] == "scenarioforge.execution-plan/v2"
        agent_configs: dict[str, dict[str, Any]] = {}
        for index, participant in enumerate(self.plan["participants"]):
            initial = participant["spawn"] if is_v2 else participant["initial"]
            if is_v2:
                lane_index = self._stable_to_engine[str(initial["lane_id"])]
                goal_lane = self._stable_to_engine[
                    str(participant["route"]["goal"]["lane_id"])
                ]
            else:
                lane_index = (">", ">>", int(initial["lane"]))
                goal_lane = None
            config: dict[str, Any] = {
                "spawn_lane_index": lane_index,
                "spawn_longitude": float(initial["longitudinal_m"]),
                "spawn_lateral": float(initial.get("lateral_m", 0.0)),
                "spawn_velocity": [float(initial["speed_mps"]), 0.0],
                "spawn_velocity_car_frame": True,
                "use_special_color": participant["role"] == "ego",
            }
            if goal_lane is not None:
                # MetaDrive 0.4.3 NodeNetworkNavigation accepts the final road
                # node and resolves the rightmost lane of that final road.
                config["destination"] = goal_lane[1]
            agent_configs[f"agent{index}"] = config
        return {
            "num_agents": len(agent_configs),
            "agent_configs": agent_configs,
            "allow_respawn": False,
            "delay_done": int(simulation["max_steps"]) + 1,
            "map_config": {
                "type": "block_sequence",
                "config": simulation["map_block_sequence"],
                "lane_width": float(simulation["lane_width_m"]),
                "lane_num": int(simulation["lane_count"]),
                "exit_length": float(simulation["length_m"]),
                "start_position": [0, 0],
            },
            "use_render": False,
            "image_observation": False,
            "random_agent_model": False,
            "traffic_density": 0.0,
            "accident_prob": 0.0,
            "physics_world_step_size": float(simulation["physics_world_step_size_s"]),
            "decision_repeat": int(simulation["decision_repeat"]),
            "horizon": int(simulation["max_steps"]),
            "truncate_as_terminate": False,
            "num_scenarios": 1,
            "start_seed": int(self.plan["seed"]),
            "log_level": 50,
        }

    def _declared_route_nodes(self, participant: Mapping[str, Any]) -> list[str]:
        nodes: list[str] = []
        for stable_lane_id in participant["route"]["lane_ids"]:
            start_node, end_node, _ = self._stable_to_engine[str(stable_lane_id)]
            if not nodes:
                nodes.extend([start_node, end_node])
            elif nodes[-1] == start_node:
                nodes.append(end_node)
            elif len(nodes) >= 2 and nodes[-2:] == [start_node, end_node]:
                continue
        return nodes

    def _declared_route_control(
        self,
        participant: Mapping[str, Any],
        vehicle: Any,
        route_lanes: list[Any],
        route_index: int,
    ) -> tuple[list[float], int]:
        """Follow declared lane geometry with deterministic lookahead control."""
        actual_engine_lane = tuple(vehicle.lane.index)
        actual_engine_lane = (
            str(actual_engine_lane[0]),
            str(actual_engine_lane[1]),
            int(actual_engine_lane[2]),
        )
        stable_lane_id = self._engine_to_stable.get(actual_engine_lane)
        route_lane_ids = [str(item) for item in participant["route"]["lane_ids"]]
        if stable_lane_id in route_lane_ids:
            route_index = max(route_index, route_lane_ids.index(stable_lane_id))

        lookahead_m = 6.0
        target_index = route_index
        current_lane = route_lanes[target_index]
        longitudinal_m = max(
            0.0,
            float(current_lane.local_coordinates(vehicle.position)[0]),
        )
        remaining_m = lookahead_m
        target_longitudinal_m = longitudinal_m
        while (
            target_index < len(route_lanes) - 1
            and target_longitudinal_m + remaining_m
            > float(route_lanes[target_index].length)
        ):
            remaining_m -= max(
                0.0,
                float(route_lanes[target_index].length)
                - target_longitudinal_m,
            )
            target_index += 1
            target_longitudinal_m = 0.0
        target_lane = route_lanes[target_index]
        target_longitudinal_m = min(
            float(target_lane.length),
            target_longitudinal_m + remaining_m,
        )
        target_position = target_lane.position(target_longitudinal_m, 0.0)
        desired_heading = math.atan2(
            float(target_position[1] - vehicle.position[1]),
            float(target_position[0] - vehicle.position[0]),
        )
        heading_error = (
            desired_heading - float(vehicle.heading_theta) + math.pi
        ) % (2.0 * math.pi) - math.pi
        steering = 1.5 * heading_error

        target_speed_mps = float(participant["spawn"]["speed_mps"])
        actual_speed_mps = float(vehicle.speed_km_h) / 3.6
        throttle_brake = 0.5 * (target_speed_mps - actual_speed_mps)
        return [steering, throttle_brake], route_index

    def _capture_state(
        self,
        tick: int,
        fallback_by_participant: Mapping[str, Mapping[str, Any]] | None = None,
        terminal_info_by_agent: Mapping[str, Mapping[str, Any]] | None = None,
        inactive_participant_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        assert self._environment is not None
        is_v2 = self.plan["schema_version"] == "scenarioforge.execution-plan/v2"
        records: list[dict[str, Any]] = []
        for participant in self.plan["participants"]:
            participant_id = str(participant["id"])
            agent_id = self._participant_to_agent[participant_id]
            vehicle = self._environment.agent_manager.get_agent(
                agent_id, raise_error=False
            )
            if vehicle is None:
                if (
                    inactive_participant_ids is not None
                    and participant_id in inactive_participant_ids
                ):
                    continue
                fallback = (
                    fallback_by_participant.get(participant_id)
                    if fallback_by_participant is not None
                    else None
                )
                terminal_info = (
                    terminal_info_by_agent.get(agent_id)
                    if terminal_info_by_agent is not None
                    else None
                )
                if fallback is None or terminal_info is None:
                    raise RuntimeError(
                        "MetaDrive participant disappeared without an observed "
                        f"state: {participant_id}"
                    )
                record = dict(fallback)
                record["tick"] = tick
                record["collision"] = bool(
                    record["collision"]
                    or terminal_info.get("crash_vehicle", False)
                    or terminal_info.get("crash_object", False)
                )
                if is_v2 and terminal_info.get("arrive_dest", False):
                    record["route_completed"] = True
                records.append(record)
                continue
            position = [float(vehicle.position[0]), float(vehicle.position[1])]
            heading_deg = math.degrees(float(vehicle.heading_theta))
            record: dict[str, Any] = {
                "schema_version": (
                    "scenarioforge.trajectory-point/v2"
                    if is_v2
                    else "scenarioforge.trajectory-point/v1"
                ),
                "tick": tick,
                "participant_id": participant_id,
                "position_m": position,
                "speed_mps": float(vehicle.speed_km_h) / 3.6,
                "heading_deg": heading_deg,
                "collision": bool(vehicle.crash_vehicle or vehicle.crash_object),
            }
            if is_v2:
                actual_engine_lane = tuple(vehicle.lane.index)
                actual_engine_lane = (
                    str(actual_engine_lane[0]),
                    str(actual_engine_lane[1]),
                    int(actual_engine_lane[2]),
                )
                stable_lane_id = self._engine_to_stable.get(actual_engine_lane)
                goal = participant["route"]["goal"]
                goal_lane_id = str(goal["lane_id"])
                goal_engine_lane = self._stable_to_engine[goal_lane_id]
                navigation = vehicle.navigation
                actual_destination = (
                    tuple(navigation.final_lane.index)
                    if navigation is not None
                    else None
                )
                actual_destination_index = (
                    [
                        str(actual_destination[0]),
                        str(actual_destination[1]),
                        int(actual_destination[2]),
                    ]
                    if actual_destination is not None
                    else None
                )
                longitudinal_m = float(
                    vehicle.lane.local_coordinates(vehicle.position)[0]
                )
                route_destination_matches = actual_destination_index == list(
                    goal_engine_lane
                )
                route_completed = (
                    stable_lane_id == goal_lane_id
                    and longitudinal_m >= float(goal["longitudinal_m"])
                )
                record.update(
                    {
                        "lane_id": stable_lane_id,
                        "engine_lane_index": list(actual_engine_lane),
                        "lane_longitudinal_m": longitudinal_m,
                        "route_id": str(participant["route"]["id"]),
                        "route_destination_lane_id": goal_lane_id,
                        "route_destination_engine_lane_index": actual_destination_index,
                        "route_destination_matches": route_destination_matches,
                        "route_checkpoints": (
                            list(navigation.checkpoints)
                            if navigation is not None
                            else []
                        ),
                        "route_completed": route_completed,
                        "boundary_violation": not bool(vehicle.on_lane),
                        "wrong_route": bool(vehicle.out_of_route),
                    }
                )
            records.append(record)
        return records

    def _validate_initial_projection(self, initial: list[dict[str, Any]]) -> None:
        by_participant = {point["participant_id"]: point for point in initial}
        for participant in self.plan["participants"]:
            participant_id = str(participant["id"])
            point = by_participant[participant_id]
            spawn = participant["spawn"]
            expected_lane = str(spawn["lane_id"])
            if point["lane_id"] != expected_lane:
                raise RuntimeError(
                    f"MetaDrive spawn lane mismatch for {participant_id}: "
                    f"{point['lane_id']} != {expected_lane}"
                )
            heading_error = _angular_distance_deg(
                float(point["heading_deg"]), float(spawn["heading_deg"])
            )
            if heading_error > 1.0:
                raise RuntimeError(
                    f"MetaDrive spawn heading mismatch for {participant_id}: "
                    f"error={heading_error:.6f} degrees"
                )
            if not point["route_destination_matches"]:
                raise RuntimeError(
                    f"MetaDrive route destination mismatch for {participant_id}"
                )
            declared_nodes = self._declared_route_nodes(participant)
            if point["route_checkpoints"] != declared_nodes:
                raise RuntimeError(
                    f"MetaDrive route mismatch for {participant_id}: "
                    f"{point['route_checkpoints']} != {declared_nodes}"
                )

    @staticmethod
    def _sample_longitudinal_range(
        start_m: float,
        end_m: float,
        *,
        spacing_m: float,
    ) -> list[float]:
        segment_count = max(1, min(511, math.ceil((end_m - start_m) / spacing_m)))
        return [
            start_m + (end_m - start_m) * index / segment_count
            for index in range(segment_count + 1)
        ]

    @staticmethod
    def _lane_boundaries(lane: Any, positions: list[float]) -> dict[str, list[list[float]]]:
        centerline: list[list[float]] = []
        left: list[list[float]] = []
        right: list[list[float]] = []
        for longitudinal_m in positions:
            half_width = float(lane.width_at(longitudinal_m)) / 2.0
            center = lane.position(longitudinal_m, 0.0)
            left_point = lane.position(longitudinal_m, half_width)
            right_point = lane.position(longitudinal_m, -half_width)
            centerline.append([float(center[0]), float(center[1])])
            left.append([float(left_point[0]), float(left_point[1])])
            right.append([float(right_point[0]), float(right_point[1])])
        return {
            "centerline_m": centerline,
            "left_boundary_m": left,
            "right_boundary_m": right,
        }

    def _capture_road_geometry(self, road_network: Any) -> dict[str, Any]:
        """Project the real MetaDrive lanes used by this run into bounded evidence."""
        topology = self.plan["simulation"]["topology"]
        lanes: list[dict[str, Any]] = []
        engine_lanes: dict[str, Any] = {}
        for declared in topology["lanes"]:
            lane_id = str(declared["id"])
            lane = road_network.get_lane(self._stable_to_engine[lane_id])
            engine_lanes[lane_id] = lane
            actual_length_m = float(lane.length)
            positions = self._sample_longitudinal_range(
                0.0,
                actual_length_m,
                spacing_m=4.0,
            )
            lanes.append(
                {
                    "lane_id": lane_id,
                    "kind": str(declared["kind"]),
                    **self._lane_boundaries(lane, positions),
                }
            )

        conflict_zones: list[dict[str, Any]] = []
        for zone in topology["conflict_zones"]:
            regions: list[dict[str, Any]] = []
            for lane_id_value in zone["lane_ids"]:
                lane_id = str(lane_id_value)
                lane = engine_lanes[lane_id]
                start_m = min(float(zone["start_m"]), float(lane.length))
                end_m = min(float(zone["end_m"]), float(lane.length))
                positions = self._sample_longitudinal_range(
                    start_m,
                    end_m,
                    spacing_m=2.0,
                )
                boundaries = self._lane_boundaries(lane, positions)
                regions.append(
                    {
                        "lane_id": lane_id,
                        "left_boundary_m": boundaries["left_boundary_m"],
                        "right_boundary_m": boundaries["right_boundary_m"],
                    }
                )
            conflict_zones.append(
                {
                    "zone_id": str(zone["id"]),
                    "start_m": float(zone["start_m"]),
                    "end_m": float(zone["end_m"]),
                    "lane_regions": regions,
                }
            )
        return {
            "schema_version": "scenarioforge.road-geometry/v1",
            "coordinate_system": "right-handed-x-forward-y-left",
            "source": "metadrive-road-network",
            "lanes": lanes,
            "conflict_zones": conflict_zones,
        }

    @staticmethod
    def _minimum_ttc_v1(trajectory: list[dict[str, Any]]) -> float | None:
        by_tick: dict[int, dict[str, dict[str, Any]]] = {}
        for point in trajectory:
            by_tick.setdefault(point["tick"], {})[point["participant_id"]] = point
        values: list[float] = []
        for states in by_tick.values():
            if "ego" not in states or "lead" not in states:
                continue
            gap = states["lead"]["position_m"][0] - states["ego"]["position_m"][0]
            closing_speed = states["ego"]["speed_mps"] - states["lead"]["speed_mps"]
            if gap > 0.0 and closing_speed > 0.0:
                values.append(gap / closing_speed)
        return min(values) if values else None

    @staticmethod
    def _applicable_participants(
        definition: Mapping[str, Any], trajectory: list[dict[str, Any]]
    ) -> list[str]:
        declared = [
            str(item) for item in definition["applies_to"]["participant_ids"]
        ]
        if declared:
            return declared
        return sorted({str(point["participant_id"]) for point in trajectory})

    @classmethod
    def _minimum_ttc_v2(
        cls,
        trajectory: list[dict[str, Any]],
        definition: Mapping[str, Any],
    ) -> float | None:
        participant_ids = cls._applicable_participants(definition, trajectory)
        by_tick: dict[int, dict[str, dict[str, Any]]] = {}
        for point in trajectory:
            by_tick.setdefault(int(point["tick"]), {})[
                str(point["participant_id"])
            ] = point
        values: list[float] = []
        for states in by_tick.values():
            for left_id, right_id in combinations(participant_ids, 2):
                if left_id not in states or right_id not in states:
                    continue
                left = states[left_id]
                right = states[right_id]
                relative_position = (
                    float(right["position_m"][0]) - float(left["position_m"][0]),
                    float(right["position_m"][1]) - float(left["position_m"][1]),
                )
                left_heading = math.radians(float(left["heading_deg"]))
                right_heading = math.radians(float(right["heading_deg"]))
                left_velocity = (
                    float(left["speed_mps"]) * math.cos(left_heading),
                    float(left["speed_mps"]) * math.sin(left_heading),
                )
                right_velocity = (
                    float(right["speed_mps"]) * math.cos(right_heading),
                    float(right["speed_mps"]) * math.sin(right_heading),
                )
                relative_velocity = (
                    right_velocity[0] - left_velocity[0],
                    right_velocity[1] - left_velocity[1],
                )
                closing_dot = (
                    relative_position[0] * relative_velocity[0]
                    + relative_position[1] * relative_velocity[1]
                )
                distance_squared = (
                    relative_position[0] ** 2 + relative_position[1] ** 2
                )
                if closing_dot < -1e-12 and distance_squared > 1e-12:
                    # Distance divided by the radial closing speed. This stays
                    # topology-agnostic while using both actors' real headings.
                    values.append(distance_squared / -closing_dot)
        return min(values) if values else None

    @classmethod
    def _minimum_acceleration(
        cls,
        trajectory: list[dict[str, Any]],
        definition: Mapping[str, Any],
        sample_interval_s: float,
    ) -> float | None:
        participant_ids = set(cls._applicable_participants(definition, trajectory))
        by_participant: dict[str, list[dict[str, Any]]] = {}
        for point in trajectory:
            participant_id = str(point["participant_id"])
            if participant_id in participant_ids:
                by_participant.setdefault(participant_id, []).append(point)
        accelerations: list[float] = []
        for points in by_participant.values():
            points.sort(key=lambda item: int(item["tick"]))
            for previous, current in zip(points, points[1:]):
                tick_delta = int(current["tick"]) - int(previous["tick"])
                if tick_delta <= 0:
                    continue
                accelerations.append(
                    (float(current["speed_mps"]) - float(previous["speed_mps"]))
                    / (sample_interval_s * tick_delta)
                )
        return min(accelerations) if accelerations else None

    @classmethod
    def _completion_time(
        cls,
        trajectory: list[dict[str, Any]],
        definition: Mapping[str, Any],
        sample_interval_s: float,
    ) -> float | None:
        participant_ids = cls._applicable_participants(definition, trajectory)
        first_completion: dict[str, int] = {}
        for point in trajectory:
            participant_id = str(point["participant_id"])
            if (
                participant_id in participant_ids
                and point.get("route_completed")
                and participant_id not in first_completion
            ):
                first_completion[participant_id] = int(point["tick"])
        if set(first_completion) != set(participant_ids):
            return None
        return max(first_completion.values()) * sample_interval_s

    @staticmethod
    def _threshold_met(value: Any, threshold: Mapping[str, Any] | None) -> bool | None:
        if threshold is None or value is None:
            return None
        expected = float(threshold["value"])
        actual = float(value)
        return {
            "lt": actual < expected,
            "lte": actual <= expected,
            "gt": actual > expected,
            "gte": actual >= expected,
            "eq": actual == expected,
        }[str(threshold["operator"])]

    @staticmethod
    def _predicate_satisfied(
        predicate: Mapping[str, Any],
        trajectory: list[dict[str, Any]],
        *,
        at_horizon: bool,
        execution_complete: bool,
    ) -> bool:
        kind = str(predicate["kind"])
        participant_ids = {
            str(item) for item in predicate["participant_ids"]
        } or {str(point["participant_id"]) for point in trajectory}
        lane_ids = {str(item) for item in predicate["lane_ids"]}
        applicable = [
            point
            for point in trajectory
            if str(point["participant_id"]) in participant_ids
        ]
        if kind == "collision":
            return any(bool(point["collision"]) for point in applicable)
        if kind == "boundary_violation":
            return any(bool(point.get("boundary_violation")) for point in applicable)
        if kind in {"wrong_lane", "closed_region_entry"}:
            return bool(lane_ids) and any(
                point.get("lane_id") in lane_ids for point in applicable
            )
        if kind == "timeout":
            return at_horizon
        if kind == "execution_incomplete":
            return not execution_complete
        if kind == "route_completed":
            return all(
                any(
                    str(point["participant_id"]) == participant_id
                    and bool(point.get("route_completed"))
                    and (not lane_ids or point.get("lane_id") in lane_ids)
                    for point in applicable
                )
                for participant_id in participant_ids
            )
        if kind in {"merge_completed", "yield_completed"}:
            return all(
                any(
                    str(point["participant_id"]) == participant_id
                    and bool(point.get("route_completed"))
                    and (not lane_ids or point.get("lane_id") in lane_ids)
                    for point in applicable
                )
                for participant_id in participant_ids
            ) and not any(bool(point["collision"]) for point in applicable)
        raise RuntimeError(f"unsupported v2 predicate kind: {kind}")

    def _predicate_results(
        self,
        trajectory: list[dict[str, Any]],
        *,
        at_horizon: bool,
        execution_complete: bool,
    ) -> dict[str, list[dict[str, Any]]]:
        results: dict[str, list[dict[str, Any]]] = {"success": [], "failure": []}
        for axis, key in (
            ("success", "success_predicates"),
            ("failure", "failure_predicates"),
        ):
            for predicate in self.plan["constraints"][key]:
                results[axis].append(
                    {
                        "predicate_id": str(predicate["id"]),
                        "kind": str(predicate["kind"]),
                        "satisfied": self._predicate_satisfied(
                            predicate,
                            trajectory,
                            at_horizon=at_horizon,
                            execution_complete=execution_complete,
                        ),
                    }
                )
        return results

    def _metric_values(
        self,
        trajectory: list[dict[str, Any]],
        *,
        collision: bool,
        termination_reason: str,
        sample_interval_s: float,
    ) -> list[dict[str, Any]]:
        topology_kind = str(self.plan["simulation"]["topology"]["topology_kind"])
        values: list[dict[str, Any]] = []
        for definition in self.plan["constraints"]["metric_definitions"]:
            metric = str(definition["metric"])
            applicable = topology_kind in {
                str(item) for item in definition["applies_to"]["topology_kinds"]
            }
            if not applicable:
                value: Any = None
            elif metric == "collision":
                participant_ids = set(
                    self._applicable_participants(definition, trajectory)
                )
                value = collision and any(
                    point["participant_id"] in participant_ids
                    and bool(point["collision"])
                    for point in trajectory
                )
            elif metric == "hard_braking":
                value = self._minimum_acceleration(
                    trajectory, definition, sample_interval_s
                )
            elif metric == "minimum_ttc":
                value = self._minimum_ttc_v2(trajectory, definition)
            elif metric == "completion_time":
                value = self._completion_time(
                    trajectory, definition, sample_interval_s
                )
            elif metric == "termination_reason":
                value = termination_reason
            else:
                raise RuntimeError(f"unsupported v2 metric: {metric}")
            values.append(
                {
                    "definition_id": str(definition["definition_id"]),
                    "metric": metric,
                    "unit": str(definition["unit"]),
                    "applies_to": definition["applies_to"],
                    "value": value,
                    "raw_evidence_value": value,
                    "threshold": definition["threshold"],
                    "threshold_met": self._threshold_met(
                        value, definition["threshold"]
                    ),
                    "null_semantics": str(definition["null_semantics"]),
                    "evidence_field": str(definition["evidence_field"]),
                }
            )
        return values

    def run(self) -> dict[str, Any]:
        # Import the simulator only at the Worker execution boundary. Contract
        # compilation and pure adapter config projection do not load Panda3D.
        from metadrive import MultiAgentMetaDrive

        is_v2 = self.plan["schema_version"] == "scenarioforge.execution-plan/v2"
        environment = MultiAgentMetaDrive(self._config())
        self._environment = environment
        trajectory: list[dict[str, Any]] = []
        action_records: list[dict[str, Any]] = []
        event_records: list[dict[str, Any]] = []
        collision_participants: set[str] = set()
        completed_steps = 0
        termination_reason: str | None = None
        max_steps = int(self.plan["simulation"]["max_steps"])
        route_lanes_by_participant: dict[str, list[Any]] = {}
        route_index_by_participant: dict[str, int] = {}
        road_geometry: dict[str, Any] | None = None
        try:
            observations, _ = environment.reset(seed=int(self.plan["seed"]))
            expected_agents = set(self._participant_to_agent.values())
            if set(observations) != expected_agents or set(environment.agents) != expected_agents:
                raise RuntimeError("MetaDrive did not spawn the bound participant set")
            initial = self._capture_state(tick=0)
            trajectory.extend(initial)
            last_by_participant = {
                str(point["participant_id"]): point for point in initial
            }
            inactive_participant_ids: set[str] = set()
            if is_v2:
                self._validate_initial_projection(initial)
                road_network = next(
                    iter(environment.agents.values())
                ).navigation.map.road_network
                road_geometry = self._capture_road_geometry(road_network)
                for participant in self.plan["participants"]:
                    participant_id = str(participant["id"])
                    route_lanes_by_participant[participant_id] = [
                        road_network.get_lane(
                            self._stable_to_engine[str(stable_lane_id)]
                        )
                        for stable_lane_id in participant["route"]["lane_ids"]
                    ]
                    route_index_by_participant[participant_id] = 0

            for tick in range(max_steps):
                active_agent_ids = set(environment.agents)
                active_participant_ids = {
                    participant_id
                    for participant_id, agent_id in self._participant_to_agent.items()
                    if agent_id in active_agent_ids
                }
                if not active_participant_ids:
                    termination_reason = "all_agents_inactive"
                    break
                participant_actions, records, fired = resolve_tick_actions(self.plan, tick)
                if is_v2:
                    control_by_participant: dict[str, list[float]] = {}
                    for participant in self.plan["participants"]:
                        participant_id = str(participant["id"])
                        if participant_id not in active_participant_ids:
                            continue
                        agent_id = self._participant_to_agent[participant_id]
                        vehicle = environment.agents[agent_id]
                        control, route_index = self._declared_route_control(
                            participant,
                            vehicle,
                            route_lanes_by_participant[participant_id],
                            route_index_by_participant[participant_id],
                        )
                        control_by_participant[participant_id] = control
                        route_index_by_participant[participant_id] = route_index
                    participant_actions, records = apply_declared_route_control(
                        participant_actions,
                        records,
                        control_by_participant,
                    )
                engine_actions = {
                    self._participant_to_agent[participant_id]: action
                    for participant_id, action in participant_actions.items()
                    if participant_id in active_participant_ids
                }
                _, _, terminated, truncated, infos = environment.step(engine_actions)
                completed_steps = tick + 1
                action_records.extend(
                    record
                    for record in records
                    if record["participant_id"] in active_participant_ids
                )
                event_records.extend(
                    event
                    for event in fired
                    if event["participant_id"] in active_participant_ids
                )
                terminal_infos = {
                    agent_id: infos[agent_id]
                    for agent_id in self._participant_to_agent.values()
                    if terminated.get(agent_id, False)
                    or truncated.get(agent_id, False)
                }
                state = self._capture_state(
                    tick=tick + 1,
                    fallback_by_participant=last_by_participant,
                    terminal_info_by_agent=terminal_infos,
                    inactive_participant_ids=inactive_participant_ids,
                )
                trajectory.extend(state)
                last_by_participant.update(
                    {str(point["participant_id"]): point for point in state}
                )
                inactive_participant_ids.update(
                    participant_id
                    for participant_id, agent_id in self._participant_to_agent.items()
                    if terminated.get(agent_id, False)
                    or truncated.get(agent_id, False)
                )
                collision_participants.update(
                    point["participant_id"] for point in state if point["collision"]
                )
                if collision_participants:
                    termination_reason = "collision"
                    break
                if is_v2:
                    predicate_results = self._predicate_results(
                        trajectory,
                        at_horizon=False,
                        execution_complete=True,
                    )
                    expected_events = set(self.plan["constraints"]["expected_events"])
                    fired_events = {item["event_id"] for item in event_records}
                    failures = [
                        item
                        for item in predicate_results["failure"]
                        if item["satisfied"]
                    ]
                    if failures:
                        termination_reason = (
                            f"failure_predicate:{failures[0]['predicate_id']}"
                        )
                        break
                    if all(
                        item["satisfied"] for item in predicate_results["success"]
                    ) and expected_events == fired_events:
                        termination_reason = "success_predicates_satisfied"
                        break
        finally:
            environment.close()
            self._environment = None

        collision = bool(collision_participants)
        if termination_reason is None:
            termination_reason = "horizon_completed"
        sample_interval_s = (
            float(self.plan["simulation"]["physics_world_step_size_s"])
            * int(self.plan["simulation"]["decision_repeat"])
        )
        if not is_v2:
            metrics: dict[str, Any] = {
                "schema_version": "scenarioforge.metrics/v1",
                "collision": collision,
                "collision_participants": sorted(collision_participants),
                "termination_reason": termination_reason,
                "terminal_status": "failed" if collision else "success",
                "min_ttc_s": self._minimum_ttc_v1(trajectory),
                "completed_steps": completed_steps,
                "sample_interval_s": sample_interval_s,
            }
        else:
            at_horizon = completed_steps >= max_steps
            predicate_results = self._predicate_results(
                trajectory,
                at_horizon=at_horizon,
                execution_complete=True,
            )
            metric_values = self._metric_values(
                trajectory,
                collision=collision,
                termination_reason=termination_reason,
                sample_interval_s=sample_interval_s,
            )
            metric_by_name = {item["metric"]: item for item in metric_values}
            success_satisfied = all(
                item["satisfied"] for item in predicate_results["success"]
            )
            failure_satisfied = any(
                item["satisfied"] for item in predicate_results["failure"]
            )
            observed_near_miss = any(
                item["metric"] in {"hard_braking", "minimum_ttc"}
                and item["threshold_met"] is True
                for item in metric_values
            )
            if collision:
                scenario_outcome = "collision_failure"
            elif failure_satisfied or observed_near_miss or not success_satisfied:
                scenario_outcome = "near_miss"
            else:
                scenario_outcome = "safe_pass"
            metrics = {
                "schema_version": "scenarioforge.metrics/v2",
                "execution_status": "completed",
                "scenario_outcome": scenario_outcome,
                "target_scenario_outcome": str(
                    self.plan["constraints"]["target_outcome"]
                ),
                "target_outcome_match": scenario_outcome
                == str(self.plan["constraints"]["target_outcome"]),
                "termination_reason": termination_reason,
                "collision": collision,
                "collision_participants": sorted(collision_participants),
                "min_ttc_s": metric_by_name["minimum_ttc"]["value"],
                "minimum_acceleration_mps2": metric_by_name["hard_braking"][
                    "value"
                ],
                "completion_time_s": metric_by_name["completion_time"]["value"],
                "completed_steps": completed_steps,
                "sample_interval_s": sample_interval_s,
                "predicate_results": predicate_results,
                "metric_definitions": self.plan["constraints"][
                    "metric_definitions"
                ],
                "metric_values": metric_values,
            }
        result = {
            "actions.json": action_records,
            "events.json": event_records,
            "metrics.json": metrics,
            "trajectory.json": trajectory,
        }
        if is_v2:
            assert road_geometry is not None
            result["_road_geometry"] = road_geometry
        return result
