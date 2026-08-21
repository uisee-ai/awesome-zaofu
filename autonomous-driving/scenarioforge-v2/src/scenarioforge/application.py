from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from scenarioforge.core import ScenarioCompiler, instantiate_scenario
from scenarioforge.core.models import CompileBundle, ScenarioDocument, ScenarioInstance
from scenarioforge.failsafe import (
    FailureController,
    FailureKind,
    FailureOutcome,
)
from scenarioforge.repro import ReproducibilityRunner, ReproductionOutcome
from scenarioforge.runtime import (
    CandidateContractError,
    P1CandidateContract,
    RunSupervisor,
    freeze_candidate,
)
from scenarioforge.runtime.contracts import PreparedRun, RunOutcome
from scenarioforge.security import SecurityViolation, load_untrusted_scenario


P0A_ACCEPTANCE_IDS = tuple(f"AC-A{index:02d}" for index in range(1, 29))
P0A_GATES = (
    "Contract",
    "Functional",
    "Evidence",
    "Security",
    "Traceability",
    "Delivery",
)
P0A_EXCLUSIONS = (
    "web",
    "non_strict_json",
    "batch_queue_concurrency_service",
    "other_scenario_families",
    "remote_upload_external_assets_user_code",
    "lossy_execution_override",
    "action_replay_as_reexecution",
    "cancelled_terminal",
    "non_linux_x86_64_formal_support",
    "smarts_natural_language_failure_search_cross_backend",
    "cross_platform_bitwise_float_identity",
)


@dataclass(frozen=True)
class DecisionTrace:
    decision_id: str
    conclusion: str
    prd_sections: tuple[str, ...]
    acceptance_ids: tuple[str, ...]
    deliverables: tuple[str, ...]
    gates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "conclusion": self.conclusion,
            "prd_sections": list(self.prd_sections),
            "acceptance_ids": list(self.acceptance_ids),
            "deliverables": list(self.deliverables),
            "gates": list(self.gates),
        }


P0A_OWNER_DECISIONS = (
    DecisionTrace(
        "q-fd5532646da41a1b",
        "minimal semantic core with versioned extensions",
        ("7.4",),
        ("AC-A03", "AC-A04", "AC-A05"),
        ("ScenarioSpec schema", "ScenarioInstance"),
        ("Contract", "Traceability"),
    ),
    DecisionTrace(
        "q-b9a68eb19cf9d5d7",
        "P0-A accepts strict JSON only",
        ("7.3",),
        ("AC-A01", "AC-A02"),
        ("strict parser", "schema", "canonicalization contract"),
        ("Functional", "Security"),
    ),
    DecisionTrace(
        "q-1f62d2875d7a507d",
        "local single-user execution without remote code or external assets",
        ("7.2", "7.8"),
        ("AC-A01", "AC-A13", "AC-A25", "AC-A26"),
        ("local reader", "supervisor", "single-run Worker"),
        ("Security",),
    ),
    DecisionTrace(
        "q-06bf8b7b24e8b376",
        "isolated single-run Worker without queue or task service",
        ("7.8", "7.11"),
        tuple(f"AC-A{index:02d}" for index in range(9, 19)),
        (
            "InputSnapshot",
            "OutputStaging",
            "RunRequest",
            "RunManifest",
            "RunResult",
            "ArtifactIndex",
        ),
        ("Contract", "Functional"),
    ),
    DecisionTrace(
        "q-4e49e2d39be43aab",
        "locked Linux x86_64 headless environment without required GPU",
        ("7.1",),
        ("AC-A12", "AC-A25"),
        ("pyproject.toml", "uv.lock", "environment evidence"),
        ("Functional", "Security"),
    ),
    DecisionTrace(
        "q-947977490d83a9a8",
        "exact-only execution; lossy and unsupported compilation stop",
        ("7.7",),
        tuple(f"AC-A{index:02d}" for index in range(5, 9)),
        ("CapabilityDescriptor", "CompileBundle"),
        ("Contract", "Functional"),
    ),
    DecisionTrace(
        "q-0b996f96d7a507d",
        "bounded two-lane lead-vehicle braking scenario family",
        ("7.5", "7.9"),
        ("AC-A14", "AC-A19", "AC-A20"),
        ("scenario examples", "tick trigger contract"),
        ("Functional", "Evidence"),
    ),
    DecisionTrace(
        "q-6c26f9bf133a60f4",
        "reproduction re-executes the fixed policy; actions are evidence only",
        ("7.6",),
        ("AC-A21",),
        ("fixed policy", "action artifacts"),
        ("Functional", "Evidence"),
    ),
    DecisionTrace(
        "q-cd430e98a506881a",
        "three independent runs use approved field tolerances",
        ("7.12",),
        ("AC-A18", "AC-A22", "AC-A23", "AC-A24"),
        ("comparison report", "trajectory comparator"),
        ("Evidence",),
    ),
)


@dataclass(frozen=True)
class AcceptanceTrace:
    acceptance_id: str
    prd_anchor: str
    task_id: str
    deliverables: tuple[str, ...]
    gates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptance_id": self.acceptance_id,
            "prd_anchor": self.prd_anchor,
            "task_id": self.task_id,
            "deliverables": list(self.deliverables),
            "gates": list(self.gates),
        }


_S1 = "TASK-AC1AF4-S1-HAPPY"
_S2 = "TASK-AC1AF4-S2-FAILSAFE"
_S3 = "TASK-AC1AF4-S3-REPRO"
_S4 = "TASK-AC1AF4-S4-DELIVERY"

P0A_ACCEPTANCE_TRACE = (
    AcceptanceTrace("AC-A01", "AC-A01-local-json-boundary", _S1, ("strict_json.py",), ("Functional", "Security")),
    AcceptanceTrace("AC-A02", "AC-A02-strict-parse-pipeline", _S1, ("strict_json.py", "schema.py"), ("Contract", "Functional", "Security")),
    AcceptanceTrace("AC-A03", "AC-A03-instantiation", _S1, ("models.py", "strict_json.py"), ("Contract", "Functional")),
    AcceptanceTrace("AC-A04", "AC-A04-extension-boundary", _S1, ("schema.py", "compiler.py"), ("Contract", "Security")),
    AcceptanceTrace("AC-A05", "AC-A05-minimal-core", _S1, ("brake_lead.json", "compiler.py"), ("Contract", "Functional")),
    AcceptanceTrace("AC-A06", "AC-A06-compile-bundle", _S1, ("compiler.py", "models.py"), ("Contract", "Functional")),
    AcceptanceTrace("AC-A07", "AC-A07-preflight-process-boundary", _S1, ("compiler.py", "supervisor.py"), ("Contract", "Security")),
    AcceptanceTrace("AC-A08", "AC-A08-capability-diagnostics", _S1, ("compiler.py",), ("Contract", "Functional")),
    AcceptanceTrace("AC-A09", "AC-A09-input-snapshot-manifest", _S1, ("snapshot.py",), ("Contract", "Functional", "Evidence", "Security")),
    AcceptanceTrace("AC-A10", "AC-A10-request-binding", _S1, ("contracts.py", "snapshot.py"), ("Contract", "Functional")),
    AcceptanceTrace("AC-A11", "AC-A11-worker-binding", _S1, ("worker_entry.py",), ("Functional", "Security")),
    AcceptanceTrace("AC-A12", "AC-A12-formal-environment", _S1, ("pyproject.toml", "uv.lock", "environment.md"), ("Functional", "Security")),
    AcceptanceTrace("AC-A13", "AC-A13-runtime-isolation", _S1, ("supervisor.py", "worker_entry.py"), ("Functional", "Security")),
    AcceptanceTrace("AC-A14", "AC-A14-tick-priority", _S1, ("policy.py", "happy-path.md"), ("Contract", "Evidence")),
    AcceptanceTrace("AC-A15", "AC-A15-success-publication", _S1, ("artifact_publish.py",), ("Evidence", "Security")),
    AcceptanceTrace("AC-A16", "AC-A16-failure-publication", _S2, ("failsafe/supervisor.py", "failsafe/publisher.py"), ("Functional", "Evidence", "Security")),
    AcceptanceTrace("AC-A17", "AC-A17-minimum-failure-evidence", _S2, ("failure-security.md",), ("Evidence", "Traceability")),
    AcceptanceTrace("AC-A18", "AC-A18-terminal-run-identity", _S2, ("failsafe/contracts.py",), ("Contract", "Evidence")),
    AcceptanceTrace("AC-A19", "AC-A19-scenario-semantics", _S1, ("brake_lead.json", "adapter.py"), ("Functional", "Evidence")),
    AcceptanceTrace("AC-A20", "AC-A20-seed-counterfactual", _S3, ("seed.py", "counterfactual.py"), ("Evidence",)),
    AcceptanceTrace("AC-A21", "AC-A21-policy-reexecution", _S3, ("repro/runner.py", "policy.py"), ("Functional", "Evidence")),
    AcceptanceTrace("AC-A22", "AC-A22-discrete-consistency", _S3, ("comparison.py",), ("Evidence",)),
    AcceptanceTrace("AC-A23", "AC-A23-trajectory-tolerances", _S3, ("comparison.py", "tolerance_profile.json"), ("Contract", "Evidence")),
    AcceptanceTrace("AC-A24", "AC-A24-comparison-report", _S3, ("comparison.py", "reproducibility.md"), ("Evidence", "Traceability")),
    AcceptanceTrace("AC-A25", "AC-A25-security-negatives", _S2, ("security/", "test_security_boundaries.py"), ("Security",)),
    AcceptanceTrace("AC-A26", "AC-A26-public-boundary", _S1, ("core/models.py", "runtime/contracts.py"), ("Contract", "Security")),
    AcceptanceTrace("AC-A27", "AC-A27-contract-traceability", _S4, ("traceability.md", "application.py"), ("Traceability", "Delivery")),
    AcceptanceTrace("AC-A28", "AC-A28-root-verification", _S4, ("delivery.md", "python -m pytest -q"), ("Delivery",)),
)


@dataclass(frozen=True)
class DeliveryManifest:
    schema_version: str
    owner_decisions: tuple[DecisionTrace, ...]
    acceptance_trace: tuple[AcceptanceTrace, ...]
    gate_evidence: Mapping[str, tuple[str, ...]]
    task_slices: tuple[Mapping[str, object], ...]
    exclusions: tuple[str, ...]
    root_verification_command: str
    completion_authority: str
    child_completion_claim: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "owner_decisions": [item.to_dict() for item in self.owner_decisions],
            "acceptance_ids": [item.acceptance_id for item in self.acceptance_trace],
            "acceptance_trace": [item.to_dict() for item in self.acceptance_trace],
            "gate_evidence": {
                gate: list(self.gate_evidence[gate]) for gate in P0A_GATES
            },
            "task_slices": [dict(item) for item in self.task_slices],
            "exclusions": list(self.exclusions),
            "root_verification_command": self.root_verification_command,
            "completion_authority": self.completion_authority,
            "child_completion_claim": self.child_completion_claim,
        }


P0A_DELIVERY_MANIFEST = DeliveryManifest(
    schema_version="scenarioforge.delivery-manifest/v1",
    owner_decisions=P0A_OWNER_DECISIONS,
    acceptance_trace=P0A_ACCEPTANCE_TRACE,
    gate_evidence={
        "Contract": (
            "src/scenarioforge/core/",
            "src/scenarioforge/runtime/contracts.py",
            "tests/test_strict_json.py",
            "tests/test_p0a_happy_path.py",
        ),
        "Functional": (
            "tests/test_p0a_happy_path.py",
            "tests/test_failure_terminals.py",
            "tests/test_reproducibility.py",
        ),
        "Evidence": (
            "docs/evidence/happy-path.md",
            "docs/evidence/failure-security.md",
            "docs/evidence/reproducibility.md",
        ),
        "Security": (
            "src/scenarioforge/security/",
            "tests/test_security_boundaries.py",
            "docs/evidence/failure-security.md",
        ),
        "Traceability": (
            "tests/test_contract_traceability.py",
            "docs/evidence/traceability.md",
        ),
        "Delivery": (
            "command:python -m pytest -q",
            "docs/evidence/delivery.md",
            "event:dev.build.done",
        ),
    },
    task_slices=(
        {
            "task_id": _S1,
            "task_ref": "task/TASK-AC1AF4-S1-HAPPY",
            "source_commit": "7c5eb7ea3ca45431917830f89eb3d58a2e17a63d",
            "acceptance_range": "AC-A01..AC-A15,AC-A19,AC-A26",
        },
        {
            "task_id": _S2,
            "task_ref": "task/TASK-AC1AF4-S2-FAILSAFE",
            "source_commit": "90edb4aa8e60ad6a36c62dbf3ad7595612fec06a",
            "acceptance_range": "AC-A16..AC-A18,AC-A25",
        },
        {
            "task_id": _S3,
            "task_ref": "task/TASK-AC1AF4-S3-REPRO",
            "source_commit": "6b2e2940bbeb526ee514683cee143b97b8417b55",
            "acceptance_range": "AC-A20..AC-A24",
        },
        {
            "task_id": _S4,
            "task_ref": "task/TASK-AC1AF4-S4-DELIVERY",
            "source_commit": "bound_by_dev.build.done",
            "acceptance_range": "AC-A27..AC-A28",
        },
    ),
    exclusions=P0A_EXCLUSIONS,
    root_verification_command="python -m pytest -q",
    completion_authority="controlled_zf_workflow",
    child_completion_claim="task_slice_only",
)


class ApplicationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        code: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class PreparedScenario:
    document: ScenarioDocument
    scenario_instance: ScenarioInstance
    bundle: CompileBundle

    def to_dict(self) -> dict[str, object]:
        plan = self.bundle.execution_plan
        return {
            "schema_version": "scenarioforge.prepared-scenario/v1",
            "status": self.bundle.report.overall_status.value,
            "executable": self.bundle.report.executable,
            "scenario_instance_digest": self.scenario_instance.digest,
            "compile_report_digest": self.bundle.report.digest,
            "execution_plan_digest": None if plan is None else plan.digest,
        }


class ScenarioForgeApplication:
    """Final P0-A composition surface; release admission remains workflow-owned."""

    def __init__(self, *, workspace: Path, project_root: Path) -> None:
        self.workspace = Path(workspace)
        self.project_root = Path(project_root)
        self.compiler = ScenarioCompiler()
        self.failure_controller = FailureController(
            redacted_paths=(self.workspace, self.project_root),
        )
        self.run_supervisor = RunSupervisor(
            workspace=self.workspace,
            project_root=self.project_root,
            failure_controller=self.failure_controller,
        )
        self.reproducibility_runner = ReproducibilityRunner(
            workspace=self.workspace,
            project_root=self.project_root,
        )

    def prepare(self, scenario_path: Path | str) -> PreparedScenario:
        try:
            document = load_untrusted_scenario(scenario_path)
        except SecurityViolation as error:
            raise ApplicationError(
                "scenario input failed closed",
                stage="input",
                code=error.code,
            ) from error
        scenario_instance = instantiate_scenario(document)
        bundle = self.compiler.compile(scenario_instance)
        if not bundle.report.executable or bundle.execution_plan is None:
            raise ApplicationError(
                "scenario compilation is not all-exact",
                stage="compile",
                code="compile_not_exact",
                details={
                    "status": bundle.report.overall_status.value,
                    "diagnostics": [item.to_dict() for item in bundle.report.diagnostics],
                },
            )
        return PreparedScenario(
            document=document,
            scenario_instance=scenario_instance,
            bundle=bundle,
        )

    def run_single(
        self,
        scenario_path: Path | str,
        *,
        run_id: str,
        attempt_id: str,
        timeout_seconds: int,
    ) -> RunOutcome | FailureOutcome:
        prepared = self.prepare(scenario_path)
        return self.run_supervisor.run(
            prepared.bundle,
            run_id=run_id,
            attempt_id=attempt_id,
            timeout_seconds=timeout_seconds,
        )

    def interrupt_active_for_shutdown(self) -> bool:
        """Interrupt only for service shutdown, never as a client run control."""
        return self.run_supervisor.interrupt_active_for_shutdown()

    def candidate_contract(self, candidate_commit: str) -> P1CandidateContract:
        """Bind the release contract to this checkout's immutable HEAD."""
        try:
            return freeze_candidate(
                project_root=self.project_root,
                candidate_commit=candidate_commit,
            )
        except CandidateContractError as error:
            raise ApplicationError(
                "candidate contract is not bound to the current HEAD",
                stage="candidate",
                code="candidate_not_frozen",
            ) from error

    def run_three(
        self,
        scenario_path: Path | str,
        *,
        comparison_id: str,
        run_id_prefix: str,
        timeout_seconds: int,
    ) -> ReproductionOutcome:
        prepared = self.prepare(scenario_path)
        return self.reproducibility_runner.run_three(
            prepared.bundle,
            comparison_id=comparison_id,
            run_id_prefix=run_id_prefix,
            timeout_seconds=timeout_seconds,
        )

    def close_failure(
        self,
        prepared: PreparedRun,
        *,
        process: subprocess.Popen[object],
        kind: FailureKind,
        stage: str,
        worker_exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> FailureOutcome:
        return self.failure_controller.close(
            prepared,
            process=process,
            kind=kind,
            stage=stage,
            worker_exit_code=worker_exit_code,
            stdout=stdout,
            stderr=stderr,
        )


def application_error_payload(error: ApplicationError) -> dict[str, Any]:
    return {
        "schema_version": "scenarioforge.application-error/v1",
        "status": "failed",
        "stage": error.stage,
        "code": error.code,
        "details": error.details,
    }
