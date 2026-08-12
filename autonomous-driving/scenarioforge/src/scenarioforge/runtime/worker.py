from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import rfc8785

from scenarioforge import __version__ as scenarioforge_version

from .assets import check_metadrive_runtime


@dataclass
class _RuntimePlanState:
    actors: dict[str, dict[str, object]]
    event_triggers: tuple[dict[str, object], ...]
    triggered_event_ids: set[str] = field(default_factory=set)


def _activate_runtime_plan(runtime: Any, runtime_plan: dict[str, Any]) -> _RuntimePlanState:
    """Materialize every authored runtime entity before the first simulation tick."""
    actors = runtime_plan.get("actors", [])
    obstacles = runtime_plan.get("static_obstacles", [])
    events = runtime_plan.get("event_triggers", [])
    if not all(isinstance(value, list) for value in (actors, obstacles, events)):
        raise ValueError("runtime plan collections must be lists")
    actor_by_id: dict[str, dict[str, object]] = {}
    for actor in actors:
        if not isinstance(actor, dict) or not isinstance(actor.get("id"), str):
            raise ValueError("runtime plan actor is missing a stable id")
        actor_id = actor["id"]
        if actor_id in actor_by_id:
            raise ValueError(f"runtime plan actor id is duplicated: {actor_id}")
        runtime.spawn_actor(actor)
        actor_by_id[actor_id] = actor
    for obstacle in obstacles:
        if not isinstance(obstacle, dict) or not isinstance(obstacle.get("id"), str):
            raise ValueError("runtime plan obstacle is missing a stable id")
        runtime.spawn_obstacle(obstacle)
    return _RuntimePlanState(
        actors=actor_by_id,
        event_triggers=tuple(event for event in events if isinstance(event, dict)),
    )


def _event_is_due(runtime: Any, trigger: dict[str, object], simulated_seconds: float) -> bool:
    kind = trigger.get("kind")
    if kind == "at_time":
        return simulated_seconds >= float(trigger["seconds"])
    if kind == "at_distance":
        return runtime.actor_longitudinal("ego") >= float(trigger["distance"])
    if kind == "on_approach":
        target_actor_id = trigger.get("target_actor_id")
        if not isinstance(target_actor_id, str):
            raise ValueError("on_approach triggers require target_actor_id")
        return runtime.actor_distance("ego", target_actor_id) <= float(trigger["distance"])
    raise ValueError(f"unsupported runtime trigger kind: {kind}")


def _advance_runtime_plan(
    runtime: Any, state: _RuntimePlanState, *, simulated_seconds: float
) -> list[dict[str, str]]:
    """Apply due triggers exactly once and return stable execution receipts."""
    receipts: list[dict[str, str]] = []
    for trigger in state.event_triggers:
        trigger_id = trigger.get("id")
        if not isinstance(trigger_id, str) or trigger_id in state.triggered_event_ids:
            continue
        if not _event_is_due(runtime, trigger, simulated_seconds):
            continue
        action = trigger.get("action")
        target_actor_id = trigger.get("target_actor_id")
        if action == "set_speed_limit":
            target_actor_id = target_actor_id or "ego"
            if not isinstance(target_actor_id, str):
                raise ValueError("set_speed_limit trigger target must be an actor id")
            runtime.set_speed_limit(target_actor_id)
            result = "speed_limited"
        elif action == "spawn_traffic":
            if not isinstance(target_actor_id, str):
                raise ValueError("spawn_traffic triggers require target_actor_id")
            runtime.activate_actor(target_actor_id)
            result = "activated"
        elif action == "yield":
            if not isinstance(target_actor_id, str):
                raise ValueError("yield triggers require target_actor_id")
            runtime.stop_actor(target_actor_id)
            result = "stopped"
        else:
            raise ValueError(f"unsupported runtime trigger action: {action}")
        state.triggered_event_ids.add(trigger_id)
        receipts.append(
            {
                "trigger_id": trigger_id,
                "target_actor_id": target_actor_id,
                "action": str(action),
                "status": "triggered",
                "result": result,
            }
        )
    return receipts


class _MetaDriveRuntime:
    """Small adapter that binds the portable runtime plan to MetaDrive objects."""

    def __init__(self, env: Any, runtime_plan: dict[str, Any]) -> None:
        from metadrive.component.static_object.traffic_object import TrafficBarrier, TrafficCone
        from metadrive.component.vehicle.vehicle_type import StaticDefaultVehicle, TrafficDefaultVehicle

        self.env = env
        self._traffic_vehicle = TrafficDefaultVehicle
        self._static_vehicle = StaticDefaultVehicle
        self._obstacle_types = {"barrier": TrafficBarrier, "cone": TrafficCone}
        self._actors: dict[str, Any] = {}
        self._obstacles: dict[str, Any] = {}
        self._speed_limited: set[str] = set()
        self._stopped_actor_ids: set[str] = set()
        self._safety = runtime_plan.get("safety") or {}

    def _lane(self, lane_number: int) -> Any:
        return self.env.engine.current_map.road_network.get_lane((">", ">>", lane_number))

    @staticmethod
    def _vehicle_config(actor: dict[str, object]) -> dict[str, object]:
        initial = actor.get("initial_state") or {}
        if not isinstance(initial, dict):
            raise ValueError(f"actor {actor['id']} initial_state must be an object")
        lane = int(initial.get("lane", 0))
        return {
            "spawn_lane_index": [">", ">>", lane],
            "spawn_longitude": float(initial.get("longitudinal", 5.0)),
            "spawn_velocity": [float(initial.get("speed", 0.0)), 0.0],
            "spawn_velocity_car_frame": True,
        }

    def spawn_actor(self, actor: dict[str, object]) -> None:
        actor_id = str(actor["id"])
        if actor.get("role") == "ego":
            self._actors[actor_id] = self.env.agent
            return
        self._actors[actor_id] = self.env.engine.spawn_object(
            self._traffic_vehicle,
            name=actor_id,
            vehicle_config=self._vehicle_config(actor),
        )

    def spawn_obstacle(self, obstacle: dict[str, object]) -> None:
        obstacle_id = str(obstacle["id"])
        lane = self._lane(int(obstacle["lane"]))
        longitudinal = float(obstacle["longitudinal"])
        if obstacle["kind"] == "stalled_vehicle":
            stalled_vehicle = self.env.engine.spawn_object(
                self._static_vehicle,
                name=obstacle_id,
                vehicle_config={
                    "spawn_lane_index": list(lane.index),
                    "spawn_longitude": longitudinal,
                    "length": float(obstacle["length"]),
                },
            )
            stalled_vehicle.set_static(True)
            self._obstacles[obstacle_id] = stalled_vehicle
            return
        obstacle_type = self._obstacle_types[str(obstacle["kind"])]
        self._obstacles[obstacle_id] = self.env.engine.spawn_object(
            obstacle_type,
            name=obstacle_id,
            lane=lane,
            position=lane.position(longitudinal, 0.0),
            heading_theta=lane.heading_theta_at(longitudinal),
            static=True,
        )

    def stop_actor(self, actor_id: str) -> None:
        self._actors[actor_id].set_static(True)
        self._stopped_actor_ids.add(actor_id)

    def activate_actor(self, actor_id: str) -> None:
        self._actors[actor_id].set_static(False)
        self._stopped_actor_ids.discard(actor_id)

    def set_speed_limit(self, actor_id: str) -> None:
        self._speed_limited.add(actor_id)

    def actor_longitudinal(self, actor_id: str) -> float:
        return float(self._actors[actor_id].position[0])

    def actor_distance(self, first_actor_id: str, second_actor_id: str) -> float:
        return abs(self.actor_longitudinal(first_actor_id) - self.actor_longitudinal(second_actor_id))

    def ego_action(self, state: _RuntimePlanState) -> list[float]:
        ego = next(actor for actor in state.actors.values() if actor.get("role") == "ego")
        behavior = ego.get("behavior", "keep_lane")
        throttle = 0.5
        steering = 0.0
        if behavior == "yield":
            throttle = -1.0
        elif behavior == "merge":
            steering = 0.25
        elif behavior == "avoid_obstacle":
            steering = -0.25
        elif behavior == "follow_lead":
            leads = [actor_id for actor_id in self._actors if actor_id != str(ego["id"])]
            if leads and self.actor_distance(str(ego["id"]), leads[0]) <= float(
                self._safety.get("minimum_headway", 2.0)
            ):
                throttle = -1.0
        if str(ego["id"]) in self._speed_limited and self._actors[str(ego["id"])].speed_km_h >= float(
            self._safety.get("max_speed", 20.0)
        ) * 3.6:
            throttle = 0.0
        return [steering, throttle]

    def actor_trace(self, state: _RuntimePlanState) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for actor_id, actor in state.actors.items():
            vehicle = self._actors[actor_id]
            result.append(
                {
                    "actor_id": actor_id,
                    "role": actor["role"],
                    "position": [float(value) for value in vehicle.position],
                    "heading": float(vehicle.heading_theta),
                    "speed_km_h": float(vehicle.speed_km_h),
                    "behavior": actor.get("behavior", "keep_lane"),
                    "goal": actor.get("goal"),
                    "state": "stopped" if actor_id in self._stopped_actor_ids else "active",
                }
            )
        return result

    def obstacle_trace(self) -> list[dict[str, object]]:
        return [
            {
                "obstacle_id": obstacle_id,
                "position": [float(value) for value in obstacle.position],
                "state": "static",
            }
            for obstacle_id, obstacle in self._obstacles.items()
        ]


def _write_json(path: Path, payload: object) -> None:
    path.write_bytes(rfc8785.dumps(payload) + b"\n")


def _synthetic_success(case: dict[str, Any]) -> dict[str, object]:
    steps = min(int(case["metadrive_config"]["horizon"]), 10)
    runtime_plan = dict(case.get("runtime_plan", {}))
    actor_states = [
        {
            "actor_id": actor["id"],
            "role": actor["role"],
            "state": "spawned",
        }
        for actor in runtime_plan.get("actors", [])
    ]
    event_receipts = [
        {"trigger_id": trigger["id"], "status": "not_triggered"}
        for trigger in runtime_plan.get("event_triggers", [])
    ]
    return {
        "record": {
            "schema_version": "scenarioforge.run-record.v1",
            "case_index": case["case_index"],
            "seed": case["seed"],
            "status": "completed",
            "scenario_verdict": "pass",
            "termination_reason": "max_steps",
            "steps": steps,
            "simulated_seconds": float(steps) / 10.0,
            "collision": False,
            "off_road": False,
            "route_progress": 0.25,
            "wall_seconds": 0.0,
            "cpu_seconds": 0.0,
            "peak_rss_bytes": 0,
            "worker_pid": os.getpid(),
            "worker_instance_id": f"pid-{os.getpid()}",
            "retry_count": 0,
            "backend": "metadrive-simulator",
            "backend_version": "0.4.3",
            "effective_config_digest": case["effective_config_digest"],
        },
        "trace": [
            {
                "step": 0,
                "position": [0.0, 0.0],
                "heading": 0.0,
                "speed_km_h": 0.0,
                "collision": False,
                "off_road": False,
                "route_progress": 0.0,
                "actors": actor_states,
                "event_receipts": event_receipts,
            },
            {
                "step": steps,
                "position": [float(steps), 0.0],
                "heading": 0.0,
                "speed_km_h": 36.0,
                "collision": False,
                "off_road": False,
                "route_progress": 0.25,
                "actors": actor_states,
                "event_receipts": event_receipts,
            },
        ],
        "provenance": {
            "backend": "metadrive-simulator",
            "backend_version": "0.4.3",
            "scenarioforge_version": scenarioforge_version,
            "python_version": platform.python_version(),
            "worker_pid": os.getpid(),
            "execution_kind": "fault-injection-fixture",
            "network_policy": "denied",
        },
    }


def _termination_reason(info: dict[str, Any], truncated: bool) -> str:
    ordered = (
        ("arrive_dest", "arrive_dest"),
        ("crash_vehicle", "crash_vehicle"),
        ("crash_object", "crash_object"),
        ("crash_building", "crash_building"),
        ("out_of_road", "out_of_road"),
    )
    for key, reason in ordered:
        if bool(info.get(key, False)):
            return reason
    return "max_steps" if truncated else "terminated"


def _run_metadrive(case: dict[str, Any], max_simulated_seconds: float) -> dict[str, object]:
    wall_started = time.monotonic()
    cpu_started = time.process_time()
    runtime = check_metadrive_runtime()
    from metadrive import MetaDriveEnv
    from metadrive.engine import base_engine

    def _deny_download(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("runtime asset download is forbidden")

    base_engine.pull_asset = _deny_download
    config = dict(case["metadrive_config"])
    env = MetaDriveEnv(config)
    trace: list[dict[str, object]] = []
    last_info: dict[str, Any] = {}
    steps = 0
    collision = False
    off_road = False
    route_progress = 0.0
    simulated_seconds = 0.0
    termination_reason = "max_steps"
    try:
        env.reset(seed=int(case["seed"]))
        runtime_plan = dict(case.get("runtime_plan", {}))
        metadrive_runtime = _MetaDriveRuntime(env, runtime_plan)
        runtime_state = _activate_runtime_plan(metadrive_runtime, runtime_plan)
        event_receipts: list[dict[str, str]] = _advance_runtime_plan(
            metadrive_runtime, runtime_state, simulated_seconds=0.0
        )
        trace.append(
            {
                "step": 0,
                "position": [float(value) for value in env.agent.position],
                "heading": float(env.agent.heading_theta),
                "speed_km_h": float(env.agent.speed_km_h),
                "collision": False,
                "off_road": False,
                "route_progress": 0.0,
                "actors": metadrive_runtime.actor_trace(runtime_state),
                "static_obstacles": metadrive_runtime.obstacle_trace(),
                "event_receipts": event_receipts,
            }
        )
        while steps < int(config["horizon"]):
            _, _, terminated, truncated, last_info = env.step(metadrive_runtime.ego_action(runtime_state))
            steps += 1
            collision = bool(last_info.get("crash", False))
            off_road = bool(last_info.get("out_of_road", False))
            route_progress = float(last_info.get("route_completion", route_progress))
            simulated_seconds = steps * float(env.config["decision_repeat"]) * float(
                env.config["physics_world_step_size"]
            )
            event_receipts.extend(
                _advance_runtime_plan(
                    metadrive_runtime, runtime_state, simulated_seconds=simulated_seconds
                )
            )
            trace.append(
                {
                    "step": steps,
                    "position": [float(value) for value in env.agent.position],
                    "heading": float(env.agent.heading_theta),
                    "speed_km_h": float(env.agent.speed_km_h),
                    "collision": collision,
                    "off_road": off_road,
                    "route_progress": route_progress,
                    "actors": metadrive_runtime.actor_trace(runtime_state),
                    "static_obstacles": metadrive_runtime.obstacle_trace(),
                    "event_receipts": list(event_receipts),
                }
            )
            if terminated or truncated or simulated_seconds >= max_simulated_seconds:
                termination_reason = _termination_reason(last_info, bool(truncated))
                break
    finally:
        env.close()
    verdict = "fail" if collision or off_road else "pass"
    wall_seconds = time.monotonic() - wall_started
    cpu_seconds = time.process_time() - cpu_started
    peak_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return {
        "record": {
            "schema_version": "scenarioforge.run-record.v1",
            "case_index": case["case_index"],
            "seed": case["seed"],
            "status": "completed",
            "scenario_verdict": verdict,
            "termination_reason": termination_reason,
            "steps": steps,
            "simulated_seconds": simulated_seconds,
            "collision": collision,
            "off_road": off_road,
            "route_progress": route_progress,
            "wall_seconds": wall_seconds,
            "cpu_seconds": cpu_seconds,
            "peak_rss_bytes": peak_rss_bytes,
            "worker_pid": os.getpid(),
            "worker_instance_id": f"pid-{os.getpid()}",
            "retry_count": 0,
            "backend": runtime.distribution,
            "backend_version": runtime.version,
            "effective_config_digest": case["effective_config_digest"],
        },
        "trace": trace,
        "provenance": {
            "backend": runtime.distribution,
            "backend_version": runtime.version,
            "asset_version": runtime.asset_version,
            "asset_lock_sha256": runtime.asset_lock_sha256,
            "scenarioforge_version": scenarioforge_version,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "worker_pid": os.getpid(),
            "execution_kind": "real-metadrive",
            "network_policy": runtime.network_policy,
            "auto_download": runtime.auto_download,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=[
            "metadrive",
            "success",
            "case_crash",
            "case_timeout",
            "bundle_cancel",
            "bundle_quota",
            "disk_exhaustion",
            "supervisor_failure",
        ],
        required=True,
    )
    args = parser.parse_args()
    payload = json.loads(args.case.read_bytes())
    case = payload["case"]
    max_simulated_seconds = float(payload["max_simulated_seconds"])
    if args.mode == "case_crash":
        os._exit(86)
    if args.mode in {
        "case_timeout",
        "bundle_cancel",
        "bundle_quota",
        "disk_exhaustion",
        "supervisor_failure",
    }:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
        _write_json(Path(f"{args.result}.ready"), {"child_pid": child.pid})
        while True:
            time.sleep(60)
    try:
        result = (
            _synthetic_success(case)
            if args.mode == "success"
            else _run_metadrive(case, max_simulated_seconds)
        )
        _write_json(args.result, result)
        return 0
    except Exception as error:  # noqa: BLE001 - process boundary must persist every worker failure
        _write_json(
            args.result,
            {
                "error": {
                    "type": type(error).__name__,
                    "message": str(error)[:500],
                }
            },
        )
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
