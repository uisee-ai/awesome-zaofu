from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Never

from scenarioforge.core.canonical import (
    CanonicalModel,
    JSONValue,
    canonical_bytes,
    canonical_digest,
    freeze_json,
    thaw_json,
)

from .presets import PresetCatalog
from .storage import (
    SQLiteLibraryStorage,
    StorageArchived,
    StorageDraftConflict,
)


class LibraryError(RuntimeError):
    pass


class UnknownScenarioError(LibraryError):
    pass


class UnknownRevisionError(LibraryError):
    pass


class DraftConflictError(LibraryError):
    pass


class ArchivedScenarioError(LibraryError):
    pass


class ImmutableRevisionError(LibraryError):
    pass


class InvalidDraftError(ValueError):
    pass


@dataclass(frozen=True)
class DraftSnapshot(CanonicalModel):
    scenario_id: str
    generation: int
    schema_version: str
    content: JSONValue
    provenance: JSONValue
    latest_revision_id: str | None
    archived: bool


@dataclass(frozen=True)
class ScenarioRevision(CanonicalModel):
    scenario_id: str
    revision_id: str
    parent_revision_id: str | None
    revision_number: int
    schema_version: str
    canonical_digest: str
    content: JSONValue
    provenance: JSONValue
    created_at: str

    @property
    def canonical_payload(self) -> bytes:
        return canonical_bytes(self.content)


@dataclass(frozen=True)
class ScenarioSummary(CanonicalModel):
    scenario_id: str
    schema_version: str
    draft_generation: int
    latest_revision_id: str | None
    archived: bool
    provenance: JSONValue


@dataclass(frozen=True)
class ArchiveTombstone(CanonicalModel):
    tombstone_id: str
    scenario_id: str
    latest_revision_id: str | None
    archived_at: str
    provenance: JSONValue


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _default_id_factory(kind: str) -> str:
    return f"{kind}_{uuid.uuid4().hex}"


def _document(content: Mapping[str, Any]) -> tuple[dict[str, Any], str, bytes]:
    if not isinstance(content, Mapping):
        raise InvalidDraftError("draft must contain a JSON object")
    value = thaw_json(content)
    if not isinstance(value, dict):
        raise InvalidDraftError("draft must contain a JSON object")
    schema_version = value.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        raise InvalidDraftError("draft schema version is missing")
    try:
        payload = canonical_bytes(value)
    except (TypeError, ValueError) as error:
        raise InvalidDraftError("draft must contain finite JSON data") from error
    return value, schema_version, payload


def _decode_mapping(payload: object) -> dict[str, Any]:
    value = json.loads(bytes(payload))
    if not isinstance(value, dict):
        raise RuntimeError("stored library record is not a JSON object")
    return value


class LocalScenarioLibrary:
    """Server-owned drafts with atomic append-only immutable revisions."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        storage: SQLiteLibraryStorage | None = None,
        preset_catalog: PresetCatalog | None = None,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        if storage is not None and root is not None:
            raise ValueError("provide either root or storage")
        if storage is None:
            if root is None:
                raise ValueError("library root is required")
            root_path = Path(root)
            database_path = (
                root_path
                if root_path.suffix in {".db", ".sqlite", ".sqlite3"}
                else root_path / "library.sqlite3"
            )
            storage = SQLiteLibraryStorage(database_path)
        self._storage = storage
        self._presets = preset_catalog or PresetCatalog()
        self._id_factory = id_factory or _default_id_factory
        self._clock = clock or _default_clock

    @staticmethod
    def _actor(actor: str) -> str:
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError("actor must be a non-empty string")
        return actor

    def _draft(self, row: Mapping[str, Any]) -> DraftSnapshot:
        return DraftSnapshot(
            scenario_id=str(row["scenario_id"]),
            generation=int(row["draft_generation"]),
            schema_version=str(row["schema_version"]),
            content=freeze_json(_decode_mapping(row["draft_payload"])),
            provenance=freeze_json(_decode_mapping(row["provenance_payload"])),
            latest_revision_id=(
                None
                if row["latest_revision_id"] is None
                else str(row["latest_revision_id"])
            ),
            archived=bool(row["archived"]),
        )

    def _revision(self, row: Mapping[str, Any]) -> ScenarioRevision:
        return ScenarioRevision(
            scenario_id=str(row["scenario_id"]),
            revision_id=str(row["revision_id"]),
            parent_revision_id=(
                None
                if row["parent_revision_id"] is None
                else str(row["parent_revision_id"])
            ),
            revision_number=int(row["revision_number"]),
            schema_version=str(row["schema_version"]),
            canonical_digest=str(row["canonical_digest"]),
            content=freeze_json(_decode_mapping(row["canonical_payload"])),
            provenance=freeze_json(_decode_mapping(row["provenance_payload"])),
            created_at=str(row["created_at"]),
        )

    def _tombstone(self, row: Mapping[str, Any]) -> ArchiveTombstone:
        return ArchiveTombstone(
            tombstone_id=str(row["tombstone_id"]),
            scenario_id=str(row["scenario_id"]),
            latest_revision_id=(
                None
                if row["latest_revision_id"] is None
                else str(row["latest_revision_id"])
            ),
            archived_at=str(row["archived_at"]),
            provenance=freeze_json(_decode_mapping(row["provenance_payload"])),
        )

    @staticmethod
    def _unknown_scenario(error: KeyError) -> Never:
        raise UnknownScenarioError("unknown scenario") from error

    def create_draft(
        self,
        content: Mapping[str, Any],
        *,
        actor: str = "local_operator",
    ) -> DraftSnapshot:
        _, schema_version, payload = _document(content)
        timestamp = self._clock()
        provenance = {
            "kind": "user_draft",
            "actor": self._actor(actor),
            "created_at": timestamp,
        }
        row = self._storage.create_draft(
            scenario_id=self._id_factory("scenario"),
            payload=payload,
            schema_version=schema_version,
            provenance_payload=canonical_bytes(provenance),
            created_at=timestamp,
        )
        return self._draft(row)

    def get_draft(self, scenario_id: str) -> DraftSnapshot:
        try:
            return self._draft(self._storage.read_draft(scenario_id))
        except KeyError as error:
            self._unknown_scenario(error)

    def update_draft(
        self,
        scenario_id: str,
        content: Mapping[str, Any],
        *,
        expected_generation: int,
        actor: str = "local_operator",
    ) -> DraftSnapshot:
        self._actor(actor)
        _, schema_version, payload = _document(content)
        try:
            row = self._storage.update_draft(
                scenario_id=scenario_id,
                payload=payload,
                schema_version=schema_version,
                expected_generation=expected_generation,
            )
        except KeyError as error:
            self._unknown_scenario(error)
        except StorageDraftConflict as error:
            raise DraftConflictError("draft generation conflict") from error
        except StorageArchived as error:
            raise ArchivedScenarioError("scenario is archived") from error
        return self._draft(row)

    @staticmethod
    def _revision_provenance(
        draft: DraftSnapshot,
        *,
        actor: str,
        created_at: str,
    ) -> dict[str, Any]:
        origin = thaw_json(draft.provenance)
        provenance = {
            "kind": str(origin["kind"]),
            "actor": actor,
            "created_at": created_at,
            "draft_generation": draft.generation,
        }
        for key in ("template_id", "template_digest"):
            if key in origin:
                provenance[key] = origin[key]
        return provenance

    def save_draft(
        self,
        scenario_id: str,
        *,
        expected_generation: int | None = None,
        actor: str = "local_operator",
    ) -> ScenarioRevision:
        actor = self._actor(actor)
        draft = self.get_draft(scenario_id)
        generation = draft.generation if expected_generation is None else expected_generation
        if generation != draft.generation:
            raise DraftConflictError("draft generation conflict")
        _, schema_version, payload = _document(thaw_json(draft.content))
        timestamp = self._clock()
        provenance = self._revision_provenance(
            draft,
            actor=actor,
            created_at=timestamp,
        )
        try:
            row = self._storage.commit_revision(
                scenario_id=scenario_id,
                revision_id=self._id_factory("revision"),
                expected_generation=generation,
                expected_payload=payload,
                schema_version=schema_version,
                canonical_digest=canonical_digest(draft.content),
                provenance_payload=canonical_bytes(provenance),
                created_at=timestamp,
            )
        except KeyError as error:
            self._unknown_scenario(error)
        except StorageDraftConflict as error:
            raise DraftConflictError("draft generation conflict") from error
        except StorageArchived as error:
            raise ArchivedScenarioError("scenario is archived") from error
        return self._revision(row)

    def get_revision(self, revision_id: str) -> ScenarioRevision:
        try:
            return self._revision(self._storage.read_revision(revision_id))
        except KeyError as error:
            raise UnknownRevisionError("unknown revision") from error

    def history(self, scenario_id: str) -> tuple[ScenarioRevision, ...]:
        self.get_draft(scenario_id)
        return tuple(
            self._revision(row) for row in self._storage.revisions(scenario_id)
        )

    def latest_revision(self, scenario_id: str) -> ScenarioRevision | None:
        try:
            row = self._storage.latest_revision(scenario_id)
        except KeyError as error:
            self._unknown_scenario(error)
        return None if row is None else self._revision(row)

    def list_scenarios(
        self,
        *,
        include_archived: bool = False,
    ) -> tuple[ScenarioSummary, ...]:
        return tuple(
            ScenarioSummary(
                scenario_id=str(row["scenario_id"]),
                schema_version=str(row["schema_version"]),
                draft_generation=int(row["draft_generation"]),
                latest_revision_id=(
                    None
                    if row["latest_revision_id"] is None
                    else str(row["latest_revision_id"])
                ),
                archived=bool(row["archived"]),
                provenance=freeze_json(
                    _decode_mapping(row["provenance_payload"])
                ),
            )
            for row in self._storage.list_scenarios(
                include_archived=include_archived
            )
        )

    def archive_scenario(
        self,
        scenario_id: str,
        *,
        actor: str = "local_operator",
    ) -> ArchiveTombstone:
        timestamp = self._clock()
        provenance = {
            "kind": "scenario_archive",
            "actor": self._actor(actor),
            "created_at": timestamp,
        }
        try:
            row = self._storage.archive(
                scenario_id=scenario_id,
                tombstone_id=self._id_factory("tombstone"),
                archived_at=timestamp,
                provenance_payload=canonical_bytes(provenance),
            )
        except KeyError as error:
            self._unknown_scenario(error)
        return self._tombstone(row)

    def tombstones(self, scenario_id: str) -> tuple[ArchiveTombstone, ...]:
        self.get_draft(scenario_id)
        return tuple(
            self._tombstone(row) for row in self._storage.tombstones(scenario_id)
        )

    def fork_preset(
        self,
        template_id: str,
        edited_content: Mapping[str, Any] | None = None,
        *,
        actor: str = "local_operator",
    ) -> ScenarioRevision:
        actor = self._actor(actor)
        template = self._presets.get(template_id)
        content = (
            self._presets.editable_copy(template_id)
            if edited_content is None
            else edited_content
        )
        _, schema_version, payload = _document(content)
        timestamp = self._clock()
        draft_provenance = {
            "kind": "preset_fork",
            "actor": actor,
            "created_at": timestamp,
            "template_id": template.template_id,
            "template_digest": template.template_digest,
        }
        revision_provenance = {
            **draft_provenance,
            "draft_generation": 0,
        }
        row = self._storage.create_fork(
            scenario_id=self._id_factory("scenario"),
            revision_id=self._id_factory("revision"),
            payload=payload,
            schema_version=schema_version,
            canonical_digest=canonical_digest(content),
            draft_provenance_payload=canonical_bytes(draft_provenance),
            revision_provenance_payload=canonical_bytes(revision_provenance),
            created_at=timestamp,
        )
        return self._revision(row)

    @staticmethod
    def overwrite_revision(revision_id: str, content: object) -> Never:
        raise ImmutableRevisionError("revisions are append-only")

    @staticmethod
    def delete_revision(revision_id: str) -> Never:
        raise ImmutableRevisionError("revisions are append-only")

    @staticmethod
    def delete_scenario(scenario_id: str) -> Never:
        raise ImmutableRevisionError("scenarios cannot be hard-deleted")


Revision = ScenarioRevision


__all__ = [
    "ArchiveTombstone",
    "ArchivedScenarioError",
    "DraftConflictError",
    "DraftSnapshot",
    "ImmutableRevisionError",
    "InvalidDraftError",
    "LibraryError",
    "LocalScenarioLibrary",
    "Revision",
    "ScenarioRevision",
    "ScenarioSummary",
    "UnknownRevisionError",
    "UnknownScenarioError",
]
