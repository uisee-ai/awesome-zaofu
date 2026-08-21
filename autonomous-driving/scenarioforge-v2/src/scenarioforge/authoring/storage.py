from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class StorageDraftConflict(RuntimeError):
    pass


class StorageArchived(RuntimeError):
    pass


class StorageIdentifierCollision(RuntimeError):
    pass


class SQLiteLibraryStorage:
    """SQLite persistence for atomic, append-only local scenario revisions."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._fault_injector = fault_injector
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scenarios (
                    scenario_id TEXT PRIMARY KEY,
                    draft_payload BLOB NOT NULL,
                    draft_generation INTEGER NOT NULL CHECK (draft_generation >= 0),
                    schema_version TEXT NOT NULL,
                    provenance_payload BLOB NOT NULL,
                    latest_revision_id TEXT,
                    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
                    parent_revision_id TEXT REFERENCES revisions(revision_id),
                    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
                    schema_version TEXT NOT NULL,
                    canonical_digest TEXT NOT NULL,
                    canonical_payload BLOB NOT NULL,
                    provenance_payload BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (scenario_id, revision_number)
                );

                CREATE INDEX IF NOT EXISTS revisions_by_scenario
                ON revisions(scenario_id, revision_number);

                CREATE TABLE IF NOT EXISTS tombstones (
                    tombstone_id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id),
                    latest_revision_id TEXT,
                    archived_at TEXT NOT NULL,
                    provenance_payload BLOB NOT NULL
                );

                CREATE INDEX IF NOT EXISTS tombstones_by_scenario
                ON tombstones(scenario_id, archived_at);

                CREATE TRIGGER IF NOT EXISTS revisions_are_not_updated
                BEFORE UPDATE ON revisions
                BEGIN
                    SELECT RAISE(ABORT, 'immutable revision');
                END;

                CREATE TRIGGER IF NOT EXISTS revisions_are_not_deleted
                BEFORE DELETE ON revisions
                BEGIN
                    SELECT RAISE(ABORT, 'immutable revision');
                END;

                CREATE TRIGGER IF NOT EXISTS tombstones_are_not_updated
                BEFORE UPDATE ON tombstones
                BEGIN
                    SELECT RAISE(ABORT, 'immutable tombstone');
                END;

                CREATE TRIGGER IF NOT EXISTS tombstones_are_not_deleted
                BEFORE DELETE ON tombstones
                BEGIN
                    SELECT RAISE(ABORT, 'immutable tombstone');
                END;
                """
            )
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _fault(self, stage: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(stage)

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise KeyError("record not found")
        return dict(row)

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        statement: str,
        parameters: tuple[object, ...],
    ) -> None:
        try:
            connection.execute(statement, parameters)
        except sqlite3.IntegrityError as error:
            raise StorageIdentifierCollision("identifier collision") from error

    def create_draft(
        self,
        *,
        scenario_id: str,
        payload: bytes,
        schema_version: str,
        provenance_payload: bytes,
        created_at: str,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            self._insert(
                connection,
                """
                INSERT INTO scenarios (
                    scenario_id, draft_payload, draft_generation, schema_version,
                    provenance_payload, latest_revision_id, archived, created_at
                ) VALUES (?, ?, 0, ?, ?, NULL, 0, ?)
                """,
                (
                    scenario_id,
                    payload,
                    schema_version,
                    provenance_payload,
                    created_at,
                ),
            )
        return self.read_draft(scenario_id)

    def read_draft(self, scenario_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM scenarios WHERE scenario_id = ?",
                (scenario_id,),
            ).fetchone()
            return self._row(row)
        finally:
            connection.close()

    def update_draft(
        self,
        *,
        scenario_id: str,
        payload: bytes,
        schema_version: str,
        expected_generation: int,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            current = self._row(
                connection.execute(
                    "SELECT * FROM scenarios WHERE scenario_id = ?",
                    (scenario_id,),
                ).fetchone()
            )
            if bool(current["archived"]):
                raise StorageArchived("scenario is archived")
            if int(current["draft_generation"]) != expected_generation:
                raise StorageDraftConflict("draft generation conflict")
            connection.execute(
                """
                UPDATE scenarios
                SET draft_payload = ?, schema_version = ?, draft_generation = ?
                WHERE scenario_id = ?
                """,
                (
                    payload,
                    schema_version,
                    expected_generation + 1,
                    scenario_id,
                ),
            )
        return self.read_draft(scenario_id)

    def commit_revision(
        self,
        *,
        scenario_id: str,
        revision_id: str,
        expected_generation: int,
        expected_payload: bytes,
        schema_version: str,
        canonical_digest: str,
        provenance_payload: bytes,
        created_at: str,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            scenario = self._row(
                connection.execute(
                    "SELECT * FROM scenarios WHERE scenario_id = ?",
                    (scenario_id,),
                ).fetchone()
            )
            if bool(scenario["archived"]):
                raise StorageArchived("scenario is archived")
            if (
                int(scenario["draft_generation"]) != expected_generation
                or bytes(scenario["draft_payload"]) != expected_payload
            ):
                raise StorageDraftConflict("draft generation conflict")
            parent_revision_id = scenario["latest_revision_id"]
            revision_number = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(revision_number), 0) + 1
                    FROM revisions WHERE scenario_id = ?
                    """,
                    (scenario_id,),
                ).fetchone()[0]
            )
            self._insert(
                connection,
                """
                INSERT INTO revisions (
                    revision_id, scenario_id, parent_revision_id, revision_number,
                    schema_version, canonical_digest, canonical_payload,
                    provenance_payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    scenario_id,
                    parent_revision_id,
                    revision_number,
                    schema_version,
                    canonical_digest,
                    expected_payload,
                    provenance_payload,
                    created_at,
                ),
            )
            self._fault("after_revision_insert")
            connection.execute(
                "UPDATE scenarios SET latest_revision_id = ? WHERE scenario_id = ?",
                (revision_id, scenario_id),
            )
            self._fault("after_latest_update")
            row = connection.execute(
                "SELECT * FROM revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()
            return self._row(row)

    def create_fork(
        self,
        *,
        scenario_id: str,
        revision_id: str,
        payload: bytes,
        schema_version: str,
        canonical_digest: str,
        draft_provenance_payload: bytes,
        revision_provenance_payload: bytes,
        created_at: str,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            self._insert(
                connection,
                """
                INSERT INTO scenarios (
                    scenario_id, draft_payload, draft_generation, schema_version,
                    provenance_payload, latest_revision_id, archived, created_at
                ) VALUES (?, ?, 0, ?, ?, NULL, 0, ?)
                """,
                (
                    scenario_id,
                    payload,
                    schema_version,
                    draft_provenance_payload,
                    created_at,
                ),
            )
            self._insert(
                connection,
                """
                INSERT INTO revisions (
                    revision_id, scenario_id, parent_revision_id, revision_number,
                    schema_version, canonical_digest, canonical_payload,
                    provenance_payload, created_at
                ) VALUES (?, ?, NULL, 1, ?, ?, ?, ?, ?)
                """,
                (
                    revision_id,
                    scenario_id,
                    schema_version,
                    canonical_digest,
                    payload,
                    revision_provenance_payload,
                    created_at,
                ),
            )
            self._fault("after_revision_insert")
            connection.execute(
                "UPDATE scenarios SET latest_revision_id = ? WHERE scenario_id = ?",
                (revision_id, scenario_id),
            )
            self._fault("after_latest_update")
            row = connection.execute(
                "SELECT * FROM revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()
            return self._row(row)

    def read_revision(self, revision_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            return self._row(
                connection.execute(
                    "SELECT * FROM revisions WHERE revision_id = ?",
                    (revision_id,),
                ).fetchone()
            )
        finally:
            connection.close()

    def revisions(self, scenario_id: str) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM revisions
                WHERE scenario_id = ? ORDER BY revision_number
                """,
                (scenario_id,),
            ).fetchall()
            return tuple(dict(row) for row in rows)
        finally:
            connection.close()

    def latest_revision(self, scenario_id: str) -> dict[str, Any] | None:
        draft = self.read_draft(scenario_id)
        revision_id = draft["latest_revision_id"]
        return None if revision_id is None else self.read_revision(str(revision_id))

    def archive(
        self,
        *,
        scenario_id: str,
        tombstone_id: str,
        archived_at: str,
        provenance_payload: bytes,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            scenario = self._row(
                connection.execute(
                    "SELECT * FROM scenarios WHERE scenario_id = ?",
                    (scenario_id,),
                ).fetchone()
            )
            if bool(scenario["archived"]):
                return self._row(
                    connection.execute(
                        """
                        SELECT * FROM tombstones WHERE scenario_id = ?
                        ORDER BY rowid DESC LIMIT 1
                        """,
                        (scenario_id,),
                    ).fetchone()
                )
            self._insert(
                connection,
                """
                INSERT INTO tombstones (
                    tombstone_id, scenario_id, latest_revision_id,
                    archived_at, provenance_payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tombstone_id,
                    scenario_id,
                    scenario["latest_revision_id"],
                    archived_at,
                    provenance_payload,
                ),
            )
            self._fault("after_tombstone_insert")
            connection.execute(
                "UPDATE scenarios SET archived = 1 WHERE scenario_id = ?",
                (scenario_id,),
            )
            self._fault("after_archive_update")
            return self._row(
                connection.execute(
                    "SELECT * FROM tombstones WHERE tombstone_id = ?",
                    (tombstone_id,),
                ).fetchone()
            )

    def list_scenarios(
        self,
        *,
        include_archived: bool,
    ) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            if include_archived:
                rows = connection.execute(
                    "SELECT * FROM scenarios ORDER BY rowid"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM scenarios WHERE archived = 0 ORDER BY rowid"
                ).fetchall()
            return tuple(dict(row) for row in rows)
        finally:
            connection.close()

    def tombstones(self, scenario_id: str) -> tuple[dict[str, Any], ...]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM tombstones
                WHERE scenario_id = ? ORDER BY rowid
                """,
                (scenario_id,),
            ).fetchall()
            return tuple(dict(row) for row in rows)
        finally:
            connection.close()


__all__ = [
    "SQLiteLibraryStorage",
    "StorageArchived",
    "StorageDraftConflict",
    "StorageIdentifierCollision",
]
