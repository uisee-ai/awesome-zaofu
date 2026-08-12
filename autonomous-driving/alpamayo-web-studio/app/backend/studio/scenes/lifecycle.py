"""Auditable lifecycle operations that preserve immutable scene versions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from studio.schemas.scene import CameraInput, FrameInput, SceneInput, VehicleHistory
from studio.scenes.create import InMemorySceneRepository, Scene, SceneVersion


class SceneLifecycleError(ValueError):
    """A stable, user-safe reason why a lifecycle operation was rejected."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LifecycleScene:
    scene: Scene
    scene_version: SceneVersion


@dataclass(frozen=True)
class ArchivedScene:
    scene_id: str
    is_archived: bool


@dataclass(frozen=True)
class SceneAuditRecord:
    action: Literal["edited", "copied", "archived"]
    actor_id: str
    scene_id: str


class SceneLifecycleService:
    """Mutates a scene's current pointer without changing any saved version."""

    def __init__(self, repository: InMemorySceneRepository) -> None:
        self._repository = repository
        self._archived_scene_ids: set[str] = set()
        self._audit_records: list[SceneAuditRecord] = []

    def edit_scene(
        self, scene_id: str, *, name: str, navigation_instruction: str, actor_id: str
    ) -> LifecycleScene:
        scene, current_version = self._current_scene(scene_id)
        self._require_text(name, "SCENE_NAME_REQUIRED", "场景名称不能为空")
        self._require_text(navigation_instruction, "NAVIGATION_REQUIRED", "导航输入不能为空")
        self._require_text(actor_id, "ACTOR_REQUIRED", "操作人不能为空")

        version = SceneVersion(
            id=self._repository.allocate_version_id(),
            scene_id=scene.id,
            scene_input=_copy_scene_input(current_version.scene_input, name=name),
            navigation_instruction=navigation_instruction,
            asset_ids=tuple(current_version.asset_ids),
            warnings=tuple(current_version.warnings),
        )
        updated_scene = Scene(id=scene.id, name=name, current_version_id=version.id)
        self._repository.save(updated_scene, version)
        self._audit_records.append(SceneAuditRecord(action="edited", actor_id=actor_id, scene_id=scene.id))
        return LifecycleScene(scene=updated_scene, scene_version=version)

    def copy_scene(self, scene_id: str, *, name: str, actor_id: str) -> LifecycleScene:
        _, current_version = self._current_scene(scene_id)
        self._require_text(name, "SCENE_NAME_REQUIRED", "场景名称不能为空")
        self._require_text(actor_id, "ACTOR_REQUIRED", "操作人不能为空")

        copied_scene_id = self._repository.allocate_scene_id()
        copied_version = SceneVersion(
            id=self._repository.allocate_version_id(),
            scene_id=copied_scene_id,
            scene_input=_copy_scene_input(current_version.scene_input, name=name),
            navigation_instruction=current_version.navigation_instruction,
            asset_ids=tuple(current_version.asset_ids),
            warnings=tuple(current_version.warnings),
        )
        copied_scene = Scene(id=copied_scene_id, name=name, current_version_id=copied_version.id)
        self._repository.save(copied_scene, copied_version)
        self._audit_records.append(SceneAuditRecord(action="copied", actor_id=actor_id, scene_id=scene_id))
        return LifecycleScene(scene=copied_scene, scene_version=copied_version)

    def archive_scene(self, scene_id: str, *, actor_id: str) -> ArchivedScene:
        self._current_scene(scene_id)
        self._require_text(actor_id, "ACTOR_REQUIRED", "操作人不能为空")
        self._archived_scene_ids.add(scene_id)
        self._audit_records.append(SceneAuditRecord(action="archived", actor_id=actor_id, scene_id=scene_id))
        return ArchivedScene(scene_id=scene_id, is_archived=True)

    def audit_records(self) -> tuple[SceneAuditRecord, ...]:
        return tuple(self._audit_records)

    def is_archived(self, scene_id: str) -> bool:
        return scene_id in self._archived_scene_ids

    def _current_scene(self, scene_id: str) -> tuple[Scene, SceneVersion]:
        scene = self._repository._scenes.get(scene_id)
        if scene is None:
            raise SceneLifecycleError("SCENE_NOT_FOUND", "场景不存在")
        for version in reversed(self._repository.scene_versions(scene_id)):
            if version.id == scene.current_version_id:
                return scene, version
        raise SceneLifecycleError("SCENE_VERSION_NOT_FOUND", "场景当前版本不存在")

    @staticmethod
    def _require_text(value: str, code: str, message: str) -> None:
        if not value.strip():
            raise SceneLifecycleError(code, message)


def _copy_scene_input(source: SceneInput, *, name: str) -> SceneInput:
    history = None
    if source.history is not None:
        history = VehicleHistory(
            positions=tuple(tuple(position) for position in source.history.positions),
            rotations=tuple(
                tuple(tuple(vector) for vector in rotation) for rotation in source.history.rotations
            ),
        )
    return SceneInput(
        name=name,
        cameras=tuple(
            CameraInput(
                camera_id=camera.camera_id,
                frames=tuple(
                    FrameInput(content_type=frame.content_type, filename=frame.filename)
                    for frame in camera.frames
                ),
            )
            for camera in source.cameras
        ),
        history=history,
    )
