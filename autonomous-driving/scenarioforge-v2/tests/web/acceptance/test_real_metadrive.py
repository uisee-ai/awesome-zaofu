from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

from playwright.sync_api import Browser, Page, expect


ROOT = Path(__file__).resolve().parents[3]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_json(
    page: Page,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return page.evaluate(
        """
        async ({path, method, headers, payload}) => {
          const response = await fetch(path, {
            method,
            headers,
            credentials: "same-origin",
            body: payload === null ? undefined : JSON.stringify(payload),
          });
          return {
            status_code: response.status,
            content_type: response.headers.get("content-type"),
            body: await response.json(),
          };
        }
        """,
        {
            "path": path,
            "method": method,
            "headers": headers or {},
            "payload": payload,
        },
    )


def test_locked_linux_real_metadrive_web_run_binds_api_player_and_publication(
    browser: Browser,
    service_factory,
) -> None:
    assert (platform.system(), platform.machine()) == ("Linux", "x86_64"), (
        "real MetaDrive acceptance requires locked Linux x86_64; incompatible "
        "platforms fail instead of skipping"
    )
    assert platform.python_version() == "3.11.15"
    assert importlib.metadata.version("metadrive-simulator") == "0.4.3"
    lock_digest = _sha256(ROOT / "uv.lock")

    service = service_factory(timeout_seconds=120)
    context = browser.new_context()
    page = context.new_page()
    page.goto(service.base_url)
    expect(page.locator("#app-status")).to_have_text("Ready")

    session = _request_json(page, "/api/session")["body"]
    started = _request_json(
        page,
        "/api/runs",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": "real-metadrive-acceptance",
        },
        payload={"scenario_id": "brake_lead"},
    )
    assert started["status_code"] == 201
    reference = started["body"]
    run_id = str(reference["run_id"])
    attempt_id = str(reference["attempt_id"])
    page.evaluate(
        "(runId) => sessionStorage.setItem('scenarioforge.active-run.v1', runId)",
        run_id,
    )
    page.reload()

    expect(page.locator("#terminal-status")).to_have_text(
        "completed", timeout=120_000
    )
    expect(page.locator("#playback-panel")).to_be_visible()
    expect(page.locator("#replay-canvas canvas")).to_have_count(1)

    terminal_response = _request_json(page, f"/api/runs/{run_id}")
    playback_response = _request_json(
        page, f"/api/runs/{run_id}/artifacts/trajectory"
    )
    assert terminal_response["status_code"] == 200
    assert playback_response["status_code"] == 200
    terminal = terminal_response["body"]
    playback = playback_response["body"]
    assert terminal["run_id"] == playback["run_id"] == run_id
    assert terminal["attempt_id"] == playback["attempt_id"] == attempt_id
    assert terminal["schema_version"] == "scenarioforge.terminal-evidence/v2"
    assert playback["schema_version"] == "scenarioforge.playback/v2"
    assert terminal["execution_status"] == playback["execution_status"] == "completed"
    assert terminal["scenario_outcome"] == playback["scenario_outcome"] == "near_miss"
    assert terminal["termination_reason"] == playback["termination_reason"] == (
        "success_predicates_satisfied"
    )
    assert terminal["playable"] is True

    published = service.workspace / "published" / run_id / attempt_id
    assert sorted(path.name for path in published.glob("SUCCESS")) == ["SUCCESS"]
    result = _json(published / "run_result.json")
    marker = _json(published / "SUCCESS")
    manifest = _json(published / "input" / "run_manifest.json")
    artifact_index = _json(published / "artifact_index.json")
    metrics = _json(published / "output" / "metrics.json")
    events = _json(published / "output" / "events.json")
    trajectory = _json(published / "output" / "trajectory.json")
    worker_result = _json(published / "output" / "worker_result.json")

    assert result == {
        "schema_version": "scenarioforge.run-result/v2",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "execution_status": "completed",
        "scenario_outcome": "near_miss",
        "termination_reason": "success_predicates_satisfied",
        "worker_exit_code": 0,
        "run_manifest_digest": _sha256(published / "input" / "run_manifest.json"),
        "compile_report_digest": result["compile_report_digest"],
        "execution_plan_digest": result["execution_plan_digest"],
        "artifact_index_digest": _sha256(published / "artifact_index.json"),
    }
    assert marker == {
        "schema_version": "scenarioforge.completion-marker/v2",
        "execution_status": "completed",
        "scenario_outcome": "near_miss",
        "termination_reason": "success_predicates_satisfied",
        "run_result_digest": _sha256(published / "run_result.json"),
        "artifact_index_digest": _sha256(published / "artifact_index.json"),
    }
    assert manifest["run_id"] == worker_result["run_id"] == run_id
    assert manifest["attempt_id"] == worker_result["attempt_id"] == attempt_id
    assert manifest["schema_version"] == "scenarioforge.run-manifest/v2"
    assert manifest["environment"] == {
        "architecture": "x86_64",
        "gpu_required": False,
        "headless": True,
        "os": "Linux",
    }
    assert manifest["python"] == {
        "implementation": "CPython",
        "version": "3.11.15",
    }
    assert manifest["dependencies"] == {
        "lockfile": "uv.lock",
        "lockfile_digest": lock_digest,
        "resolved": {
            "jsonschema": "4.25.1",
            "metadrive-simulator": "0.4.3",
        },
    }
    assert manifest["simulator"] == {
        "asset_digest": manifest["simulator"]["asset_digest"],
        "asset_version": "0.4.3",
        "distribution": "metadrive-simulator",
        "version": "0.4.3",
    }
    assert len(manifest["simulator"]["asset_digest"]) == 64
    road_geometry = worker_result["road_geometry"]
    assert {key: value for key, value in worker_result.items() if key != "road_geometry"} == {
        "schema_version": "scenarioforge.worker-result/v2",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "worker_pid": worker_result["worker_pid"],
        "backend": {
            "asset_version": "0.4.3",
            "distribution": "metadrive-simulator",
            "engine_class": "MultiAgentMetaDrive",
            "version": "0.4.3",
        },
        "execution_plan_digest": result["execution_plan_digest"],
        "completed_steps": metrics["completed_steps"],
        "collision": False,
        "execution_status": "completed",
        "scenario_outcome": "near_miss",
        "termination_reason": "success_predicates_satisfied",
    }
    assert road_geometry["schema_version"] == "scenarioforge.road-geometry/v1"
    assert road_geometry["source"] == "metadrive-road-network"
    assert isinstance(worker_result["worker_pid"], int)
    assert worker_result["worker_pid"] > 1

    entries = artifact_index["artifacts"]
    assert {
        key: artifact_index[key]
        for key in (
            "schema_version",
            "run_id",
            "attempt_id",
            "run_manifest_digest",
            "execution_status",
            "scenario_outcome",
            "termination_reason",
        )
    } == {
        "schema_version": "scenarioforge.artifact-index/v2",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "run_manifest_digest": _sha256(published / "input" / "run_manifest.json"),
        "execution_status": "completed",
        "scenario_outcome": "near_miss",
        "termination_reason": "success_predicates_satisfied",
    }
    assert entries == sorted(entries, key=lambda entry: entry["path"])
    by_path = {entry["path"]: entry for entry in entries}
    for relative in (
        "input/run_manifest.json",
        "output/events.json",
        "output/metrics.json",
        "output/trajectory.json",
        "output/worker_result.json",
    ):
        entry = by_path[relative]
        path = published.joinpath(*relative.split("/"))
        assert entry == {
            "path": relative,
            "status": "present",
            "size_bytes": path.stat().st_size,
            "digest": _sha256(path),
            "validation": "verified",
        }

    assert terminal["digests"] == {
        "run_manifest": _sha256(published / "input" / "run_manifest.json"),
        "artifact_index": _sha256(published / "artifact_index.json"),
    }
    assert terminal["logical_ref"] == f"published/{run_id}/{attempt_id}"
    assert terminal["metrics"] == {
        "collision": metrics["collision"],
        "collision_participants": metrics["collision_participants"],
        "min_ttc_s": metrics["min_ttc_s"],
        "minimum_acceleration_mps2": metrics["minimum_acceleration_mps2"],
        "completion_time_s": metrics["completion_time_s"],
        "terminal_tick": metrics["completed_steps"],
    }
    projected_events = [
        {
            "event_id": event["event_id"],
            "sequence": event["sequence"],
            "type": event["type"],
            "participant_id": event["participant_id"],
            "trigger_tick": event["trigger_tick"],
            "effect_state_tick": event["effect_state_tick"],
            "duration_ticks": int(
                manifest["scenario_instance"]["events"][event["sequence"]].get(
                    "duration_ticks", 1
                )
            ),
            "action": event["action"],
        }
        for event in events
    ]
    assert terminal["events"] == playback["events"] == projected_events
    assert playback["logical_ref"] == (
        f"published/{run_id}/{attempt_id}/output/trajectory.json"
    )
    assert playback["trajectory_digest"] == _sha256(
        published / "output" / "trajectory.json"
    )
    assert playback["trajectory"] == trajectory
    assert playback["participants"] == [
        {"id": participant["id"], "role": participant["role"]}
        for participant in manifest["scenario_instance"]["participants"]
    ]
    assert {
        key: value for key, value in playback["road"].items() if key != "geometry"
    } == manifest["scenario_instance"]["road"]
    assert playback["road"]["geometry"] == road_geometry
    assert playback["terminal_tick"] == metrics["completed_steps"]
    assert playback["sample_interval_s"] == metrics["sample_interval_s"]

    participant_legend = page.locator("#participant-legend li").all_inner_texts()
    assert len(participant_legend) == 2
    assert "Following vehicle · ego (ego)" in participant_legend[0]
    assert "Lead vehicle · lead (social)" in participant_legend[1]
    assert all("m/s" in item for item in participant_legend)
    assert page.locator("#replay-timeline").get_attribute("max") == str(
        metrics["completed_steps"]
    )
    assert page.locator("#event-positions .event-marker").all_inner_texts() == [
        f"tick {event['trigger_tick']} · {event['event_id']}" for event in events
    ]
    context.close()
