from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from scenarioforge.bundle import seal_bundle, verify_bundle
from scenarioforge.replay import ReplayLoadError, load_replay_bundle


REAL_BUNDLE = Path("evidence/runtime/metadrive-smoke/bundle")


def _copy_bundle(tmp_path: Path, name: str = "bundle") -> Path:
    destination = tmp_path / name
    shutil.copytree(REAL_BUNDLE, destination)
    return destination


def test_loads_sealed_real_provider_bundle_without_importing_metadrive() -> None:
    before = set(__import__("sys").modules)

    replay = load_replay_bundle(REAL_BUNDLE)

    after = set(__import__("sys").modules)
    assert replay.bundle_id == "bundle"
    assert replay.status == "completed"
    assert replay.provider.model_dump() == {
        "backend": "metadrive-simulator",
        "backend_version": "0.4.3",
        "execution_kind": "real-metadrive",
        "network_policy": "denied",
        "auto_download": False,
    }
    assert replay.execution.model_dump() == {
        "runner_state": "stopped",
        "metadrive_calls": 0,
        "external_network": "denied",
    }
    case = replay.cases[0]
    assert case.seed == 17
    assert len(case.frames) == 21
    assert case.frames[0].position == (5, 3.5)
    assert case.frames[-1].position == (7.8343329429626465, 3.5)
    assert case.frames[-1].speed_km_h == 10.517005062104593
    assert case.frames[-1].route_progress == 0.0634676881231387
    assert case.events[-1].kind == "termination"
    assert case.events[-1].tick == 20
    assert replay.metrics.total_steps == 20
    assert "metadrive" not in after - before


@pytest.mark.parametrize("extra_name", ["payload.pkl", "unexpected.json"])
def test_rejects_unmanifested_files_before_parse(tmp_path: Path, extra_name: str) -> None:
    bundle = _copy_bundle(tmp_path)
    (bundle / extra_name).write_bytes(b"\x80\x04secret")

    with pytest.raises(ReplayLoadError) as caught:
        load_replay_bundle(bundle)

    assert caught.value.code == "unexpected_artifact"
    assert str(tmp_path) not in str(caught.value)


def test_rejects_symlink_and_hardlink_traversal_before_parse(tmp_path: Path) -> None:
    symlink_bundle = _copy_bundle(tmp_path, "symlink-bundle")
    target = symlink_bundle / "traces" / "case-000.json"
    target.unlink()
    target.symlink_to(REAL_BUNDLE.resolve() / "traces" / "case-000.json")

    with pytest.raises(ReplayLoadError) as symlink_error:
        load_replay_bundle(symlink_bundle)
    assert symlink_error.value.code == "unsafe_filesystem_entry"

    hardlink_bundle = _copy_bundle(tmp_path, "hardlink-bundle")
    target = hardlink_bundle / "traces" / "case-000.json"
    original = tmp_path / "outside.json"
    original.write_bytes(target.read_bytes())
    target.unlink()
    os.link(original, target)

    with pytest.raises(ReplayLoadError) as hardlink_error:
        load_replay_bundle(hardlink_bundle)
    assert hardlink_error.value.code == "unsafe_filesystem_entry"


def test_rejects_digest_tampering_with_public_error_only(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    trace = bundle / "traces" / "case-000.json"
    trace.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ReplayLoadError) as caught:
        load_replay_bundle(bundle)

    assert caught.value.code == "bundle_integrity"
    assert str(bundle) not in str(caught.value)


def test_replay_projects_sealed_versioned_safety_evidence(tmp_path: Path) -> None:
    manifest = verify_bundle(REAL_BUNDLE).model_dump(mode="json")
    files = {
        artifact["path"]: (REAL_BUNDLE / artifact["path"]).read_bytes()
        for artifact in manifest["artifacts"]
    }
    trace = json.loads(files["traces/case-000.json"])
    for frame in trace:
        frame["actors"] = [
            {
                "actor_id": "ego",
                "role": "ego",
                "position": frame["position"],
                "speed_mps": frame["speed_km_h"] / 3.6,
                "heading": frame["heading"],
                "state": "active",
            },
            {
                "actor_id": "lead",
                "role": "traffic",
                "position": [20.0, frame["position"][1]],
                "speed_mps": 0.0,
                "heading": 0.0,
                "state": "stopped",
            },
        ]
        frame["event_receipts"] = [
            {
                "trigger_id": "brake",
                "target_actor_id": "lead",
                "action": "yield",
                "status": "triggered",
                "result": "stopped",
            }
        ]
    files["traces/case-000.json"] = json.dumps(trace).encode()
    files["safety_evidence.json"] = b'''{
        "schema_version":"scenarioforge.safety-evidence.v1",
        "metric_definitions":{"minimum_ttc_seconds":{"formula_version":"v1","formula":"min(gap/closing)","unit":"s","missing_value":null}},
        "cases":[{"case_index":0,"metrics":{"minimum_ttc_seconds":1.5,"minimum_headway_seconds":2.0,"event_to_response_latency_seconds":0.0,"collision":false,"off_road":false,"route_progress":0.0634676881231387},"safety_constraints":{"collision_free":true},"safety_verdict":"pass","violations":[]}]
    }'''
    bundle = seal_bundle(
        tmp_path,
        bundle_id="safety-replay",
        status="completed",
        scenario_digest=manifest["scenario_digest"],
        files=files,
    )

    replay = load_replay_bundle(bundle.path)

    assert replay.safety_evidence is not None
    assert {actor.actor_id for actor in replay.cases[0].frames[0].actors} == {"ego", "lead"}
    assert replay.cases[0].frames[0].event_receipts[0].result == "stopped"
    assert replay.safety_evidence.cases[0].metrics.minimum_ttc_seconds == 1.5
    assert replay.safety_evidence.cases[0].safety_verdict == "pass"
