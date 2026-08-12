"""Creation boundary for reproducible, immutable scene versions.

The caller supplies only assets already accepted by the upload boundary.  This
module validates that those assets exactly match the scene frames, then stores a
deep snapshot so later changes to a request object cannot alter a past run's
input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from studio.assets import AssetUpload, validate_asset_upload
from studio.schemas.scene import (
    CameraInput,
    FrameInput,
    SceneInput,
    SceneWarning,
    VehicleHistory,
    validate_scene_input,
)


class SceneCreationError(ValueError):
    """A stable, user-safe reason why a scene cannot be created."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class UploadedSceneAsset:
    asset_id: str
    upload: AssetUpload


@dataclass(frozen=True)
class CreateSceneRequest:
    scene_input: SceneInput
    navigation_instruction: str
    uploaded_assets: Sequence[UploadedSceneAsset]


@dataclass(frozen=True)
class SceneVersion:
    id: str
    scene_id: str
    scene_input: SceneInput
    navigation_instruction: str
    asset_ids: tuple[str, ...]
    warnings: tuple[SceneWarning, ...]


@dataclass(frozen=True)
class Scene:
    id: str
    name: str
    current_version_id: str


@dataclass(frozen=True)
class CreatedScene:
    scene: Scene
    scene_version: SceneVersion


class InMemorySceneRepository:
    """Small deterministic repository used until a persistent store is wired in."""

    def __init__(self) -> None:
        self._scenes: dict[str, Scene] = {}
        self._versions: dict[str, list[SceneVersion]] = {}
        self._next_scene_number = 1
        self._next_version_number = 1

    def allocate_scene_id(self) -> str:
        scene_id = f"scene-{self._next_scene_number}"
        self._next_scene_number += 1
        return scene_id

    def allocate_version_id(self) -> str:
        version_id = f"scene-version-{self._next_version_number}"
        self._next_version_number += 1
        return version_id

    def save(self, scene: Scene, scene_version: SceneVersion) -> None:
        self._scenes[scene.id] = scene
        self._versions.setdefault(scene.id, []).append(scene_version)

    def scene_versions(self, scene_id: str) -> tuple[SceneVersion, ...]:
        return tuple(self._versions.get(scene_id, ()))


def create_scene(repository: InMemorySceneRepository, request: CreateSceneRequest) -> CreatedScene:
    """Create a scene and its first immutable version from accepted upload assets."""
    if not request.scene_input.name.strip():
        raise SceneCreationError("SCENE_NAME_REQUIRED", "场景名称不能为空")
    if not request.navigation_instruction.strip():
        raise SceneCreationError("NAVIGATION_REQUIRED", "导航输入不能为空")

    effective_history, warnings = validate_scene_input(request.scene_input)
    assets_by_filename = _validated_assets(request.uploaded_assets)
    frames = tuple(frame for camera in request.scene_input.cameras for frame in camera.frames)
    asset_ids = _asset_ids_for_frames(frames, assets_by_filename)

    scene_id = repository.allocate_scene_id()
    version_id = repository.allocate_version_id()
    version = SceneVersion(
        id=version_id,
        scene_id=scene_id,
        scene_input=_snapshot_scene_input(request.scene_input, effective_history),
        navigation_instruction=request.navigation_instruction,
        asset_ids=asset_ids,
        warnings=tuple(warnings),
    )
    scene = Scene(id=scene_id, name=version.scene_input.name, current_version_id=version.id)
    repository.save(scene, version)
    return CreatedScene(scene=scene, scene_version=version)


def _validated_assets(uploaded_assets: Sequence[UploadedSceneAsset]) -> dict[str, UploadedSceneAsset]:
    assets_by_filename: dict[str, UploadedSceneAsset] = {}
    asset_ids: set[str] = set()
    for asset in uploaded_assets:
        if not asset.asset_id.strip():
            raise SceneCreationError("ASSET_ID_REQUIRED", "上传资产必须具有标识符")
        validate_asset_upload(asset.upload)
        if asset.asset_id in asset_ids:
            raise SceneCreationError("DUPLICATE_ASSET", "同一场景版本不能重复引用上传资产")
        if asset.upload.filename in assets_by_filename:
            raise SceneCreationError("DUPLICATE_ASSET", "同名上传资产不能用于同一场景版本")
        asset_ids.add(asset.asset_id)
        assets_by_filename[asset.upload.filename] = asset
    return assets_by_filename


def _asset_ids_for_frames(
    frames: Sequence[FrameInput], assets_by_filename: dict[str, UploadedSceneAsset]
) -> tuple[str, ...]:
    frame_filenames = tuple(frame.filename for frame in frames)
    if len(set(frame_filenames)) != len(frame_filenames):
        raise SceneCreationError("DUPLICATE_FRAME_FILENAME", "同一场景版本不能重复引用同名帧")

    frame_filename_set = set(frame_filenames)
    asset_filename_set = set(assets_by_filename)
    if asset_filename_set - frame_filename_set:
        raise SceneCreationError("UNREFERENCED_ASSET", "每个上传资产必须恰好对应一个场景帧")
    if frame_filename_set - asset_filename_set:
        raise SceneCreationError("ASSET_FRAME_MISMATCH", "每个场景帧必须引用一个上传资产")

    asset_ids: list[str] = []
    for frame in frames:
        asset = assets_by_filename.get(frame.filename)
        if asset is None or asset.upload.content_type != frame.content_type:
            raise SceneCreationError("ASSET_FRAME_MISMATCH", "场景帧必须引用 MIME 与文件名匹配的上传资产")
        asset_ids.append(asset.asset_id)
    return tuple(asset_ids)


def _snapshot_scene_input(scene_input: SceneInput, history: VehicleHistory) -> SceneInput:
    """Return a structurally immutable copy of the validated creation input."""
    cameras = tuple(
        CameraInput(
            camera_id=camera.camera_id,
            frames=tuple(
                FrameInput(content_type=frame.content_type, filename=frame.filename)
                for frame in camera.frames
            ),
        )
        for camera in scene_input.cameras
    )
    snapshot_history = VehicleHistory(
        positions=tuple(tuple(position) for position in history.positions),
        rotations=tuple(
            tuple(tuple(vector) for vector in rotation)
            for rotation in history.rotations
        ),
    )
    return SceneInput(name=scene_input.name, cameras=cameras, history=snapshot_history)
