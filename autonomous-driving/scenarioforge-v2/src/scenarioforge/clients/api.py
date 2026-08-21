from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, TypeVar

from scenarioforge import __version__
from scenarioforge.application import ApplicationError, ScenarioForgeApplication
from scenarioforge.core.canonical import JSONValue, freeze_json, thaw_json
from scenarioforge.orchestration import (
    ExperimentDefinition,
    ExperimentService,
    ExperimentStore,
    ScenarioForgeRunnerFactory,
)
from scenarioforge.repro import P0MatrixSpec, regression_contract


_T = TypeVar("_T")


@dataclass(frozen=True)
class ClientResponse:
    operation: str
    payload: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        frozen = freeze_json(self.payload)
        if not isinstance(frozen, Mapping):
            raise TypeError("client payload must be an object")
        object.__setattr__(self, "payload", MappingProxyType(dict(frozen)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "scenarioforge.client-response/v1",
            "operation": self.operation,
            "payload": thaw_json(self.payload),
        }


class ScenarioForgeClientError(RuntimeError):
    def __init__(self, *, operation: str, code: str, message: str) -> None:
        super().__init__(message)
        self.operation = operation
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": "scenarioforge.client-error/v1",
            "operation": self.operation,
            "code": self.code,
            "message": self.message,
        }


class ScenarioForgeClient:
    """Typed non-Web facade over ScenarioForge's canonical local services."""

    def __init__(self, *, project_root: Path | str, workspace: Path | str) -> None:
        self._project_root = Path(project_root)
        self._workspace = Path(workspace)
        self._application = ScenarioForgeApplication(
            project_root=self._project_root,
            workspace=self._workspace / "runs",
        )
        self._experiments = ExperimentService(
            store=ExperimentStore(self._workspace / "experiments"),
            runner_factory=ScenarioForgeRunnerFactory(
                project_root=self._project_root,
                workspace=self._workspace / "runs",
            ),
        )

    @staticmethod
    def _response(operation: str, payload: Mapping[str, Any]) -> ClientResponse:
        return ClientResponse(operation=operation, payload=payload)

    @staticmethod
    def _translate(operation: str, callback: Callable[[], _T]) -> _T:
        try:
            return callback()
        except ScenarioForgeClientError:
            raise
        except ApplicationError as error:
            code = (
                "scenario_input_invalid"
                if error.stage == "input"
                else "scenario_preflight_failed"
            )
            message = (
                "scenario input failed closed"
                if error.stage == "input"
                else "scenario preflight failed closed"
            )
            raise ScenarioForgeClientError(
                operation=operation,
                code=code,
                message=message,
            ) from error
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            raise ScenarioForgeClientError(
                operation=operation,
                code="client_request_invalid",
                message=f"{operation} request failed closed",
            ) from error

    def health(self) -> ClientResponse:
        return self._response(
            "health",
            {
                "schema_version": "scenarioforge.client-health/v1",
                "package": "scenarioforge",
                "version": __version__,
                "transport": "local-no-web",
                "capabilities": [
                    "validation",
                    "preflight",
                    "control",
                    "batch",
                    "recovery",
                    "query",
                    "comparison",
                ],
            },
        )

    def validate(self, scenario: Path | str) -> ClientResponse:
        def execute() -> ClientResponse:
            prepared = self._application.prepare(scenario).to_dict()
            return self._response(
                "validate",
                {
                    "schema_version": "scenarioforge.client-validation/v1",
                    "valid": bool(prepared["executable"]),
                    "status": prepared["status"],
                    "scenario_instance_digest": prepared["scenario_instance_digest"],
                    "compile_report_digest": prepared["compile_report_digest"],
                    "execution_plan_digest": prepared["execution_plan_digest"],
                },
            )

        return self._translate("validate", execute)

    def preflight(self, scenario: Path | str) -> ClientResponse:
        def execute() -> ClientResponse:
            prepared = self._application.prepare(scenario).to_dict()
            return self._response(
                "preflight",
                {
                    "schema_version": "scenarioforge.client-preflight/v1",
                    "status": prepared["status"],
                    "executable": prepared["executable"],
                    "scenario_instance_digest": prepared["scenario_instance_digest"],
                    "compile_report_digest": prepared["compile_report_digest"],
                    "execution_plan_digest": prepared["execution_plan_digest"],
                },
            )

        return self._translate("preflight", execute)

    def submit_experiment(
        self,
        definition: Mapping[str, object],
        *,
        idempotency_key: str,
    ) -> ClientResponse:
        return self._translate(
            "submit_experiment",
            lambda: self._response(
                "submit_experiment",
                self._experiments.submit(
                    ExperimentDefinition.from_mapping(definition),
                    idempotency_key=idempotency_key,
                ),
            ),
        )

    def list_experiments(self) -> ClientResponse:
        return self._translate(
            "list_experiments",
            lambda: self._response("list_experiments", self._experiments.list()),
        )

    def get_experiment(self, experiment_id: str) -> ClientResponse:
        return self._translate(
            "get_experiment",
            lambda: self._response(
                "get_experiment", self._experiments.get(experiment_id)
            ),
        )

    def control_experiment(
        self,
        experiment_id: str,
        operation: str,
        *,
        command_id: str,
    ) -> ClientResponse:
        return self._translate(
            "control_experiment",
            lambda: self._response(
                "control_experiment",
                self._experiments.control(
                    experiment_id,
                    operation,
                    command_id=command_id,
                ),
            ),
        )

    def recover_experiments(self) -> ClientResponse:
        def execute() -> ClientResponse:
            self._experiments.recover()
            return self._response("recover_experiments", self._experiments.list())

        return self._translate("recover_experiments", execute)

    def comparison_contract(self) -> ClientResponse:
        return self._response(
            "comparison_contract",
            {
                "schema_version": "scenarioforge.client-comparison-contract/v1",
                "matrix": P0MatrixSpec.p0().to_dict(),
                "regression": regression_contract(),
            },
        )
