from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from scenarioforge.core import canonical_digest
from scenarioforge.runtime.confirmation import (
    ConfirmationMismatch,
    ConfirmationReplay,
    ConfirmationStale,
    RunAuthorizationAuthority,
)


SPEC = {
    "schema_version": "scenarioforge.scenario/v3",
    "scenario_id": "highway-merge",
    "traffic_side": "right",
}
CAPABILITY_REPORT = {
    "schema_version": "scenarioforge.capability-report/v1",
    "backend_id": "scenarioforge.smarts",
    "status": "exact",
    "diagnostics": [],
}


def test_authorization_binds_normalized_spec_backend_capabilities_and_validation() -> None:
    now = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
    authority = RunAuthorizationAuthority(
        registered_backend_ids=("scenarioforge.smarts", "scenarioforge.metadrive"),
        clock=lambda: now,
        id_factory=lambda: "authorization-0001",
        ttl_seconds=60,
    )

    authorization = authority.issue(
        normalized_scenario_spec=SPEC,
        backend_id="scenarioforge.smarts",
        capability_report=CAPABILITY_REPORT,
        validation_version="scenarioforge.validation/v3",
    )

    assert authorization.to_dict() == {
        "schema_version": "scenarioforge.run-authorization/v1",
        "authorization_id": "authorization-0001",
        "issued_at": "2026-08-19T08:00:00.000000Z",
        "expires_at": "2026-08-19T08:01:00.000000Z",
        "normalized_scenario_spec_digest": canonical_digest(SPEC),
        "backend_id": "scenarioforge.smarts",
        "capability_report_digest": canonical_digest(CAPABILITY_REPORT),
        "validation_version": "scenarioforge.validation/v3",
    }
    assert authority.consume(
        authorization,
        normalized_scenario_spec=SPEC,
        backend_id="scenarioforge.smarts",
        capability_report=CAPABILITY_REPORT,
        validation_version="scenarioforge.validation/v3",
    ) == authorization
    with pytest.raises(ConfirmationReplay):
        authority.consume(
            authorization,
            normalized_scenario_spec=SPEC,
            backend_id="scenarioforge.smarts",
            capability_report=CAPABILITY_REPORT,
            validation_version="scenarioforge.validation/v3",
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"normalized_scenario_spec": {**SPEC, "traffic_side": "left"}}, "binding"),
        ({"backend_id": "scenarioforge.metadrive"}, "binding"),
        ({"capability_report": {**CAPABILITY_REPORT, "status": "lossy"}}, "binding"),
        ({"validation_version": "scenarioforge.validation/v4"}, "binding"),
    ],
)
def test_binding_mutation_invalidates_authorization_and_requires_reconfirmation(
    changes: dict[str, object],
    message: str,
) -> None:
    now = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
    authority = RunAuthorizationAuthority(
        registered_backend_ids=("scenarioforge.smarts", "scenarioforge.metadrive"),
        clock=lambda: now,
    )
    authorization = authority.issue(
        normalized_scenario_spec=SPEC,
        backend_id="scenarioforge.smarts",
        capability_report=CAPABILITY_REPORT,
        validation_version="scenarioforge.validation/v3",
    )
    request = {
        "normalized_scenario_spec": SPEC,
        "backend_id": "scenarioforge.smarts",
        "capability_report": CAPABILITY_REPORT,
        "validation_version": "scenarioforge.validation/v3",
        **changes,
    }

    with pytest.raises(ConfirmationMismatch, match=message):
        authority.consume(authorization, **request)
    with pytest.raises(ConfirmationReplay):
        authority.consume(
            authorization,
            normalized_scenario_spec=SPEC,
            backend_id="scenarioforge.smarts",
            capability_report=CAPABILITY_REPORT,
            validation_version="scenarioforge.validation/v3",
        )


def test_expiry_tampering_and_unregistered_backend_fail_closed() -> None:
    now = datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc)
    current = [now]
    authority = RunAuthorizationAuthority(
        registered_backend_ids=("scenarioforge.smarts",),
        clock=lambda: current[0],
        ttl_seconds=10,
    )
    authorization = authority.issue(
        normalized_scenario_spec=SPEC,
        backend_id="scenarioforge.smarts",
        capability_report=CAPABILITY_REPORT,
        validation_version="scenarioforge.validation/v3",
    )

    current[0] = now + timedelta(seconds=10)
    with pytest.raises(ConfirmationStale, match="expired"):
        authority.consume(
            authorization,
            normalized_scenario_spec=SPEC,
            backend_id="scenarioforge.smarts",
            capability_report=CAPABILITY_REPORT,
            validation_version="scenarioforge.validation/v3",
        )
    with pytest.raises(ConfirmationMismatch, match="not registered"):
        authority.issue(
            normalized_scenario_spec=SPEC,
            backend_id="package.module:Adapter",
            capability_report=CAPABILITY_REPORT,
            validation_version="scenarioforge.validation/v3",
        )

    fresh = authority.issue(
        normalized_scenario_spec=SPEC,
        backend_id="scenarioforge.smarts",
        capability_report=CAPABILITY_REPORT,
        validation_version="scenarioforge.validation/v3",
    )
    with pytest.raises(ConfirmationMismatch, match="issued"):
        authority.consume(
            replace(fresh, capability_report_digest="0" * 64),
            normalized_scenario_spec=SPEC,
            backend_id="scenarioforge.smarts",
            capability_report=CAPABILITY_REPORT,
            validation_version="scenarioforge.validation/v3",
        )
