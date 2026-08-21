from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from scenarioforge.core.models import CompilationStatus
from scenarioforge.runtime.confirmation import (
    ConfirmationError,
    LossyConfirmation,
    LossyConfirmationAuthority,
)

from .library import LocalScenarioLibrary, ScenarioRevision, UnknownRevisionError
from .preflight import PreflightResult, PreflightService


class Runner(Protocol):
    def run(
        self,
        bundle: Any,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: float,
    ) -> Any: ...


class SaveAndRunBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class SaveAndRunResult:
    revision: ScenarioRevision
    preflight: PreflightResult
    outcome: Any


class SaveAndRunService:
    def __init__(
        self,
        *,
        library: LocalScenarioLibrary,
        runner: Runner,
        preflight: PreflightService | None = None,
        confirmations: LossyConfirmationAuthority | None = None,
    ) -> None:
        self.library = library
        self.runner = runner
        self.preflight = preflight or PreflightService()
        self.confirmations = confirmations or LossyConfirmationAuthority()

    def save_and_run(
        self,
        scenario_id: str,
        *,
        expected_generation: int,
        run_id: str,
        attempt_id: str,
        timeout_seconds: float,
        confirmation: LossyConfirmation | None = None,
    ) -> SaveAndRunResult:
        revision = self.library.save_draft(
            scenario_id,
            expected_generation=expected_generation,
            actor="local_operator",
        )
        return self._run(
            revision,
            run_id=run_id,
            attempt_id=attempt_id,
            timeout_seconds=timeout_seconds,
            confirmation=confirmation,
        )

    def run_revision(
        self,
        revision_id: str,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: float,
        confirmation: LossyConfirmation | None = None,
    ) -> SaveAndRunResult:
        if not revision_id or revision_id == "latest":
            raise SaveAndRunBlocked("run requires an explicit immutable revision_id")
        try:
            revision = self.library.get_revision(revision_id)
        except UnknownRevisionError as error:
            raise SaveAndRunBlocked("run requires an explicit immutable revision_id") from error
        return self._run(
            revision,
            run_id=run_id,
            attempt_id=attempt_id,
            timeout_seconds=timeout_seconds,
            confirmation=confirmation,
        )

    def preflight_revision(self, revision_id: str) -> PreflightResult:
        return self.preflight.evaluate(self.library.get_revision(revision_id))

    def issue_lossy_confirmation(
        self,
        preflight: PreflightResult,
        *,
        run_id: str,
        attempt_id: str,
    ) -> LossyConfirmation:
        return self.confirmations.issue(
            preflight,
            run_id=run_id,
            attempt_id=attempt_id,
            actor="local_operator",
        )

    def _run(
        self,
        revision: ScenarioRevision,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: float,
        confirmation: LossyConfirmation | None,
    ) -> SaveAndRunResult:
        result = self.preflight.evaluate(revision)
        if result.status is CompilationStatus.UNSUPPORTED:
            raise SaveAndRunBlocked("unsupported preflight blocks execution")
        bundle = result.bundle
        if result.status is CompilationStatus.LOSSY:
            if confirmation is None:
                raise SaveAndRunBlocked("lossy preflight requires explicit confirmation")
            try:
                bundle = self.confirmations.consume(
                    confirmation,
                    preflight=result,
                    run_id=run_id,
                    attempt_id=attempt_id,
                )
            except ConfirmationError as error:
                raise SaveAndRunBlocked(str(error)) from error
        elif confirmation is not None:
            raise SaveAndRunBlocked("exact preflight does not accept a lossy confirmation")
        outcome = self.runner.run(
            bundle,
            run_id=run_id,
            attempt_id=attempt_id,
            timeout_seconds=timeout_seconds,
        )
        return SaveAndRunResult(revision=revision, preflight=result, outcome=outcome)


__all__ = ["SaveAndRunBlocked", "SaveAndRunResult", "SaveAndRunService"]
