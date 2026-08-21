from __future__ import annotations

from pathlib import Path
from typing import Callable

from scenarioforge.application import ScenarioForgeApplication
from scenarioforge.runtime.supervisor import RunSupervisor
from scenarioforge.web.catalog import registered_scenario_path

from .contracts import ExperimentJob, ExperimentManifest


class ScenarioForgeJobRunner:
    """Adapter from one immutable ExperimentJob to the real Worker supervisor."""

    def __init__(
        self,
        *,
        job: ExperimentJob,
        manifest: ExperimentManifest,
        workspace: Path,
        project_root: Path,
        cgroup_root: Path | None = None,
    ) -> None:
        self.job = job
        self.manifest = manifest
        self.workspace = Path(workspace)
        self.project_root = Path(project_root).resolve()
        scenario_id = job.parameters.get("scenario_id")
        if not isinstance(scenario_id, str):
            raise ValueError("ExperimentJob requires a scenario_id parameter")
        self.scenario_path = (
            self.project_root
            / registered_scenario_path(scenario_id, profile="p0c")
        ).resolve()
        self.scenario_path.relative_to(self.project_root)
        if self.scenario_path.is_symlink() or not self.scenario_path.is_file():
            raise ValueError("registered Experiment scenario is unavailable")
        self.application = ScenarioForgeApplication(
            workspace=self.workspace,
            project_root=self.project_root,
        )
        formal_release = manifest.inputs.get("formal_release", False)
        if not isinstance(formal_release, bool):
            raise ValueError("formal_release input must be boolean")
        if formal_release:
            selected_root = cgroup_root or Path("/sys/fs/cgroup/scenarioforge")
            self.application.run_supervisor = RunSupervisor(
                workspace=self.workspace,
                project_root=self.project_root,
                failure_controller=self.application.failure_controller,
                require_delegated_cgroup=True,
                cgroup_root=selected_root,
            )
        self._process_group_callback: Callable[[int], None] | None = None

    def bind_process_group(self, callback: Callable[[int], None]) -> None:
        self._process_group_callback = callback

    def run(self, *, attempt_id: str, timeout_seconds: int) -> object:
        prepared = self.application.prepare(self.scenario_path)
        return self.application.run_supervisor.run(
            prepared.bundle,
            run_id=self.job.logical_run_id,
            attempt_id=attempt_id,
            timeout_seconds=timeout_seconds,
            process_started=self._process_group_callback,
        )

    def pause(self) -> bool:
        return self.application.run_supervisor.pause_active()

    def resume(self) -> bool:
        return self.application.run_supervisor.resume_active()

    def step(self) -> bool:
        return self.application.run_supervisor.step_active()

    def cancel(self, *, command_id: str, reason: str) -> bool:
        return self.application.run_supervisor.cancel_active(
            command_id=command_id,
            operation="reset" if reason == "reset" else "stop",
            reason=reason,
        )


class ScenarioForgeRunnerFactory:
    def __init__(
        self,
        *,
        workspace: Path,
        project_root: Path,
        cgroup_root: Path | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.project_root = Path(project_root)
        self.cgroup_root = cgroup_root

    def __call__(
        self,
        job: ExperimentJob,
        manifest: ExperimentManifest,
    ) -> ScenarioForgeJobRunner:
        return ScenarioForgeJobRunner(
            job=job,
            manifest=manifest,
            workspace=self.workspace,
            project_root=self.project_root,
            cgroup_root=self.cgroup_root,
        )
