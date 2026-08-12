from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

import rfc8785
from pydantic import TypeAdapter, ValidationError

from scenarioforge.bundle import BundleIntegrityError, verify_bundle
from scenarioforge.compiler import CompiledBundle, compile_scenario
from scenarioforge.replay import load_replay_bundle
from scenarioforge.runtime import RunRecord, run_bundle
from scenarioforge.spec import RunRequest, ScenarioSpec

from .models import (
    ExactDifference,
    ExactReplayVerification,
    NumericDifference,
    ResimulationReport,
    ResimulationResult,
    SafetyEvidence,
    ToleranceProfile,
)


class CalibrationError(ValueError):
    pass


@dataclass(frozen=True)
class _BundleData:
    bundle_id: str
    manifest_digest: str
    compiled: CompiledBundle
    records: tuple[RunRecord, ...]
    safety_evidence: SafetyEvidence | None

    @property
    def ordered_seeds(self) -> tuple[int, ...]:
        return tuple(record.seed for record in self.records)

    @property
    def effective_config_digests(self) -> tuple[str, ...]:
        return tuple(record.effective_config_digest for record in self.records)


def _read_bundle(path: Path) -> _BundleData:
    manifest = verify_bundle(path)
    artifact_names = {artifact.path for artifact in manifest.artifacts}
    required = {"compiled_bundle.json", "run_records.json"}
    missing = required - artifact_names
    if missing:
        raise BundleIntegrityError("oracle_inputs", f"missing artifacts: {sorted(missing)}")
    try:
        compiled = CompiledBundle.model_validate_json((path / "compiled_bundle.json").read_bytes())
        records = TypeAdapter(tuple[RunRecord, ...]).validate_json(
            (path / "run_records.json").read_bytes(), strict=True
        )
        safety_evidence = (
            SafetyEvidence.model_validate_json((path / "safety_evidence.json").read_bytes())
            if "safety_evidence.json" in artifact_names
            else None
        )
    except ValidationError as error:
        raise BundleIntegrityError("oracle_schema", str(error)) from error
    if safety_evidence is not None:
        if tuple(item.case_index for item in safety_evidence.cases) != tuple(
            record.case_index for record in records
        ):
            raise BundleIntegrityError("oracle_schema", "safety evidence case indexes disagree with records")
    digest_text = (path / "bundle.sha256").read_text(encoding="ascii")
    return _BundleData(
        bundle_id=manifest.bundle_id,
        manifest_digest=digest_text.split()[0],
        compiled=compiled,
        records=records,
        safety_evidence=safety_evidence,
    )


def _compatibility(data: _BundleData) -> tuple[object, ...]:
    return (
        data.compiled.scenario_digest,
        data.compiled.backend.distribution,
        data.compiled.backend.version,
        data.ordered_seeds,
        data.effective_config_digests,
        None
        if data.safety_evidence is None
        else tuple(sorted(data.safety_evidence.metric_definitions.items())),
    )


def _profile_digest(data: dict[str, object]) -> str:
    return hashlib.sha256(rfc8785.dumps(data)).hexdigest()


def calibrate_tolerance(bundle_paths: list[Path]) -> ToleranceProfile:
    if len(bundle_paths) != 5:
        raise CalibrationError("tolerance calibration requires exactly five runs")
    bundles = [_read_bundle(path) for path in bundle_paths]
    if len({bundle.manifest_digest for bundle in bundles}) != 5:
        raise CalibrationError("calibration runs must be five distinct sealed bundles")
    reference = _compatibility(bundles[0])
    if any(_compatibility(bundle) != reference for bundle in bundles[1:]):
        raise CalibrationError("all calibration bundles must have identical compatibility keys")
    if not bundles[0].records:
        raise CalibrationError("calibration bundles must contain at least one RunRecord")
    for bundle in bundles:
        if any(record.status != "completed" for record in bundle.records):
            raise CalibrationError("calibration accepts only completed RunRecords")
    route_values = [record.route_progress for bundle in bundles for record in bundle.records]
    time_values = [record.simulated_seconds for bundle in bundles for record in bundle.records]
    numeric_tolerances = {
        "route_progress": max(round(max(route_values) - min(route_values), 12), 1e-9),
        "simulated_seconds": max(round(max(time_values) - min(time_values), 12), 1e-9),
    }
    safety_evidence = [bundle.safety_evidence for bundle in bundles]
    if any(item is not None for item in safety_evidence):
        if any(item is None for item in safety_evidence):
            raise CalibrationError("calibration safety evidence must be present in every bundle")
        for field in (
            "minimum_ttc_seconds",
            "minimum_headway_seconds",
            "event_to_response_latency_seconds",
        ):
            values = [
                getattr(case.metrics, field)
                for evidence in safety_evidence
                for case in evidence.cases
                if getattr(case.metrics, field) is not None
            ]
            if values:
                numeric_tolerances[f"safety.{field}"] = max(
                    round(max(values) - min(values), 12), 1e-9
                )
    data: dict[str, object] = {
        "schema_version": "scenarioforge.tolerance-profile.v1",
        "profile_version": 1,
        "backend": bundles[0].compiled.backend.distribution,
        "backend_version": bundles[0].compiled.backend.version,
        "scenario_digest": bundles[0].compiled.scenario_digest,
        "effective_config_digest": bundles[0].records[0].effective_config_digest,
        "ordered_seeds": bundles[0].ordered_seeds,
        "calibration_runs": 5,
        "numeric_tolerances": numeric_tolerances,
        "sample_bundle_digests": tuple(bundle.manifest_digest for bundle in bundles),
    }
    return ToleranceProfile(**data, profile_digest=_profile_digest(data))


def _incompatibilities(
    baseline: _BundleData, candidate: _BundleData, profile: ToleranceProfile
) -> tuple[str, ...]:
    differences: list[str] = []
    comparisons = (
        ("scenario_digest", baseline.compiled.scenario_digest, candidate.compiled.scenario_digest),
        ("backend", baseline.compiled.backend.distribution, candidate.compiled.backend.distribution),
        ("backend_version", baseline.compiled.backend.version, candidate.compiled.backend.version),
        ("ordered_seeds", baseline.ordered_seeds, candidate.ordered_seeds),
        (
            "effective_config_digest",
            baseline.effective_config_digests,
            candidate.effective_config_digests,
        ),
    )
    for field, baseline_value, candidate_value in comparisons:
        if baseline_value != candidate_value:
            differences.append(field)
    if baseline.compiled.scenario_digest != profile.scenario_digest:
        differences.append("profile.scenario_digest")
    if baseline.compiled.backend.distribution != profile.backend:
        differences.append("profile.backend")
    if baseline.compiled.backend.version != profile.backend_version:
        differences.append("profile.backend_version")
    if baseline.ordered_seeds != profile.ordered_seeds:
        differences.append("profile.ordered_seeds")
    if (
        not candidate.effective_config_digests
        or any(value != profile.effective_config_digest for value in candidate.effective_config_digests)
    ):
        differences.append("profile.effective_config_digest")
    if (baseline.safety_evidence is None) != (candidate.safety_evidence is None):
        differences.append("safety_evidence")
    elif baseline.safety_evidence is not None and candidate.safety_evidence is not None:
        if baseline.safety_evidence.metric_definitions != candidate.safety_evidence.metric_definitions:
            differences.append("safety_evidence.metric_definitions")
        if tuple(case.safety_constraints for case in baseline.safety_evidence.cases) != tuple(
            case.safety_constraints for case in candidate.safety_evidence.cases
        ):
            differences.append("safety_evidence.safety_constraints")
    return tuple(differences)


def compare_bundles(
    baseline_path: Path, candidate_path: Path, profile: ToleranceProfile
) -> ResimulationReport:
    baseline = _read_bundle(baseline_path)
    candidate = _read_bundle(candidate_path)
    incompatibilities = _incompatibilities(baseline, candidate, profile)
    if incompatibilities:
        return ResimulationReport(
            schema_version="scenarioforge.resimulation-report.v1",
            status="incompatible",
            baseline_bundle_id=baseline.bundle_id,
            candidate_bundle_id=candidate.bundle_id,
            profile_digest=profile.profile_digest,
            incompatibilities=incompatibilities,
            exact_differences=(),
            numeric_differences=(),
        )
    exact_differences: list[ExactDifference] = []
    numeric_differences: list[NumericDifference] = []
    exact_fields = (
        "status",
        "scenario_verdict",
        "termination_reason",
        "steps",
        "collision",
        "off_road",
    )
    numeric_fields = ("route_progress", "simulated_seconds")
    for index, (baseline_record, candidate_record) in enumerate(
        zip(baseline.records, candidate.records, strict=True)
    ):
        for field in exact_fields:
            baseline_value = getattr(baseline_record, field)
            candidate_value = getattr(candidate_record, field)
            if baseline_value != candidate_value:
                exact_differences.append(
                    ExactDifference(
                        field=f"cases/{index}/{field}",
                        baseline=baseline_value,
                        candidate=candidate_value,
                    )
                )
        for field in numeric_fields:
            baseline_value = float(getattr(baseline_record, field))
            candidate_value = float(getattr(candidate_record, field))
            difference = abs(candidate_value - baseline_value)
            tolerance = profile.numeric_tolerances[field]
            if difference > tolerance:
                numeric_differences.append(
                    NumericDifference(
                        field=f"cases/{index}/{field}",
                        baseline=baseline_value,
                        candidate=candidate_value,
                        absolute_difference=difference,
                        tolerance=tolerance,
                    )
                )
    if baseline.safety_evidence is not None and candidate.safety_evidence is not None:
        for index, (baseline_case, candidate_case) in enumerate(
            zip(baseline.safety_evidence.cases, candidate.safety_evidence.cases, strict=True)
        ):
            for field in ("collision", "off_road"):
                baseline_value = getattr(baseline_case.metrics, field)
                candidate_value = getattr(candidate_case.metrics, field)
                if baseline_value != candidate_value:
                    exact_differences.append(
                        ExactDifference(
                            field=f"cases/{index}/safety/{field}",
                            baseline=baseline_value,
                            candidate=candidate_value,
                        )
                    )
            if baseline_case.safety_verdict != candidate_case.safety_verdict:
                exact_differences.append(
                    ExactDifference(
                        field=f"cases/{index}/safety/safety_verdict",
                        baseline=baseline_case.safety_verdict,
                        candidate=candidate_case.safety_verdict,
                    )
                )
            for field in (
                "minimum_ttc_seconds",
                "minimum_headway_seconds",
                "event_to_response_latency_seconds",
            ):
                baseline_value = getattr(baseline_case.metrics, field)
                candidate_value = getattr(candidate_case.metrics, field)
                if baseline_value is None or candidate_value is None:
                    continue
                difference = abs(candidate_value - baseline_value)
                tolerance = profile.numeric_tolerances.get(f"safety.{field}", 0.0)
                if difference > tolerance:
                    numeric_differences.append(
                        NumericDifference(
                            field=f"cases/{index}/safety/{field}",
                            baseline=baseline_value,
                            candidate=candidate_value,
                            absolute_difference=difference,
                            tolerance=tolerance,
                        )
                    )
    return ResimulationReport(
        schema_version="scenarioforge.resimulation-report.v1",
        status="regression" if exact_differences or numeric_differences else "pass",
        baseline_bundle_id=baseline.bundle_id,
        candidate_bundle_id=candidate.bundle_id,
        profile_digest=profile.profile_digest,
        incompatibilities=(),
        exact_differences=tuple(exact_differences),
        numeric_differences=tuple(numeric_differences),
    )


def verify_exact_replay(bundle_path: Path) -> ExactReplayVerification:
    """Verify a sealed bundle for offline exact replay without re-simulating it."""

    manifest = verify_bundle(bundle_path)
    replay = load_replay_bundle(bundle_path)
    manifest_digest = (bundle_path / "bundle.sha256").read_text(encoding="ascii").split()[0]
    return ExactReplayVerification(
        schema_version="scenarioforge.exact-replay-verification.v1",
        status="pass",
        bundle_id=manifest.bundle_id,
        manifest_digest=manifest_digest,
        replay=replay,
    )


def resimulate(
    baseline_path: Path,
    scenario: ScenarioSpec,
    request: RunRequest,
    output_root: Path,
    profile: ToleranceProfile,
) -> ResimulationResult:
    baseline = _read_bundle(baseline_path)
    compiled = compile_scenario(scenario, request)
    if compiled.scenario_digest != baseline.compiled.scenario_digest:
        raise ValueError("re-simulation ScenarioSpec does not match baseline")
    outcome = run_bundle(compiled, output_root, run_id=f"resim-{uuid.uuid4().hex}")
    report = compare_bundles(baseline_path, outcome.bundle_path, profile)
    return ResimulationResult(outcome=outcome, report=report)
