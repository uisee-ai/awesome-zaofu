from __future__ import annotations

import importlib.metadata
import os
import platform
from pathlib import Path

from scenarioforge.core import strict_loads
from scenarioforge.repro import P0RealMatrixRunner


ROOT = Path(__file__).resolve().parents[2]


def test_p0_real_matrix_executes_thirty_real_metadrive_children_and_retains_pairs(
    tmp_path: Path,
) -> None:
    assert (platform.system(), platform.machine()) == ("Linux", "x86_64")
    assert platform.python_version() == "3.11.15"
    assert importlib.metadata.version("metadrive-simulator") == "0.4.3"
    evidence_root = Path(
        os.environ.get(
            "SCENARIOFORGE_REAL_MATRIX_EVIDENCE_DIR",
            ROOT / "artifacts" / "evidence" / "p0-real-matrix",
        )
    )
    report = P0RealMatrixRunner(
        workspace=tmp_path / "runs",
        project_root=ROOT,
        evidence_root=evidence_root,
    ).run()

    assert report.matrix.presets == (
        "construction_merge",
        "highway_merge",
        "brake_lead",
        "dangerous_cut_in",
        "unprotected_left_turn",
    )
    assert report.matrix.seeds == (7, 8, 9)
    assert report.matrix.policy_order == (
        "scenarioforge.deterministic-control@2.0.0",
        "scenarioforge.defensive-control@1.0.0",
    )
    assert report.pair_count == 15
    assert report.real_child_runs == 30
    assert len(report.pairs) == 15
    assert all(pair.baseline.run_id != pair.candidate.run_id for pair in report.pairs)
    assert all(pair.baseline.world_instance_digest == pair.case.world_instance_digest for pair in report.pairs)
    assert all(pair.candidate.world_instance_digest == pair.case.world_instance_digest for pair in report.pairs)
    assert all(pair.candidate.earliest_brake_tick < pair.baseline.earliest_brake_tick for pair in report.pairs if pair.baseline.earliest_brake_tick is not None)
    assert report.statistical_significance_claimed is False
    assert report.violations == ()
    assert report.passed is True

    published = strict_loads((evidence_root / "matrix-report.json").read_bytes())
    assert published == report.to_dict()
