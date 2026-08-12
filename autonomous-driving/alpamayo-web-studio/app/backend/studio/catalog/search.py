"""Searchable read projection for scenes already created by the scene boundary.

This module deliberately does not mutate ``scenes.create`` storage.  A future
persistent repository can adapt immutable Scene/SceneVersion records into
``CatalogScene`` while preserving the search and integrity semantics here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Sequence

IntegrityState = Literal["complete", "needs_attention"]


@dataclass(frozen=True)
class CatalogScene:
    scene_id: str
    name: str
    camera_ids: Sequence[int]
    tags: Sequence[str]
    source: str
    created_at: datetime
    asset_ids: Sequence[str]


@dataclass(frozen=True)
class SceneCatalogSearch:
    name: str | None = None
    camera_id: int | None = None
    tags: Sequence[str] = ()
    source: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


@dataclass(frozen=True)
class DataIntegrityIssue:
    code: str
    message: str


@dataclass(frozen=True)
class DataIntegrityStatus:
    state: IntegrityState
    issues: tuple[DataIntegrityIssue, ...]


@dataclass(frozen=True)
class SceneCatalogResult:
    scene_id: str
    name: str
    camera_ids: tuple[int, ...]
    tags: tuple[str, ...]
    source: str
    created_at: datetime
    integrity: DataIntegrityStatus


class SceneCatalog:
    """Deterministic in-memory projection with composable, inclusive filters."""

    def __init__(self, scenes: Sequence[CatalogScene] = ()) -> None:
        self._scenes = tuple(scenes)

    def search(self, filters: SceneCatalogSearch | None = None) -> tuple[SceneCatalogResult, ...]:
        filters = filters or SceneCatalogSearch()
        _validate_time_window(filters)
        return tuple(
            _to_result(scene)
            for scene in self._scenes
            if _matches(scene, filters)
        )


class SceneCatalogApi:
    """HTTP-shaped read entry used by the mounted Studio API.

    The root application can mount ``get`` at ``/api/catalog/scenes`` without
    duplicating filter parsing or integrity serialization.
    """

    def __init__(self, catalog: SceneCatalog) -> None:
        self._catalog = catalog

    def get(self, query: Mapping[str, object]) -> dict[str, object]:
        filters = SceneCatalogSearch(
            name=_optional_string(query.get("name")),
            camera_id=_optional_integer(query.get("cameraId"), "cameraId"),
            tags=_string_values(query.get("tags")),
            source=_optional_string(query.get("source")),
            created_after=_optional_datetime(query.get("createdAfter"), "createdAfter"),
            created_before=_optional_datetime(query.get("createdBefore"), "createdBefore"),
        )
        return {"items": [_serialize_result(result) for result in self._catalog.search(filters)]}


def _matches(scene: CatalogScene, filters: SceneCatalogSearch) -> bool:
    if filters.name and filters.name.casefold() not in scene.name.casefold():
        return False
    if filters.camera_id is not None and filters.camera_id not in scene.camera_ids:
        return False
    scene_tags = {tag.casefold() for tag in scene.tags}
    if any(tag.casefold() not in scene_tags for tag in filters.tags):
        return False
    if filters.source and filters.source.casefold() != scene.source.casefold():
        return False
    if filters.created_after and scene.created_at < filters.created_after:
        return False
    if filters.created_before and scene.created_at > filters.created_before:
        return False
    return True


def _validate_time_window(filters: SceneCatalogSearch) -> None:
    if filters.created_after and filters.created_before and filters.created_after > filters.created_before:
        raise ValueError("搜索开始时间不能晚于结束时间")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("搜索参数必须是字符串")
    return value or None


def _string_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else tuple(value) if isinstance(value, Sequence) else ()
    if not all(isinstance(item, str) for item in values):
        raise ValueError("tags 必须是字符串列表")
    return tuple(item for item in values if item)


def _optional_integer(value: object, field: str) -> int | None:
    text = _optional_string(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as error:
        raise ValueError(f"{field} 必须是整数") from error


def _optional_datetime(value: object, field: str) -> datetime | None:
    text = _optional_string(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} 必须是 ISO-8601 时间") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")
    return parsed


def _to_result(scene: CatalogScene) -> SceneCatalogResult:
    return SceneCatalogResult(
        scene_id=scene.scene_id,
        name=scene.name,
        camera_ids=tuple(scene.camera_ids),
        tags=tuple(scene.tags),
        source=scene.source,
        created_at=scene.created_at,
        integrity=_integrity_for(scene),
    )


def _serialize_result(result: SceneCatalogResult) -> dict[str, object]:
    return {
        "sceneId": result.scene_id,
        "name": result.name,
        "cameraIds": list(result.camera_ids),
        "tags": list(result.tags),
        "source": result.source,
        "createdAt": result.created_at.isoformat().replace("+00:00", "Z"),
        "integrity": {
            "state": result.integrity.state,
            "issues": [
                {"code": issue.code, "message": issue.message}
                for issue in result.integrity.issues
            ],
        },
    }


def _integrity_for(scene: CatalogScene) -> DataIntegrityStatus:
    issues: list[DataIntegrityIssue] = []
    if not scene.name.strip():
        issues.append(DataIntegrityIssue("MISSING_NAME", "场景名称缺失"))
    if not scene.source.strip():
        issues.append(DataIntegrityIssue("MISSING_SOURCE", "数据来源缺失"))
    if not scene.camera_ids:
        issues.append(DataIntegrityIssue("MISSING_CAMERA", "Camera 信息缺失"))
    elif len(set(scene.camera_ids)) != len(scene.camera_ids):
        issues.append(DataIntegrityIssue("DUPLICATE_CAMERA_ID", "Camera ID 不能重复"))
    elif any(camera_id < 0 or camera_id > 6 for camera_id in scene.camera_ids):
        issues.append(DataIntegrityIssue("INVALID_CAMERA_ID", "Camera ID 必须在 0–6 范围内"))
    if not scene.asset_ids:
        issues.append(DataIntegrityIssue("MISSING_ASSET_REFERENCE", "场景缺少资产引用"))
    elif len(set(scene.asset_ids)) != len(scene.asset_ids):
        issues.append(DataIntegrityIssue("DUPLICATE_ASSET_REFERENCE", "资产引用不能重复"))
    return DataIntegrityStatus(
        state="complete" if not issues else "needs_attention",
        issues=tuple(issues),
    )
