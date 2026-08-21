from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from scenarioforge.authoring.actions import (
    AuthoringActionError,
    AuthoringActionService,
    ControlledResourceRegistry,
)
from scenarioforge.authoring.p1_preflight import evaluate_preflight
from scenarioforge.authoring.providers import CloudProviderPolicy, ProviderDisabled
from scenarioforge.authoring.scenario_spec import normalize_scenario_spec
from scenarioforge.runtime.confirmation import ConfirmationMismatch, ConfirmationReplay


ROOT = Path(__file__).resolve().parents[3]


def _spec():
    return normalize_scenario_spec(
        json.loads(
            (ROOT / "tests/fixtures/authoring/valid_scenario.json").read_text(
                encoding="utf-8"
            )
        )
    )


def _capability():
    return {
        "schema_version": "scenarioforge.capability-report/v1",
        "backend_id": "scenarioforge.smarts",
        "status": "exact",
        "diagnostics": [],
    }


def test_server_confirmation_is_short_lived_single_use_and_bound_to_inputs() -> None:
    service = AuthoringActionService(
        registered_adapter_ids=("scenarioforge.smarts",),
    )
    spec = _spec()
    report = evaluate_preflight(
        spec,
        backend_id="scenarioforge.smarts",
        capability_report=_capability(),
    )

    authorization = service.confirm(spec, report)
    service.authorize_run(authorization, spec, report)
    with pytest.raises(ConfirmationReplay):
        service.authorize_run(authorization, spec, report)

    changed = normalize_scenario_spec({**spec.to_dict()["content"], "seed": 99})
    second = service.confirm(spec, report)
    with pytest.raises(ConfirmationMismatch, match="binding"):
        service.authorize_run(second, changed, report)
    with pytest.raises(AuthoringActionError, match="registered"):
        service.confirm(spec, report, backend_id="module.path:Adapter")


@pytest.mark.parametrize(
    "reference",
    ["/tmp/car.glb", "../car.glb", "file:///tmp/car.glb", "https://example/car.glb"],
)
def test_resources_reject_arbitrary_paths_and_urls(reference: str) -> None:
    registry = ControlledResourceRegistry(
        builtin_ids=("builtin://vehicles/sedan",),
        content_digests=("a" * 64,),
    )
    with pytest.raises(AuthoringActionError, match="controlled resource"):
        registry.resolve(reference)
    assert registry.resolve("builtin://vehicles/sedan") == "builtin://vehicles/sedan"
    assert registry.resolve(f"content://sha256/{'a' * 64}").startswith("content://")


def test_controlled_upload_requires_type_size_and_integrity_before_registration() -> None:
    payload = b"glTF\x02\x00\x00\x00\x0c\x00\x00\x00"
    digest = hashlib.sha256(payload).hexdigest()
    registry = ControlledResourceRegistry(
        builtin_ids=("builtin://vehicles/sedan",),
        max_upload_bytes=64,
    )

    reference = registry.register_upload(
        payload,
        media_type="model/gltf-binary",
        expected_digest=digest,
    )

    assert registry.resolve(reference) == reference
    with pytest.raises(AuthoringActionError, match="media type"):
        registry.register_upload(
            payload,
            media_type="text/html",
            expected_digest=digest,
        )
    disguised = b"not-a-gltf"
    with pytest.raises(AuthoringActionError, match="content does not match"):
        registry.register_upload(
            disguised,
            media_type="model/gltf-binary",
            expected_digest=hashlib.sha256(disguised).hexdigest(),
        )
    with pytest.raises(AuthoringActionError, match="integrity"):
        registry.register_upload(
            payload,
            media_type="model/gltf-binary",
            expected_digest="0" * 64,
        )
    with pytest.raises(AuthoringActionError, match="size"):
        registry.register_upload(
            b"x" * 65,
            media_type="model/gltf-binary",
            expected_digest=hashlib.sha256(b"x" * 65).hexdigest(),
        )


def test_cloud_provider_is_disabled_by_default_and_redacts_allowlisted_scope() -> None:
    disabled = CloudProviderPolicy(provider_id="example-cloud")
    with pytest.raises(ProviderDisabled):
        disabled.prepare_egress({"intent": "merge", "token": "secret"})

    enabled = CloudProviderPolicy(
        provider_id="example-cloud",
        enabled=True,
        allowed_fields=("intent", "context"),
    )
    payload = enabled.prepare_egress({
        "intent": "merge /home/operator/project",
        "context": "credential sk-secret",
        "token": "must-not-leave",
    })
    assert set(payload) == {"intent", "context"}
    assert "/home/operator" not in payload["intent"]
    assert "sk-secret" not in payload["context"]
