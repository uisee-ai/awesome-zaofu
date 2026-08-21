from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from scenarioforge.core import (
    CompilationStatus,
    ScenarioCompiler,
    canonical_bytes,
    environment_fingerprint,
    instantiate_scenario,
    load_scenario,
    strict_loads,
)
from scenarioforge.policies import trusted_policy_pair
from scenarioforge.runtime import RunSupervisor
from scenarioforge.runtime.contracts import RunOutcome

from .regression import (
    P0MatrixSpec,
    PolicyRunSample,
    RegressionContractError,
    RegressionMatrixReport,
    bind_regression_policy,
    build_regression_case,
    compare_policy_pair,
    compare_regression_matrix,
)


class P0RealMatrixRunner:
    """Execute the frozen 5x2x3 matrix through real Worker subprocesses."""

    def __init__(
        self,
        *,
        workspace: Path,
        project_root: Path,
        evidence_root: Path,
    ) -> None:
        self.workspace = Path(workspace)
        self.project_root = Path(project_root)
        self.evidence_root = Path(evidence_root)

    @staticmethod
    def _verify_real_outcome(outcome: RunOutcome) -> None:
        if (
            not outcome.worker_exited
            or outcome.worker_exit_code != 0
            or outcome.run_result.status != "success"
        ):
            raise RegressionContractError("real MetaDrive child did not publish success")
        worker_result = strict_loads(
            (outcome.published_path / "output" / "worker_result.json").read_bytes()
        )
        if not isinstance(worker_result, dict) or worker_result.get("backend") != {
            "distribution": "metadrive-simulator",
            "version": "0.4.3",
            "asset_version": "0.4.3",
            "engine_class": "MultiAgentMetaDrive",
        }:
            raise RegressionContractError("matrix child did not use real MetaDrive 0.4.3")

    def run(self) -> RegressionMatrixReport:
        spec = P0MatrixSpec.p0()
        fingerprint = environment_fingerprint(self.project_root / "uv.lock").to_dict()
        pairs = []
        for preset_id in spec.presets:
            document = load_scenario(
                self.project_root / "examples" / "p0c" / f"{preset_id}.json"
            )
            for seed in spec.seeds:
                instance = replace(instantiate_scenario(document), seed=seed)
                bundle = ScenarioCompiler().compile(instance)
                if (
                    bundle.report.overall_status is not CompilationStatus.EXACT
                    or not bundle.report.executable
                    or bundle.execution_plan is None
                ):
                    raise RegressionContractError(
                        f"matrix preset did not compile exactly: {preset_id}"
                    )
                case = build_regression_case(
                    bundle,
                    preset_id=preset_id,
                    environment_fingerprint=fingerprint,
                )
                bindings = trusted_policy_pair(bundle.execution_plan.policy["config"])
                supervisor = RunSupervisor(
                    workspace=self.workspace / case.case_id,
                    project_root=self.project_root,
                )
                samples = []
                for binding in bindings:
                    outcome = supervisor.run(
                        bind_regression_policy(bundle, binding),
                        run_id=f"run-{case.case_id}-{binding.role}",
                        attempt_id="attempt-0001",
                        timeout_seconds=120,
                    )
                    self._verify_real_outcome(outcome)
                    samples.append(PolicyRunSample.from_outcome(case, outcome))
                pairs.append(compare_policy_pair(case, samples[0], samples[1]))

        report = compare_regression_matrix(pairs, spec)
        self._publish(report)
        return report

    def _publish(self, report: RegressionMatrixReport) -> None:
        if self.evidence_root.is_symlink():
            raise RegressionContractError("matrix evidence root must not be a symlink")
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        destination = self.evidence_root / "matrix-report.json"
        descriptor = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o400,
        )
        try:
            payload = canonical_bytes(report.to_dict())
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short regression matrix report write")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        destination.chmod(0o444)
