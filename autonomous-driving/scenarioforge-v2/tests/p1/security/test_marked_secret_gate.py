from __future__ import annotations

import base64
import json
import zipfile
from pathlib import Path
from urllib.parse import quote

import pytest

from scenarioforge.security import (
    SecurityViolation,
    assert_no_marked_secrets,
    authorize_capture,
    load_artifact_allowlists,
    sanitize_artifact,
)


ROOT = Path(__file__).resolve().parents[3]
ALLOWLISTS = ROOT / "tests/fixtures/p1/security/artifact-allowlists.json"
CASES = ROOT / "tests/fixtures/p1/security/marked-secret-cases.json"
PROFILE = ROOT / "tests/fixtures/p1/security/redaction-profile.json"


def _canaries() -> tuple[str, ...]:
    fixture = json.loads(CASES.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "scenarioforge.marked-secret-cases/v1"
    assert [item["case_id"] for item in fixture["cases"]] == [
        "environment",
        "request-token",
        "cookie",
        "authorization-header",
        "controlled-file",
        "rejected-field",
    ]
    return tuple(item["value"] for item in fixture["cases"])


def test_redaction_profile_and_all_encoded_canary_forms_are_removed() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile == {
        "schema_version": "scenarioforge.redaction-profile/v1",
        "replacement": "<redacted>",
        "forbidden_key_fragments": [
            "secret",
            "token",
            "cookie",
            "authorization",
            "password",
            "environment_value",
            "file_content",
        ],
        "encoded_forms": ["raw", "url", "base64", "hex"],
        "absolute_path_strategy": {
            "project_descendant": "project-relative",
            "other": "<redacted-path>",
        },
        "counterfactual": {
            "redaction_enabled": False,
            "expected_gate_result": "blocked",
        },
    }
    canary = _canaries()[3]
    encoded = " ".join(
        (
            canary,
            quote(canary, safe=""),
            base64.b64encode(canary.encode()).decode(),
            canary.encode().hex(),
        )
    )
    policy = load_artifact_allowlists(ALLOWLISTS).policy("structured_log")

    safe = sanitize_artifact(
        {
            "schema_version": "scenarioforge.structured-log/v1",
            "level": "error",
            "event": "marked_secret_test",
            "message": encoded,
        },
        policy=policy,
        sensitive_values=(canary,),
    )

    assert canary not in str(safe.to_dict())
    assert base64.b64encode(canary.encode()).decode() not in str(safe.to_dict())
    assert canary.encode().hex() not in str(safe.to_dict())


def test_capture_rejects_unapproved_layers_and_secret_render_state_before_capture() -> None:
    policy = load_artifact_allowlists(ALLOWLISTS).policy("screenshot")
    canary = _canaries()[0]

    with pytest.raises(SecurityViolation, match="capture layer") as layer_error:
        authorize_capture(
            policy=policy,
            capture_layers=("replay_canvas", "debug_overlay"),
            render_state={"title": "safe"},
            sensitive_values=(canary,),
        )
    assert layer_error.value.code == "capture_allowlist_violation"

    with pytest.raises(SecurityViolation, match="before capture") as secret_error:
        authorize_capture(
            policy=policy,
            capture_layers=("replay_canvas", "legend"),
            render_state={"legend": f"run {canary}"},
            sensitive_values=(canary,),
        )
    assert secret_error.value.code == "marked_secret_detected"

    authorization = authorize_capture(
        policy=policy,
        capture_layers=("replay_canvas", "legend"),
        render_state={"legend": "run-0001"},
        sensitive_values=(canary,),
    )
    assert authorization.capture_layers == ("replay_canvas", "legend")
    assert authorization.allowlist_digest == policy.digest


@pytest.mark.parametrize("encoding", ["raw", "url", "base64", "hex", "zip"])
def test_release_gate_scans_structured_binary_and_archived_outputs(
    tmp_path: Path,
    encoding: str,
) -> None:
    canary = _canaries()[4]
    output = tmp_path / "artifacts"
    output.mkdir()
    target = output / ("trace.zip" if encoding == "zip" else f"evidence-{encoding}.bin")
    variants = {
        "raw": canary.encode(),
        "url": quote(canary, safe="").encode(),
        "base64": base64.b64encode(canary.encode()),
        "hex": canary.encode().hex().encode(),
    }
    if encoding == "zip":
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("resources/console.log", canary)
    else:
        target.write_bytes(variants[encoding])

    with pytest.raises(SecurityViolation, match="marked secret") as caught:
        assert_no_marked_secrets(output, sensitive_values=(canary,))
    assert caught.value.code == "marked_secret_detected"


def test_counterfactual_unredacted_output_blocks_but_clean_tree_passes(tmp_path: Path) -> None:
    canary = _canaries()[5]
    output = tmp_path / "artifacts"
    output.mkdir()
    evidence = output / "audit.json"
    evidence.write_text(json.dumps({"event": "safe"}), encoding="utf-8")

    assert assert_no_marked_secrets(output, sensitive_values=_canaries()) == (
        "audit.json",
    )

    evidence.write_text(json.dumps({"rejected_field": canary}), encoding="utf-8")
    with pytest.raises(SecurityViolation, match="marked secret"):
        assert_no_marked_secrets(output, sensitive_values=_canaries())
