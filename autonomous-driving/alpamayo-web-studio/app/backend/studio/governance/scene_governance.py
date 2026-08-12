"""Safe deletion and content-addressed storage for scenes.

The service deliberately retains deleted records so a later persistence layer
can support audit and recovery without treating a delete as an irreversible
physical removal.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256


class GovernanceError(ValueError):
    """A stable, user-safe reason why a governance action was rejected."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredAsset:
    id: str
    content_hash: str
    size_bytes: int


@dataclass(frozen=True)
class SceneRecord:
    id: str
    name: str
    deleted_at: datetime | None = None
    deleted_by: str | None = None


@dataclass(frozen=True)
class DeletionConfirmation:
    id: str
    scene_id: str
    actor_id: str


class InMemorySceneGovernance:
    """Deterministic governance store used until database repositories are wired."""

    def __init__(self) -> None:
        self._scenes: dict[str, SceneRecord] = {}
        self._assets_by_hash: dict[str, StoredAsset] = {}
        self._confirmations: dict[str, DeletionConfirmation] = {}
        self._next_asset_number = 1
        self._next_confirmation_number = 1

    def add_scene(self, scene_id: str, name: str) -> SceneRecord:
        if not scene_id.strip():
            raise GovernanceError("SCENE_ID_REQUIRED", "场景必须具有标识符")
        if not name.strip():
            raise GovernanceError("SCENE_NAME_REQUIRED", "场景名称不能为空")
        if scene_id in self._scenes:
            raise GovernanceError("SCENE_ALREADY_EXISTS", "场景已存在")
        scene = SceneRecord(id=scene_id, name=name)
        self._scenes[scene_id] = scene
        return scene

    def store_asset(self, content: bytes) -> StoredAsset:
        """Store content once and return the same asset record for identical bytes."""
        content_hash = sha256(content).hexdigest()
        existing = self._assets_by_hash.get(content_hash)
        if existing is not None:
            return existing

        asset = StoredAsset(
            id=f"asset-{self._next_asset_number}",
            content_hash=content_hash,
            size_bytes=len(content),
        )
        self._next_asset_number += 1
        self._assets_by_hash[content_hash] = asset
        return asset

    def asset_count(self) -> int:
        return len(self._assets_by_hash)

    def scene_record(self, scene_id: str) -> SceneRecord | None:
        return self._scenes.get(scene_id)

    def active_scene(self, scene_id: str) -> SceneRecord | None:
        scene = self.scene_record(scene_id)
        return scene if scene is not None and scene.deleted_at is None else None

    def request_deletion(
        self, scene_id: str, *, actor_id: str, is_administrator: bool
    ) -> DeletionConfirmation:
        self._require_administrator(actor_id, is_administrator)
        self._require_active_scene(scene_id)
        confirmation = DeletionConfirmation(
            id=f"delete-confirmation-{self._next_confirmation_number}",
            scene_id=scene_id,
            actor_id=actor_id,
        )
        self._next_confirmation_number += 1
        self._confirmations[confirmation.id] = confirmation
        return confirmation

    def confirm_deletion(
        self,
        scene_id: str,
        *,
        actor_id: str,
        confirmation_id: str,
        is_administrator: bool,
    ) -> SceneRecord:
        self._require_administrator(actor_id, is_administrator)
        scene = self._require_active_scene(scene_id)
        confirmation = self._confirmations.get(confirmation_id)
        if confirmation is None or confirmation.scene_id != scene_id or confirmation.actor_id != actor_id:
            raise GovernanceError("CONFIRMATION_REQUIRED", "必须使用管理员的二次确认才能删除场景")

        deleted = replace(
            scene,
            deleted_at=datetime.now(timezone.utc),
            deleted_by=actor_id,
        )
        self._scenes[scene_id] = deleted
        del self._confirmations[confirmation_id]
        return deleted

    @staticmethod
    def _require_administrator(actor_id: str, is_administrator: bool) -> None:
        if not actor_id.strip() or not is_administrator:
            raise GovernanceError("ADMIN_REQUIRED", "只有管理员可以删除场景")

    def _require_active_scene(self, scene_id: str) -> SceneRecord:
        scene = self.active_scene(scene_id)
        if scene is None:
            raise GovernanceError("SCENE_NOT_FOUND", "未找到可删除的场景")
        return scene
