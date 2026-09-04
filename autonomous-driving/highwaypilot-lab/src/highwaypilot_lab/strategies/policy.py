"""Four v1 strategies behind one traceable decision interface."""

from __future__ import annotations

import copy
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from highwaypilot_lab.model import VerifiedOnnxModel
from highwaypilot_lab.simulation.environment import ACTIONS as ACTION_INDEX
from highwaypilot_lab.simulation.observation import observation_vector


ACTIONS = tuple(ACTION_INDEX[index] for index in sorted(ACTION_INDEX))


class PolicyError(RuntimeError):
    """A strategy input or lifecycle contract was violated."""


@dataclass(frozen=True)
class PolicyDecision:
    strategy_id: str
    strategy_version: str
    action: str
    reason: str
    explanation: dict[str, Any]
    model_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Strategy(Protocol):
    strategy_id: str
    strategy_version: str

    def reset(self) -> None: ...

    def decide(self, snapshot: Mapping[str, Any]) -> PolicyDecision: ...


def _validate_action(action: object) -> str:
    if not isinstance(action, str) or action not in ACTIONS:
        raise PolicyError(f"unknown canonical action: {action!r}")
    return action


def _base_explanation(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    try:
        construction = snapshot["construction"]
        ego = snapshot["ego"]
        safety = snapshot["safety"]
        distance = float(construction["zone_start_m"]) - float(ego["position_m"]["x"])
        return {
            "snapshot_step": int(snapshot["step"]),
            "distance_to_construction_m": round(distance, 12),
            "target_lane_index": int(construction["target_lane_index"]),
            "min_ttc_s": safety["min_ttc_s"],
        }
    except (KeyError, TypeError, ValueError) as error:
        raise PolicyError("strategy snapshot is incomplete") from error


class ManualPolicy:
    strategy_id = "manual"
    strategy_version = "manual-policy/v1"

    def __init__(self, actions: Iterable[str]) -> None:
        self._source = tuple(_validate_action(action) for action in actions)
        self.reset()

    def reset(self) -> None:
        self._pending = deque(self._source)
        self._history: list[str] = []

    @property
    def action_history(self) -> tuple[str, ...]:
        return tuple(self._history)

    def decide(self, snapshot: Mapping[str, Any]) -> PolicyDecision:
        explanation = _base_explanation(snapshot)
        if not self._pending:
            raise PolicyError("manual action sequence exhausted")
        action = self._pending.popleft()
        self._history.append(action)
        explanation["user_action_index"] = len(self._history) - 1
        return PolicyDecision(
            self.strategy_id,
            self.strategy_version,
            action,
            "user_supplied_action",
            explanation,
        )


class RandomPolicy:
    strategy_id = "random"
    strategy_version = "random-policy/highwaypilot-rng-v1"

    def __init__(self, generator: np.random.Generator) -> None:
        self._generator = generator
        self._initial_state = copy.deepcopy(generator.bit_generator.state)

    def reset(self) -> None:
        self._generator.bit_generator.state = copy.deepcopy(self._initial_state)

    def decide(self, snapshot: Mapping[str, Any]) -> PolicyDecision:
        explanation = _base_explanation(snapshot)
        action_index = int(self._generator.integers(0, len(ACTIONS)))
        explanation["rng_stream"] = "random_policy"
        explanation["sampled_action_index"] = action_index
        return PolicyDecision(
            self.strategy_id,
            self.strategy_version,
            ACTIONS[action_index],
            "owned_rng_sample",
            explanation,
        )


class QualifiedRulePolicy:
    strategy_id = "qualified_rule"
    strategy_version = "qualified-rule-policy/v1"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._merge_pending = False

    def _lane_gaps(self, snapshot: Mapping[str, Any]) -> tuple[float | None, float | None, bool]:
        ego_x = float(snapshot["ego"]["position_m"]["x"])
        target_lane = int(snapshot["construction"]["target_lane_index"])
        front: list[float] = []
        rear: list[float] = []
        for vehicle in snapshot["vehicles"]:
            if int(vehicle["lane_index"]) != target_lane:
                continue
            gap = float(vehicle["position_m"]["x"]) - ego_x
            (front if gap >= 0 else rear).append(abs(gap))
        front_gap = min(front) if front else None
        rear_gap = min(rear) if rear else None
        occupied = (front_gap is not None and front_gap < 15.0) or (
            rear_gap is not None and rear_gap < 12.0
        )
        return front_gap, rear_gap, occupied

    def decide(self, snapshot: Mapping[str, Any]) -> PolicyDecision:
        explanation = _base_explanation(snapshot)
        try:
            ego_lane = int(snapshot["ego"]["lane_index"])
            ego_target_lane = int(snapshot["ego"].get("target_lane_index", ego_lane))
            target_lane = int(snapshot["construction"]["target_lane_index"])
            merge_action = _validate_action(snapshot["construction"]["authoritative_merge_action"])
            distance = float(explanation["distance_to_construction_m"])
            ttc = snapshot["safety"]["min_ttc_s"]
            front_gap, rear_gap, occupied = self._lane_gaps(snapshot)
        except (KeyError, TypeError, ValueError) as error:
            raise PolicyError("rule-policy snapshot is incomplete") from error
        explanation.update(
            {
                "front_gap_m": front_gap,
                "rear_gap_m": rear_gap,
                "target_lane_occupied": occupied,
                "merge_action": merge_action,
            }
        )

        if ego_lane == target_lane:
            self._merge_pending = False
            if ttc is not None and float(ttc) < 3.0:
                action, reason = "SLOWER", "target_lane_low_ttc_recovery"
            else:
                action, reason = "IDLE", "target_lane_reached"
        elif ego_target_lane == target_lane:
            self._merge_pending = False
            action = "SLOWER" if ttc is not None and float(ttc) < 3.0 else "IDLE"
            reason = "merge_in_progress"
        elif self._merge_pending:
            self._merge_pending = False
            action, reason = "SLOWER", "merge_retry_recovery"
        elif not occupied and distance <= 120.0:
            # A low TTC in the currently closing lane is not, by itself, a
            # reason to abandon an already-safe escape lane.  Prioritising
            # braking here can trap the ego behind stopped traffic because
            # DiscreteMetaAction has a non-zero minimum target speed.
            self._merge_pending = True
            action, reason = merge_action, "safe_merge_window"
        elif ttc is not None and float(ttc) < 3.0:
            action, reason = "SLOWER", "low_ttc_recovery"
        elif occupied:
            action = "SLOWER" if distance <= 40.0 else "IDLE"
            reason = "target_lane_gap_blocked"
        else:
            action, reason = "IDLE", "wait_for_merge_window"
        return PolicyDecision(
            self.strategy_id,
            self.strategy_version,
            action,
            reason,
            explanation,
        )


class OnnxLearningPolicy:
    strategy_id = "construction_dqn_onnx"
    strategy_version = "onnx-learning-policy/v1"

    def __init__(self, model_dir: str | Path) -> None:
        self.model = VerifiedOnnxModel.load(model_dir)
        self.model_version = self.model.version
        if self.model.action_mapping != ACTIONS:
            raise PolicyError("model action mapping differs from the canonical five actions")

    def reset(self) -> None:
        return None

    def decide(self, snapshot: Mapping[str, Any]) -> PolicyDecision:
        vector = observation_vector(snapshot).reshape(1, 10)
        q_values = self.model.infer(vector)[0]
        action_index = int(np.argmax(q_values))
        explanation = _base_explanation(snapshot)
        explanation.update(
            {
                "observation_schema": "construction-dqn-observation/v1",
                "q_values": [round(float(value), 8) for value in q_values],
                "selected_action_index": action_index,
                "model_sha256": self.model.sha256,
            }
        )
        return PolicyDecision(
            self.strategy_id,
            self.strategy_version,
            self.model.action_mapping[action_index],
            "maximum_q_value",
            explanation,
            model_version=self.model.version,
        )
