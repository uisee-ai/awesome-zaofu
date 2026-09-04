"""HighwayEnv 1.12.1 adapter for the frozen construction-v0 domain."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from highway_env.envs.highway_env import HighwayEnv
from highway_env.road.lane import LineType, StraightLane
from highway_env.road.road import Road, RoadNetwork
from highway_env.vehicle.behavior import IDMVehicle
from highway_env.vehicle.objects import Landmark, Obstacle

from highwaypilot_lab.rng import RNGStreams


ACTIONS = {
    0: "LANE_LEFT",
    1: "IDLE",
    2: "LANE_RIGHT",
    3: "FASTER",
    4: "SLOWER",
}
ACTION_INDEXES = {label: index for index, label in ACTIONS.items()}
MERGE_ACTION_BY_SIDE = {"left": "LANE_RIGHT", "right": "LANE_LEFT"}


def _rounded(value: float) -> float:
    return round(float(value), 12)


class ConstructionEnv(HighwayEnv):
    """A narrow adapter; all domain outputs are computed on the Python side."""

    def __init__(
        self,
        effective_config: Mapping[str, Any],
        streams: RNGStreams,
        env_seed: int,
    ) -> None:
        self.effective_config = dict(effective_config)
        self.streams = streams
        self.env_seed = env_seed
        self._traffic_rng = streams.generator("traffic")
        self._scenario_rng = streams.generator("scenario_events")
        self._bootstrap_reset = True
        self._last_action: str | None = None
        self._last_reward = 0.0
        self._last_reward_components: dict[str, float] = {}
        self._last_terminated = False
        self._last_truncated = False
        super().__init__(config=self._highway_config())

    def _highway_config(self) -> dict[str, Any]:
        config = self.effective_config
        return {
            "observation": {
                "type": "Kinematics",
                **config["observation"],
            },
            # HighwayEnv's default meta-action speeds bottom out at 20 m/s.
            # That makes repeated SLOWER commands ineffective in dense traffic
            # and prevents a qualified policy from stopping before a blockage.
            "action": {
                "type": "DiscreteMetaAction",
                "target_speeds": [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0],
            },
            "lanes_count": config["road"]["lanes_count"],
            "vehicles_count": config["traffic"]["vehicles_count"],
            "controlled_vehicles": 1,
            "duration": config["simulation"]["duration_s"],
            "simulation_frequency": config["simulation"]["simulation_frequency_hz"],
            "policy_frequency": config["simulation"]["policy_frequency_hz"],
            "show_trajectories": False,
            "normalize_reward": False,
            "offroad_terminal": True,
        }

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        # AbstractEnv.__init__ invokes reset without a seed. Redirect that sole
        # bootstrap call to the exact env_core scalar required by the contract.
        if not self._bootstrap_reset:
            raise RuntimeError("recreate ConstructionSimulation to reset deterministic streams")
        self._bootstrap_reset = False
        observation, info = super().reset(seed=self.env_seed, options=options)
        if dict(self.action_type.actions) != ACTIONS:
            raise RuntimeError("HighwayEnv discrete action mapping is incompatible")
        self._last_reward_components = self._reward_components(ACTION_INDEXES["IDLE"])
        self._last_reward = self._weighted_reward(self._last_reward_components)
        self._last_terminated = self._is_terminated()
        self._last_truncated = self._is_truncated()
        return observation, info

    def _reset(self) -> None:
        self._create_road()
        self._create_construction_objects()
        self._create_vehicles()

    def _create_road(self) -> None:
        road = self.effective_config["road"]
        network = RoadNetwork()
        lane_count = road["lanes_count"]
        for lane_index in range(lane_count):
            y = lane_index * road["lane_width_m"]
            line_types = [
                LineType.CONTINUOUS_LINE if lane_index == 0 else LineType.STRIPED,
                LineType.CONTINUOUS_LINE if lane_index == lane_count - 1 else LineType.NONE,
            ]
            network.add_lane(
                "0",
                "1",
                StraightLane(
                    [0.0, y],
                    [road["length_m"], y],
                    width=road["lane_width_m"],
                    line_types=line_types,
                    speed_limit=road["speed_limit_mps"],
                ),
            )
        self.road = Road(
            network=network,
            np_random=self._traffic_rng,
            record_history=False,
            neighbour_vehicles_connected_lanes=False,
        )

    def _lane(self, lane_index: int) -> StraightLane:
        return self.road.network.get_lane(("0", "1", lane_index))

    def _create_construction_objects(self) -> None:
        construction = self.effective_config["construction"]
        lane_index = construction["closed_lane_index"]
        lane = self._lane(lane_index)
        for index, offset in enumerate(construction["warning_offsets_m"]):
            x = construction["zone_start_m"] - offset
            marker = Landmark(self.road, lane.position(x, 0.0))
            marker.object_id = f"warning-{index:02d}"
            marker.object_kind = "warning"
            self.road.objects.append(marker)

        barrier_positions = np.arange(
            construction["zone_start_m"],
            construction["zone_end_m"] + construction["cone_spacing_m"] * 0.5,
            construction["cone_spacing_m"],
        )
        for index, x_value in enumerate(barrier_positions):
            x = min(float(x_value), construction["zone_end_m"])
            barrier = Obstacle(self.road, lane.position(x, 0.0))
            barrier.object_id = f"barrier-{index:03d}"
            barrier.object_kind = "barrier"
            self.road.objects.append(barrier)

    def _traffic_slots(self, count: int) -> list[tuple[float, int]]:
        """Place traffic deterministically with density-controlled headways.

        ``vehicles_count`` controls how many vehicles exist; ``density`` controls
        how tightly their longitudinal rows cluster around the work zone.  Rows
        always retain a collision-safe minimum headway.  Traffic approaching the
        closure is placed only on open lanes so the scenario does not manufacture
        a stationary pile-up in front of the ego before it can merge.
        """
        if count == 0:
            return []
        construction = self.effective_config["construction"]
        road = self.effective_config["road"]
        traffic = self.effective_config["traffic"]
        closed_lane = construction["closed_lane_index"]
        open_lanes = [index for index in range(road["lanes_count"]) if index != closed_lane]
        all_lanes = list(range(road["lanes_count"]))
        before_min = max(70.0, self.effective_config["ego"]["initial_position_m"] + 30.0)

        # density=1 gives a comfortable 42 m row headway; higher density packs
        # rows closer, while the 18 m floor prevents overlapping initial bodies.
        spacing = float(np.clip(42.0 / np.sqrt(traffic["density"]), 18.0, 80.0))

        def rows(start: float, stop: float, step: float, lanes: list[int]) -> list[tuple[float, int]]:
            positions = np.arange(start, stop, step, dtype=float)
            slots: list[tuple[float, int]] = []
            for position in positions:
                lane_order = list(lanes)
                self._traffic_rng.shuffle(lane_order)
                slots.extend((float(position), lane_index) for lane_index in lane_order)
            return slots

        while True:
            before_slots = rows(
                construction["zone_start_m"] - 35.0,
                before_min - 0.001,
                -spacing,
                open_lanes,
            )
            after_slots = rows(
                construction["zone_end_m"] + 35.0,
                road["length_m"] - 49.999,
                spacing,
                all_lanes,
            )
            if len(before_slots) + len(after_slots) >= count or spacing <= 18.0:
                break
            spacing = max(18.0, spacing * 0.9)

        before_count = min((count + 1) // 2, len(before_slots))
        after_count = min(count - before_count, len(after_slots))
        before_count = min(count - after_count, len(before_slots))
        selected = before_slots[:before_count] + after_slots[:after_count]
        if len(selected) != count:
            raise RuntimeError("traffic placement capacity is insufficient")

        # Small deterministic jitter avoids artificial rows while remaining far
        # below the collision-safe headway.
        jittered = [
            (position + float(self._traffic_rng.uniform(-2.0, 2.0)), lane_index)
            for position, lane_index in selected
        ]
        self._traffic_rng.shuffle(jittered)
        return jittered

    def _create_vehicles(self) -> None:
        config = self.effective_config
        construction = config["construction"]
        ego_config = config["ego"]
        closed_lane = construction["closed_lane_index"]
        ego_lane = self._lane(closed_lane)
        ego = self.action_type.vehicle_class(
            self.road,
            ego_lane.position(ego_config["initial_position_m"], 0.0),
            ego_lane.heading_at(ego_config["initial_position_m"]),
            ego_config["initial_speed_mps"],
        )
        ego.vehicle_id = "ego"
        ego.scenario_event = False
        self.controlled_vehicles = [ego]
        self.road.vehicles.append(ego)

        traffic = config["traffic"]
        slots = self._traffic_slots(traffic["vehicles_count"])
        for index, (x, lane_index) in enumerate(slots):
            lane = self._lane(lane_index)
            speed = float(
                self._traffic_rng.uniform(traffic["min_speed_mps"], traffic["max_speed_mps"])
            )
            vehicle = IDMVehicle(
                self.road,
                lane.position(float(x), 0.0),
                lane.heading_at(float(x)),
                speed,
                enable_lane_change=True,
            )
            vehicle.vehicle_id = f"traffic-{index:03d}"
            vehicle.scenario_event = False
            if self._traffic_rng.random() < traffic["aggressive_fraction"]:
                vehicle.DISTANCE_WANTED = 3.0
                vehicle.TIME_WANTED = 0.8
                vehicle.ACC_MAX = 6.0
            self.road.vehicles.append(vehicle)

        if config["scenario_events"]["dangerous_cut_in"]:
            self._create_dangerous_cut_in_vehicle()

    def _create_dangerous_cut_in_vehicle(self) -> None:
        config = self.effective_config
        construction = config["construction"]
        event = config["scenario_events"]
        source_lane_index = construction["closed_lane_index"]
        target_lane_index = construction["target_lane_index"]
        source_lane = self._lane(source_lane_index)
        jitter = float(self._scenario_rng.uniform(-2.0, 2.0))
        x = config["ego"]["initial_position_m"] + event["cut_in_trigger_distance_m"] + jitter
        vehicle = IDMVehicle(
            self.road,
            source_lane.position(x, 0.0),
            source_lane.heading_at(x),
            event["cut_in_vehicle_speed_mps"],
            target_lane_index=("0", "1", target_lane_index),
            enable_lane_change=True,
        )
        vehicle.vehicle_id = "event-dangerous-cut-in"
        vehicle.scenario_event = True
        self.road.vehicles.append(vehicle)

    def _minimum_ttc(self) -> float | None:
        ego = self.vehicle
        ego_lane = ego.lane_index[2]
        candidates = list(self.road.vehicles) + [obj for obj in self.road.objects if obj.solid]
        ttc_values: list[float] = []
        for candidate in candidates:
            if candidate is ego or candidate.lane_index[2] != ego_lane:
                continue
            longitudinal = float(candidate.position[0] - ego.position[0])
            if longitudinal <= 0:
                continue
            closing_speed = float(ego.speed - candidate.speed)
            if closing_speed <= 0:
                continue
            clearance = max(
                0.0,
                longitudinal - (float(ego.LENGTH) + float(candidate.LENGTH)) / 2.0,
            )
            ttc_values.append(clearance / closing_speed)
        return min(ttc_values) if ttc_values else None

    def _merge_success(self) -> bool:
        construction = self.effective_config["construction"]
        return bool(
            self.vehicle.lane_index[2] != construction["closed_lane_index"]
            and self.vehicle.position[0] >= construction["zone_end_m"]
            and not self.vehicle.crashed
        )

    def _reward_components(self, action: int | None) -> dict[str, float]:
        min_ttc = self._minimum_ttc()
        action_label = ACTIONS.get(int(action), None) if action is not None else None
        acceleration = abs(float(self.vehicle.action.get("acceleration", 0.0)))
        return {
            "collision": float(self.vehicle.crashed),
            "speed": float(np.clip(self.vehicle.speed / self.effective_config["road"]["speed_limit_mps"], 0.0, 1.0)),
            "safe_lane": float(self.vehicle.lane_index[2] != self.effective_config["construction"]["closed_lane_index"]),
            "lane_change": float(action_label in {"LANE_LEFT", "LANE_RIGHT"}),
            "merge_success": float(self._merge_success()),
            "ttc": 0.0 if min_ttc is None else float(np.clip(1.0 - min_ttc / 5.0, 0.0, 1.0)),
            "comfort": float(np.clip(acceleration / 10.0, 0.0, 1.0)),
        }

    def _weighted_reward(self, components: Mapping[str, float]) -> float:
        weights = self.effective_config["reward"]
        return float(sum(weights[name] * value for name, value in components.items()))

    def _rewards(self, action: int | None) -> dict[str, float]:
        return self._reward_components(action)

    def _reward(self, action: int) -> float:
        return self._weighted_reward(self._reward_components(action))

    def _is_terminated(self) -> bool:
        return bool(
            self.vehicle.crashed
            or not self.vehicle.on_road
            or self._merge_success()
        )

    def _is_truncated(self) -> bool:
        return bool(self.time >= self.effective_config["simulation"]["duration_s"])

    def step(self, action: int):
        observation, reward, terminated, truncated, info = super().step(action)
        self._last_action = ACTIONS[action]
        self._last_reward_components = self._reward_components(action)
        self._last_reward = float(reward)
        self._last_terminated = bool(terminated)
        self._last_truncated = bool(truncated)
        return observation, reward, terminated, truncated, info

    def _vehicle_state(self, vehicle: Any) -> dict[str, Any]:
        return {
            "vehicle_id": vehicle.vehicle_id,
            "position_m": {
                "x": _rounded(vehicle.position[0]),
                "y": _rounded(vehicle.position[1]),
            },
            "speed_mps": _rounded(vehicle.speed),
            "heading_rad": _rounded(vehicle.heading),
            "lane_index": int(vehicle.lane_index[2]),
            "target_lane_index": int(getattr(vehicle, "target_lane_index", vehicle.lane_index)[2]),
            "crashed": bool(vehicle.crashed),
            "scenario_event": bool(vehicle.scenario_event),
        }

    def _object_state(self, obj: Any) -> dict[str, Any]:
        return {
            "object_id": obj.object_id,
            "kind": obj.object_kind,
            "position_m": {"x": _rounded(obj.position[0]), "y": _rounded(obj.position[1])},
            "lane_index": int(obj.lane_index[2]),
            "solid": bool(obj.solid),
        }

    def termination_reason(self) -> str | None:
        if self.vehicle.crashed:
            return "collision"
        if not self.vehicle.on_road:
            return "offroad"
        if self._merge_success():
            return "merge_success"
        if self._last_truncated:
            return "timeout"
        return None

    def authoritative_snapshot(self) -> dict[str, Any]:
        config = self.effective_config
        construction = config["construction"]
        available_indexes = sorted(self.action_type.get_available_actions())
        return {
            "schema_version": "simulation-snapshot/v1",
            "authority": "python",
            "scenario_id": config["scenario_id"],
            "step": int(round(self.time * config["simulation"]["policy_frequency_hz"])),
            "time_s": _rounded(self.time),
            "config_digest": self.streams.metadata["config_digest"],
            "rng": {
                **self.streams.metadata,
                "env_seed": self.env_seed,
                "env_core_sealed": self.streams.env_core_sealed,
            },
            "road": dict(config["road"]),
            "construction": {
                "side": construction["side"],
                "closed_lane_index": construction["closed_lane_index"],
                "target_lane_index": construction["target_lane_index"],
                "zone_start_m": construction["zone_start_m"],
                "zone_end_m": construction["zone_end_m"],
                "authoritative_merge_action": MERGE_ACTION_BY_SIDE[construction["side"]],
            },
            "ego": self._vehicle_state(self.vehicle),
            "vehicles": sorted(
                (self._vehicle_state(vehicle) for vehicle in self.road.vehicles if vehicle is not self.vehicle),
                key=lambda item: item["vehicle_id"],
            ),
            "objects": [self._object_state(obj) for obj in self.road.objects],
            "reward": {
                "total": _rounded(self._last_reward),
                "components": {name: _rounded(value) for name, value in self._last_reward_components.items()},
            },
            "safety": {
                "min_ttc_s": None if self._minimum_ttc() is None else _rounded(self._minimum_ttc()),
                "collision": bool(self.vehicle.crashed),
            },
            "status": {
                "terminated": self._last_terminated,
                "truncated": self._last_truncated,
                "termination_reason": self.termination_reason(),
            },
            "last_action": self._last_action,
            "available_actions": [ACTIONS[index] for index in available_indexes],
        }
