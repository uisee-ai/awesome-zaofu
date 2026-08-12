from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "evidence/release/plan-admission-successor.json"
DIGEST = ROOT / "evidence/release/plan-admission-successor.sha256"
STATE_DIR_NAME = ".zf-scenarioforge-case2-full-20260802t133411z"
ZF_CLI = Path("/home/min/workspace/zaofu/.venv/bin/zf")

R5_COMMIT = "9aae5831b1229c36eb6d88089415f23bfb3eb37f"
R9_WORKER_COMMIT = "2e1f7c1a5e226fa9ca81828a82d9575214a3dd80"
R9_CANDIDATE_COMMIT = "40be029b42172600510c6e94c34b1a97cb490808"
R9_CANDIDATE_AUTHORITY_REF = "event:evt-e3e1d7340a71"
R9_CANDIDATE_AUTHORITY_SHA256 = (
    "19a1c724b22da6df96b029dad3286ae97263ad91782f4ec317dbef73ebd046ff"
)
OWNED_PATHS = {
    "evidence/release/plan-admission-successor.json",
    "evidence/release/plan-admission-successor.sha256",
    "tests/release/test_plan_admission_successor.py",
}
R5_SELF_CHECK_REF = (
    "artifacts/impl-self-check/workflow-8586e3d5e81ee117/"
    "GAP-SFP0-004-RELEASE-PORTS-R5/"
    "run-fanout-prd-lanes-impl-evt-78b12ae0-prd-dev-lane-1-"
    "GAP-SFP0-004-RELEASE-PORTS-R5-176e321e07a487da.json"
)
R9_SELF_CHECK_REF = (
    "artifacts/impl-self-check/workflow-8586e3d5e81ee117/"
    "GAP-SFP0-004-RELEASE-PORTS-R9/"
    "run-fanout-prd-lanes-impl-evt-957c4bdf-prd-dev-lane-1-"
    "GAP-SFP0-004-RELEASE-PORTS-R9-db0413ef46cf5f8f.json"
)


def _receipt() -> dict[str, object]:
    assert RECEIPT.is_file(), "admission successor receipt is required"
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _git_bytes(commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


@lru_cache
def _controlled_event(event_ref: str) -> dict[str, object]:
    assert event_ref.startswith("event:"), "candidate authority must be an event ref"
    event_id = event_ref.removeprefix("event:")
    git_common_dir = Path(
        _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    state_dir = git_common_dir.parent / STATE_DIR_NAME
    assert state_dir.is_dir(), "controlled event state is required"
    assert ZF_CLI.is_file(), "controlled zf event query is required"

    result = json.loads(
        subprocess.check_output(
            [
                str(ZF_CLI),
                "events",
                "--json",
                "--state-dir",
                str(state_dir),
                "--type",
                "candidate.quality.failed",
            ],
            cwd=ROOT,
            text=True,
        )
    )
    assert result["schema_version"] == "zf.cli.result.v1"
    assert result["ok"] is True
    events = result["data"]["events"]
    assert isinstance(events, list)
    matches = [event for event in events if event.get("id") == event_id]

    assert len(matches) == 1, "candidate authority event must exist exactly once"
    authority = matches[0]
    assert authority["type"] == "candidate.quality.failed"
    assert authority["origin"] == "kernel"
    return authority


def _event_sha256(event: dict[str, object]) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _validate_candidate_authority(receipt: dict[str, object]) -> None:
    provenance = receipt["candidate_provenance"]
    assert isinstance(provenance, dict)
    authority = _controlled_event(provenance["authority_ref"])
    assert authority["type"] == "candidate.quality.failed"
    assert authority["origin"] == "kernel"
    assert authority["id"] == provenance["authority_ref"].removeprefix("event:")
    assert _event_sha256(authority) == provenance["authority_sha256"]

    payload = authority["payload"]
    assert isinstance(payload, dict)
    included_task = {
        "task_id": provenance["included_task_id"],
        "task_ref": receipt["implementation_provenance"]["task_ref"],
        "source_commit": provenance["implementation_source_commit"],
        "approval_event_id": provenance["approval_event_ref"].removeprefix("event:"),
        "approval_event_type": "task.ref.updated",
    }
    assert payload["pdd_id"] == receipt["goal_id"]
    assert payload["branch"] == provenance["candidate_ref"]
    assert payload["base_ref"] == provenance["candidate_base_commit"]
    assert payload["requested_base_ref"] == provenance["candidate_base_commit"]
    assert payload["base_commit"] == provenance["candidate_base_commit"]
    assert payload["commit"] == provenance["candidate_commit"]
    assert payload["strategy"] == provenance["strategy"]
    assert payload["requested_tasks"] == [included_task]
    assert payload["included_tasks"] == [included_task]
    assert payload["dependency_tasks"] == []
    assert payload["skipped_tasks"] == []
    assert payload["status"] == provenance["authority_snapshot_status"]
    assert payload["quality_status"] == "failed"


def _validate_owned_path_equivalence(receipt: dict[str, object]) -> None:
    provenance = receipt["candidate_provenance"]
    equivalence = receipt["equivalence"]
    assert isinstance(provenance, dict)
    assert isinstance(equivalence, dict)
    assert equivalence["worker_commit"] == receipt["implementation_provenance"][
        "source_commit"
    ]
    assert equivalence["candidate_commit"] == provenance["candidate_commit"]
    records = equivalence["owned_paths"]
    assert {record["path"] for record in records} == OWNED_PATHS
    assert set(
        _git(
            "diff",
            "--name-only",
            provenance["candidate_base_commit"],
            provenance["candidate_commit"],
        ).splitlines()
    ) == OWNED_PATHS
    for record in records:
        path = record["path"]
        worker_bytes = _git_bytes(equivalence["worker_commit"], path)
        candidate_bytes = _git_bytes(equivalence["candidate_commit"], path)
        assert worker_bytes == candidate_bytes
        assert hashlib.sha256(worker_bytes).hexdigest() == record["content_sha256"]
        assert _git("rev-parse", f'{equivalence["worker_commit"]}:{path}') == record[
            "worker_blob_oid"
        ]
        assert _git("rev-parse", f'{equivalence["candidate_commit"]}:{path}') == record[
            "candidate_blob_oid"
        ]


def _validate_admission_contract(receipt: dict[str, object]) -> None:
    assert receipt["task_id"] == "GAP-SFP0-004-RELEASE-PORTS-R10"
    assert receipt["task_ref"] == "task/GAP-SFP0-004-RELEASE-PORTS-R10"
    assert receipt["lineage"]["task_base_commit"] == R9_CANDIDATE_COMMIT
    assert receipt["plan"]["blocked_by"] == []
    assert receipt["plan"]["dependencies"] == []
    assert receipt["plan"]["supersedes_task_ids"] == [
        "GAP-SFP0-004-RELEASE-PORTS-R9"
    ]
    _validate_candidate_authority(receipt)
    _validate_owned_path_equivalence(receipt)


def test_receipt_binds_r10_plan_and_only_supersedes_r9() -> None:
    receipt = _receipt()

    assert set(receipt) == {
        "schema_version",
        "status",
        "delivery_kind",
        "new_product_implementation",
        "workflow_run_id",
        "goal_id",
        "task_id",
        "fanout_id",
        "run_id",
        "task_ref",
        "contract",
        "plan",
        "lineage",
        "implementation_provenance",
        "candidate_provenance",
        "equivalence",
        "r5_completion",
        "evidence_refs",
    }
    assert receipt["schema_version"] == "scenarioforge.plan-admission-successor.v3"
    assert receipt["status"] == "passed"
    assert receipt["delivery_kind"] == "candidate_provenance_correction"
    assert receipt["new_product_implementation"] is False
    assert receipt["workflow_run_id"] == "workflow-8586e3d5e81ee117"
    assert receipt["goal_id"] == "TASK-F6BCDA"
    assert receipt["task_id"] == "GAP-SFP0-004-RELEASE-PORTS-R10"
    assert receipt["fanout_id"] == "fanout-prd-lanes-impl-evt-431ed73b"
    assert receipt["run_id"] == (
        "run-fanout-prd-lanes-impl-evt-431ed73b-prd-dev-lane-1-"
        "GAP-SFP0-004-RELEASE-PORTS-R10"
    )
    assert receipt["task_ref"] == "task/GAP-SFP0-004-RELEASE-PORTS-R10"
    assert receipt["contract"] == {
        "revision": "contract-rfbb211333a30",
        "snapshot_ref": (
            "artifacts/task-contract-snapshots/workflow-8586e3d5e81ee117/"
            "GAP-SFP0-004-RELEASE-PORTS-R10/"
            "contract-rfbb211333a30-c654384d60152175.json"
        ),
        "snapshot_sha256": (
            "21f20c6ff787f726671c8a367648abaf33cdf24073c99b1c9e6ce481b0888292"
        ),
    }
    assert receipt["plan"] == {
        "resume_scope": "gap_tasks_only",
        "blocked_by": [],
        "dependencies": [],
        "supersedes_task_ids": ["GAP-SFP0-004-RELEASE-PORTS-R9"],
        "task_map_ref": ".zf/artifacts/TASK-F6BCDA/gap-amends/evt-b85a7d3840d6/task_map.json",
        "source_index_ref": "artifacts/plan/source_index.json",
        "task_map_generation": "task-map-64f305c3dcf8339751c3",
        "task_map_target_ref": "6ac629107de1d0b408746ed8d531c794b8a2cc84",
        "handoff_ref": "task/GAP-SFP0-004-RELEASE-PORTS-R10",
    }
    assert receipt["lineage"] == {
        "task_base_commit": R9_CANDIDATE_COMMIT,
        "task_base_ref": f"git:{R9_CANDIDATE_COMMIT}",
        "candidate_assembly_base_commit": R5_COMMIT,
        "candidate_assembly_base_ref": f"git:{R5_COMMIT}",
    }
    assert receipt["evidence_refs"] == [
        "event:evt-1ac234ed7db7",
        f"git:{R5_COMMIT}",
        R5_SELF_CHECK_REF,
        "event:evt-3947c3ab6138",
        f"git:{R9_WORKER_COMMIT}",
        R9_SELF_CHECK_REF,
        R9_CANDIDATE_AUTHORITY_REF,
        f"git:{R9_CANDIDATE_COMMIT}",
        ".zf/artifacts/TASK-F6BCDA/gap-amends/evt-b85a7d3840d6/task_map.json",
    ]

    serialized = json.dumps(receipt, sort_keys=True)
    assert "GAP-SFP0-004-RELEASE-PORTS-R2" not in serialized


def test_worker_and_candidate_provenance_use_separate_authority_domains() -> None:
    receipt = _receipt()

    assert receipt["implementation_provenance"] == {
        "task_id": "GAP-SFP0-004-RELEASE-PORTS-R9",
        "task_ref": "task/GAP-SFP0-004-RELEASE-PORTS-R9",
        "source_commit": R9_WORKER_COMMIT,
        "source_ref": f"git:{R9_WORKER_COMMIT}",
        "completion_event_ref": "event:evt-3947c3ab6138",
        "impl_self_check_ref": R9_SELF_CHECK_REF,
    }
    assert receipt["candidate_provenance"] == {
        "authority_kind": "kernel_candidate_quality_event",
        "authority_ref": R9_CANDIDATE_AUTHORITY_REF,
        "authority_sha256": R9_CANDIDATE_AUTHORITY_SHA256,
        "candidate_ref": "candidate/TASK-F6BCDA",
        "candidate_commit": R9_CANDIDATE_COMMIT,
        "candidate_commit_ref": f"git:{R9_CANDIDATE_COMMIT}",
        "candidate_base_commit": R5_COMMIT,
        "strategy": "cherry-pick",
        "included_task_id": "GAP-SFP0-004-RELEASE-PORTS-R9",
        "implementation_source_commit": R9_WORKER_COMMIT,
        "approval_event_ref": "event:evt-3947c3ab6138",
        "authority_snapshot_status": "quality_failed",
    }
    assert receipt["implementation_provenance"]["source_commit"] != receipt[
        "candidate_provenance"
    ]["candidate_commit"]
    _validate_candidate_authority(receipt)


def test_worker_and_candidate_are_equivalent_on_exact_owned_path_content() -> None:
    receipt = _receipt()
    equivalence = receipt["equivalence"]
    expected_records = [
        {
            "path": "evidence/release/plan-admission-successor.json",
            "content_sha256": (
                "a8d6a7f00cddde6e933191fa4773cc129d241e8576f1aadb3495f60e94a00220"
            ),
            "worker_blob_oid": "ac868e29d588066585628583d789bbb631e0a92d",
            "candidate_blob_oid": "ac868e29d588066585628583d789bbb631e0a92d",
        },
        {
            "path": "evidence/release/plan-admission-successor.sha256",
            "content_sha256": (
                "251152d59a77fe6d627df560f076f58cedba2bdc64a557ab84d9695615cd8576"
            ),
            "worker_blob_oid": "2dc1f770110e1e779bed232cd8bf7331dd6b221a",
            "candidate_blob_oid": "2dc1f770110e1e779bed232cd8bf7331dd6b221a",
        },
        {
            "path": "tests/release/test_plan_admission_successor.py",
            "content_sha256": (
                "af8d3bc55afbfbc822ea479899fa77311848b9f054cf1526d9eb12b9deb4d61c"
            ),
            "worker_blob_oid": "003639d462badca27808876d7aa637288076b053",
            "candidate_blob_oid": "003639d462badca27808876d7aa637288076b053",
        },
    ]

    assert equivalence == {
        "kind": "owned_path_content_digest.v1",
        "worker_commit": R9_WORKER_COMMIT,
        "candidate_commit": R9_CANDIDATE_COMMIT,
        "owned_paths": expected_records,
    }
    assert {record["path"] for record in expected_records} == OWNED_PATHS
    assert set(_git("diff", "--name-only", R5_COMMIT, R9_CANDIDATE_COMMIT).splitlines()) == (
        OWNED_PATHS
    )
    for record in expected_records:
        path = record["path"]
        worker_bytes = _git_bytes(R9_WORKER_COMMIT, path)
        candidate_bytes = _git_bytes(R9_CANDIDATE_COMMIT, path)
        assert worker_bytes == candidate_bytes
        assert hashlib.sha256(worker_bytes).hexdigest() == record["content_sha256"]
        assert _git("rev-parse", f"{R9_WORKER_COMMIT}:{path}") == record[
            "worker_blob_oid"
        ]
        assert _git("rev-parse", f"{R9_CANDIDATE_COMMIT}:{path}") == record[
            "candidate_blob_oid"
        ]
    _validate_owned_path_equivalence(receipt)


def test_candidate_contract_fails_closed_for_missing_or_stale_authority() -> None:
    receipt = _receipt()

    with pytest.raises(AssertionError, match="must exist exactly once"):
        _controlled_event("event:evt-missing-authority")

    stale = copy.deepcopy(receipt)
    stale["candidate_provenance"]["authority_sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        _validate_admission_contract(stale)


def test_candidate_contract_fails_closed_for_identity_or_equivalence_mismatch() -> None:
    receipt = _receipt()
    mutations = [
        ("task identity", ("task_id",), "GAP-SFP0-004-RELEASE-PORTS-R9"),
        (
            "candidate base",
            ("candidate_provenance", "candidate_base_commit"),
            R9_CANDIDATE_COMMIT,
        ),
        (
            "included task",
            ("candidate_provenance", "included_task_id"),
            "GAP-SFP0-004-RELEASE-PORTS-R8",
        ),
        (
            "candidate tree",
            ("candidate_provenance", "candidate_commit"),
            R9_WORKER_COMMIT,
        ),
        (
            "owned content digest",
            ("equivalence", "owned_paths", 0, "content_sha256"),
            "0" * 64,
        ),
        (
            "unexpected owned path",
            ("equivalence", "owned_paths", 0, "path"),
            "scripts/backend",
        ),
    ]

    for _label, path, value in mutations:
        mutated = copy.deepcopy(receipt)
        target = mutated
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(AssertionError):
            _validate_admission_contract(mutated)


def test_receipt_preserves_exact_r5_evidence_without_product_claim() -> None:
    receipt = _receipt()

    assert receipt["r5_completion"] == {
        "task_id": "GAP-SFP0-004-RELEASE-PORTS-R5",
        "event_ref": "event:evt-1ac234ed7db7",
        "source_commit": R5_COMMIT,
        "source_ref": f"git:{R5_COMMIT}",
        "impl_self_check_ref": R5_SELF_CHECK_REF,
        "command_receipts": {"passed": 15, "total": 15},
        "acceptance_results": {"passed": 4, "total": 4},
        "product_tests": {"passed": 88},
    }
    assert receipt["new_product_implementation"] is False


def test_receipt_digest_matches_exact_bytes() -> None:
    receipt_bytes = RECEIPT.read_bytes()
    expected_line = (
        f"{hashlib.sha256(receipt_bytes).hexdigest()}  "
        "evidence/release/plan-admission-successor.json\n"
    )

    assert DIGEST.read_text(encoding="utf-8") == expected_line
