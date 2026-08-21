from __future__ import annotations

import json
from pathlib import Path

import pytest

from scenarioforge.security import (
    ArtifactAllowlistRegistry,
    SecurityViolation,
    load_artifact_allowlists,
    sanitize_artifact,
    write_safe_artifact,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/p1/security/artifact-allowlists.json"


def _registry() -> ArtifactAllowlistRegistry:
    return load_artifact_allowlists(FIXTURE)


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.run-manifest/v4",
        "run_id": "run-0001",
        "attempt_id": "attempt-0001",
        "execution_snapshot_id": "snapshot-run-0001-attempt-0001",
        "execution_snapshot_digest": "a" * 64,
        "compile_report_digest": "b" * 64,
        "execution_snapshot": {
            "schema_version": "scenarioforge.execution-snapshot/v1",
            "execution_snapshot_id": "snapshot-run-0001-attempt-0001",
            "normalized_scenario_spec": {
                "schema_version": "scenarioforge.scenario/v3",
                "scenario_id": "highway-merge",
                "traffic_side": "right",
            },
            "normalized_scenario_spec_digest": "c" * 64,
            "resolved_defaults": {
                "schema_version": "scenarioforge.resolved-defaults/v1",
                "values": {"sample_interval_s": 0.1},
            },
            "resolved_defaults_digest": "d" * 64,
            "code": {"commit": "e" * 40, "digest": "f" * 64},
            "adapter": {"id": "scenarioforge.smarts", "version": "2.0.1", "digest": "1" * 64},
            "simulator": {"distribution": "smarts", "version": "2.0.1", "digest": "2" * 64},
            "assets": [{"id": "map", "version": "1", "digest": "3" * 64}],
            "policy": {"id": "keep-lane", "version": "1", "digest": "4" * 64},
            "seed": 17,
            "run_parameters": {"duration_steps": 100},
            "run_parameters_digest": "5" * 64,
            "environment": {"schema_version": "scenarioforge.environment/v1", "os": "Linux"},
            "environment_digest": "6" * 64,
        },
    }


def test_registry_fixture_is_exact_versioned_and_covers_every_governed_artifact() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    registry = _registry()

    assert registry.to_dict() == fixture
    assert registry.kinds() == (
        "artifact_index",
        "audit_record",
        "compile_report",
        "media_sidecar",
        "run_manifest",
        "screenshot",
        "structured_log",
        "trace",
        "video",
        "worker_receipt",
    )
    for kind in registry.kinds():
        policy = registry.policy(kind)
        assert policy.schema_version == "scenarioforge.artifact-allowlist/v1"
        assert len(policy.digest) == 64
        assert set(policy.required_fields) <= set(policy.allowed_fields)


def test_safe_manifest_retains_every_provenance_field_and_records_allowlist_digest() -> None:
    registry = _registry()
    policy = registry.policy("run_manifest")
    manifest = _manifest()

    safe = sanitize_artifact(manifest, policy=policy)

    assert safe.to_dict() == {
        "schema_version": "scenarioforge.safe-artifact/v1",
        "artifact_kind": "run_manifest",
        "allowlist_schema_version": "scenarioforge.artifact-allowlist/v1",
        "allowlist_digest": policy.digest,
        "payload": manifest,
    }
    assert set(safe.payload["execution_snapshot"]) == set(manifest["execution_snapshot"])


def test_unknown_missing_and_forbidden_fields_fail_before_write(tmp_path: Path) -> None:
    policy = _registry().policy("run_manifest")
    destination = tmp_path / "manifest.json"

    unknown = _manifest()
    unknown["debug_dump"] = "not approved"
    with pytest.raises(SecurityViolation, match="unknown field") as caught:
        write_safe_artifact(destination, unknown, policy=policy)
    assert caught.value.code == "artifact_allowlist_violation"
    assert not destination.exists()

    nested = _manifest()
    nested["execution_snapshot"]["adapter"]["access_token"] = "must-not-persist"  # type: ignore[index]
    with pytest.raises(SecurityViolation, match="forbidden field"):
        write_safe_artifact(destination, nested, policy=policy)
    assert not destination.exists()

    missing = _manifest()
    del missing["execution_snapshot"]
    with pytest.raises(SecurityViolation, match="required field"):
        write_safe_artifact(destination, missing, policy=policy)
    assert not destination.exists()


def test_redaction_and_path_conversion_happen_before_exclusive_durable_write(
    tmp_path: Path,
) -> None:
    policy = _registry().policy("structured_log")
    project_root = tmp_path / "project"
    project_root.mkdir()
    destination = tmp_path / "log.json"
    canary = "SF_MARKED_TOKEN_04db73"
    payload = {
        "schema_version": "scenarioforge.structured-log/v1",
        "level": "warning",
        "event": "provider_rejected",
        "message": f"value={canary} source={project_root}/inputs/scenario.json outside=/etc/passwd",
    }

    safe = write_safe_artifact(
        destination,
        payload,
        policy=policy,
        sensitive_values=(canary,),
        project_root=project_root,
    )
    persisted = destination.read_text(encoding="utf-8")

    assert safe.payload["message"] == (
        "value=<redacted> source=project://inputs/scenario.json outside=<redacted-path>"
    )
    assert canary not in persisted
    assert str(project_root) not in persisted
    assert "/etc/passwd" not in persisted
    with pytest.raises(FileExistsError):
        write_safe_artifact(destination, payload, policy=policy)
