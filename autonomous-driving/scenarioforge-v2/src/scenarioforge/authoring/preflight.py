from __future__ import annotations

from dataclasses import dataclass

from scenarioforge.core.models import (
    CapabilityDescriptor,
    CompilationStatus,
    CompileBundle,
    CompileReport,
    ScenarioInstance,
)
from scenarioforge.core.compiler import ScenarioCompiler

from .library import ScenarioRevision


@dataclass(frozen=True)
class PreflightResult:
    revision: ScenarioRevision
    capabilities: CapabilityDescriptor
    bundle: CompileBundle

    @property
    def scenario_instance(self) -> ScenarioInstance:
        return self.bundle.scenario_instance

    @property
    def report(self) -> CompileReport:
        return self.bundle.report

    @property
    def status(self) -> CompilationStatus:
        return self.report.overall_status

    @property
    def executable(self) -> bool:
        return self.status is CompilationStatus.EXACT and self.bundle.execution_plan is not None

    @property
    def requires_confirmation(self) -> bool:
        return self.status is CompilationStatus.LOSSY


def preflight_revision(
    revision: ScenarioRevision,
    *,
    compiler: ScenarioCompiler | None = None,
) -> PreflightResult:
    capabilities, bundle = (compiler or ScenarioCompiler()).compile_revision(revision)
    return PreflightResult(revision=revision, capabilities=capabilities, bundle=bundle)


class PreflightService:
    def __init__(self, compiler: ScenarioCompiler | None = None) -> None:
        self.compiler = compiler or ScenarioCompiler()

    def evaluate(self, revision: ScenarioRevision) -> PreflightResult:
        return preflight_revision(revision, compiler=self.compiler)


__all__ = ["PreflightResult", "PreflightService", "preflight_revision"]
