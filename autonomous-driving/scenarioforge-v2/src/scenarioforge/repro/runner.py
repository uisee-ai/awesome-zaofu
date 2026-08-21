from __future__ import annotations

from pathlib import Path

from scenarioforge.core.models import CompileBundle
from scenarioforge.runtime import RunSupervisor

from .comparison import compare_runs
from .contracts import ReproductionOutcome, ToleranceProfile


class ReproducibilityRunner:
    """Execute one immutable plan in three fresh single-run Worker processes."""

    def __init__(self, *, workspace: Path, project_root: Path) -> None:
        self.workspace = Path(workspace)
        self.project_root = Path(project_root)

    def run_three(
        self,
        bundle: CompileBundle,
        *,
        comparison_id: str,
        run_id_prefix: str,
        timeout_seconds: int,
        tolerances: ToleranceProfile | None = None,
    ) -> ReproductionOutcome:
        supervisor = RunSupervisor(workspace=self.workspace, project_root=self.project_root)
        runs = tuple(
            supervisor.run(
                bundle,
                run_id=f"{run_id_prefix}-{run_index:04d}",
                attempt_id="attempt-0001",
                timeout_seconds=timeout_seconds,
            )
            for run_index in range(1, 4)
        )
        report = compare_runs(comparison_id, runs, tolerances)
        return ReproductionOutcome(runs=runs, report=report)
