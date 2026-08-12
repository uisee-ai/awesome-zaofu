"""Backend representation of the shared scene and inference-result contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Sequence

CAMERA_COUNT_MIN = 1
CAMERA_COUNT_MAX = 7
FRAME_COUNT_MIN = 1
FRAME_COUNT_MAX = 8
HISTORY_LENGTH = 16
TRAJECTORY_POINT_COUNT = 64
TRAJECTORY_STEP_SECONDS = 0.1

ImageContentType = Literal["image/jpeg", "image/png"]
ReviewStatus = Literal["unreviewed", "approved", "rejected"]
Vector3 = tuple[float, float, float]
RotationMatrix3 = tuple[Vector3, Vector3, Vector3]


@dataclass(frozen=True)
class FrameInput:
    content_type: ImageContentType
    filename: str


@dataclass(frozen=True)
class CameraInput:
    camera_id: int
    frames: Sequence[FrameInput]


@dataclass(frozen=True)
class VehicleHistory:
    positions: Sequence[Vector3]
    rotations: Sequence[RotationMatrix3]


@dataclass(frozen=True)
class SceneInput:
    name: str
    cameras: Sequence[CameraInput]
    history: VehicleHistory | None = None


@dataclass(frozen=True)
class SceneWarning:
    code: Literal["REDUCED_CAMERA_COVERAGE", "MISSING_HISTORY"]
    severity: Literal["warning"] = "warning"


@dataclass(frozen=True)
class TrajectoryPoint:
    time_seconds: float
    position: Vector3
    rotation: RotationMatrix3


@dataclass(frozen=True)
class InferenceResult:
    vqa_answer: str
    chain_of_causation: str
    meta_action: str
    trajectory: Sequence[TrajectoryPoint]
    review_status: ReviewStatus = "unreviewed"
    model_name: str | None = None
    model_version: str | None = None
    parameters: dict[str, object] = field(default_factory=dict)
    seed: int | None = None

    def __post_init__(self) -> None:
        if not all((self.vqa_answer.strip(), self.chain_of_causation.strip(), self.meta_action.strip())):
            raise ValueError("VQA、CoC 和 Meta Action 均为必填字段")
        if len(self.trajectory) != TRAJECTORY_POINT_COUNT:
            raise ValueError("未来轨迹必须包含 64 个时间点")
        for index, point in enumerate(self.trajectory, start=1):
            if point.time_seconds != round(index * TRAJECTORY_STEP_SECONDS, 1):
                raise ValueError("未来轨迹必须以 0.1 秒步长覆盖 0.1–6.4 秒")


def validate_scene_input(scene: SceneInput) -> tuple[VehicleHistory, list[SceneWarning]]:
    """Validate shared scene invariants and return effective history plus warnings."""
    if not CAMERA_COUNT_MIN <= len(scene.cameras) <= CAMERA_COUNT_MAX:
        raise ValueError("场景必须包含 1–7 路 Camera")
    camera_ids = [camera.camera_id for camera in scene.cameras]
    if len(set(camera_ids)) != len(camera_ids) or any(not 0 <= camera_id <= 6 for camera_id in camera_ids):
        raise ValueError("Camera ID 必须唯一且在 0–6 范围内")

    frame_counts = {len(camera.frames) for camera in scene.cameras}
    if len(frame_counts) != 1 or not FRAME_COUNT_MIN <= next(iter(frame_counts)) <= FRAME_COUNT_MAX:
        raise ValueError("每路 Camera 需有相同的 1–8 帧")
    for camera in scene.cameras:
        for frame in camera.frames:
            if frame.content_type not in ("image/jpeg", "image/png"):
                raise ValueError("图片 MIME 必须是 image/jpeg 或 image/png")
            suffixes = (".png",) if frame.content_type == "image/png" else (".jpg", ".jpeg")
            if not frame.filename.lower().endswith(suffixes):
                raise ValueError("图片文件扩展名必须与 JPEG/PNG MIME 一致")

    warnings: list[SceneWarning] = []
    if len(scene.cameras) < 4:
        warnings.append(SceneWarning(code="REDUCED_CAMERA_COVERAGE"))
    if scene.history is None:
        warnings.append(SceneWarning(code="MISSING_HISTORY"))
        return _stationary_history(), warnings
    if len(scene.history.positions) != HISTORY_LENGTH or len(scene.history.rotations) != HISTORY_LENGTH:
        raise ValueError("车辆历史位置和旋转矩阵都必须包含 16 条记录")
    return scene.history, warnings


def _stationary_history() -> VehicleHistory:
    identity: RotationMatrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return VehicleHistory(
        positions=[(0.0, 0.0, 0.0) for _ in range(HISTORY_LENGTH)],
        rotations=[identity for _ in range(HISTORY_LENGTH)],
    )
