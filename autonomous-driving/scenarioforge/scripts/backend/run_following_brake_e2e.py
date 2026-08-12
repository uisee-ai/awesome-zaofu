from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _bootstrap_project_runtime() -> None:
    """Re-exec a bare entrypoint in the project runtime before importing product code."""

    project_python = PROJECT_ROOT / ".venv/bin/python"
    if (
        os.environ.get("SCENARIOFORGE_REGRESSION_BOOTSTRAPPED") == "1"
        or not project_python.is_file()
        or Path(sys.executable).resolve() == project_python.resolve()
    ):
        return
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT_ROOT / "src"), str(PROJECT_ROOT), *([existing_pythonpath] if existing_pythonpath else [])]
    )
    environment["SCENARIOFORGE_REGRESSION_BOOTSTRAPPED"] = "1"
    os.execve(
        str(project_python),
        [str(project_python), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]],
        environment,
    )


_bootstrap_project_runtime()

SRC_ROOT = PROJECT_ROOT / "src"
for import_root in (PROJECT_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scenarioforge.bundle import BundleIntegrityError, load_bundle_json, verify_bundle  # noqa: E402
from scenarioforge.compiler import CompiledBundle, compile_scenario  # noqa: E402
from scenarioforge.oracle import calibrate_tolerance, verify_exact_replay  # noqa: E402
from scenarioforge.runtime import run_bundle  # noqa: E402
from scenarioforge.spec import RunRequest, ScenarioSpec, canonical_scenario, load_scenario  # noqa: E402
from scripts.release._common import write_immutable_json  # noqa: E402


SCHEMA = "scenarioforge.following-brake-regression.v1"
REGRESSION_SAMPLE_ID = "following-emergency-brake"
_PERFORMANCE_FIELDS = {"wall_seconds", "cpu_seconds", "peak_rss_bytes"}
_COMPARISON_FIELDS = (
    "most_dangerous_tick",
    "minimum_ttc_seconds",
    "collision",
    "event_receipt",
    "safety_verdict",
)


def _project_python() -> Path:
    python = PROJECT_ROOT / ".venv/bin/python"
    return python if python.is_file() else Path(sys.executable)


def _scenario_source(samples_root: Path) -> dict[str, Any]:
    payload = json.loads((samples_root / f"{REGRESSION_SAMPLE_ID}.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("following-emergency-brake fixture must be an object")
    return payload


def load_regression_cases(samples_root: Path) -> tuple[ScenarioSpec, ScenarioSpec]:
    """Load the committed safe case and its deliberately unsafe A/B counterpart."""

    baseline_payload = _scenario_source(samples_root)
    candidate_payload = copy.deepcopy(baseline_payload)
    candidate_payload["name"] = f"{REGRESSION_SAMPLE_ID}-candidate"
    candidate_payload["tags"] = ["following-emergency-brake", "metadrive-only", "regression-candidate"]
    candidate_payload["actors"][0]["behavior"] = "follow_lead"
    candidate_payload["actors"][1]["initial_state"] = {
        "lane": 0,
        "longitudinal": 13.0,
        "speed": 0.0,
    }
    candidate_payload["event_triggers"][0]["seconds"] = 0.0
    candidate_payload["safety"] = {
        "max_speed": 20.0,
        "minimum_headway": 0.5,
        "collision_free": True,
    }
    baseline = load_scenario(json.dumps(baseline_payload), "application/json")
    candidate = load_scenario(json.dumps(candidate_payload), "application/json")
    return baseline, candidate


def build_regression_request(scenario: ScenarioSpec) -> RunRequest:
    return RunRequest.model_validate(
        {
            "schema_version": "scenarioforge.run-request.v1",
            "scenario_digest": canonical_scenario(scenario).digest,
            "seeds": [17],
            "profile": "default",
            "limits": {
                "workers": 1,
                "aggregate_cpu_threads": 2,
                "max_steps": 160,
                "max_simulated_seconds": 30.0,
                "case_wall_seconds": 60.0,
                "bundle_wall_seconds": 600.0,
                "bundle_disk_bytes": 1_073_741_824,
            },
        }
    )


def _bundle_descriptor(bundle: Path, *, root: Path) -> dict[str, str]:
    verify_bundle(bundle)
    return {
        "path": bundle.relative_to(root).as_posix(),
        "manifest_sha256": (bundle / "bundle.sha256").read_text(encoding="ascii").split()[0],
    }


def _safety_summary(bundle: Path) -> dict[str, object]:
    evidence = load_bundle_json(bundle, "safety_evidence.json")
    traces = load_bundle_json(bundle, "traces/case-000.json")
    if not isinstance(evidence, dict) or not isinstance(traces, list):
        raise ValueError("sealed bundle lacks safety evidence or trace")
    cases = evidence.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], dict):
        raise ValueError("sealed bundle has an invalid safety case")
    safety_case = cases[0]
    metrics = safety_case.get("metrics")
    if not isinstance(metrics, dict):
        raise ValueError("sealed bundle lacks safety metrics")
    frames = [frame for frame in traces if isinstance(frame, dict)]
    dangerous = min(frames, key=_frame_ttc, default=None)
    if dangerous is None:
        raise ValueError("sealed bundle trace is empty")
    triggered = next(
        (
            (frame.get("step"), receipt)
            for frame in frames[1:]
            for receipt in frame.get("event_receipts", [])
            if isinstance(receipt, dict) and receipt.get("status") == "triggered"
        ),
        None,
    )
    return {
        "most_dangerous_tick": dangerous.get("step"),
        "minimum_ttc_seconds": metrics.get("minimum_ttc_seconds"),
        "collision": metrics.get("collision"),
        "event_receipt": {
            "triggered_tick": None if triggered is None else triggered[0],
            "receipt": None if triggered is None else triggered[1],
        },
        "safety_verdict": safety_case.get("safety_verdict"),
    }


def _frame_ttc(frame: dict[str, object]) -> float:
    actors = frame.get("actors")
    if not isinstance(actors, list):
        return float("inf")
    ego = next((actor for actor in actors if isinstance(actor, dict) and actor.get("role") == "ego"), None)
    if not isinstance(ego, dict):
        return float("inf")
    ego_position = ego.get("position")
    ego_speed = ego.get("speed_mps")
    if not isinstance(ego_position, list) or not isinstance(ego_speed, (int, float)):
        return float("inf")
    values: list[float] = []
    for actor in actors:
        if not isinstance(actor, dict) or actor is ego:
            continue
        position = actor.get("position")
        speed = actor.get("speed_mps")
        if not isinstance(position, list) or not isinstance(speed, (int, float)):
            continue
        gap = float(position[0]) - float(ego_position[0])
        closing_speed = float(ego_speed) - float(speed)
        if gap >= 0.0 and closing_speed > 0.0:
            values.append(gap / closing_speed)
    return min(values, default=float("inf"))


def _assert_tamper_negative(bundle: Path, workspace: Path) -> None:
    tampered = workspace / "tampered"
    shutil.copytree(bundle, tampered)
    try:
        for path in tampered.rglob("*"):
            path.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))
        trace = tampered / "traces/case-000.json"
        trace.write_bytes(trace.read_bytes() + b" ")
        try:
            verify_bundle(tampered)
        except BundleIntegrityError:
            return
        raise ValueError("tamper negative did not fail closed")
    finally:
        if tampered.exists():
            tampered.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            shutil.rmtree(tampered)


def validate_regression_report(report: dict[str, object]) -> None:
    if report.get("schema_version") != SCHEMA or report.get("status") != "passed":
        raise ValueError("regression report did not pass")
    fields = report.get("comparison_fields")
    if not isinstance(fields, list):
        raise ValueError("regression report lacks comparison fields")
    if _PERFORMANCE_FIELDS & set(fields):
        raise ValueError("performance fields must not be used for the regression comparison")
    if set(fields) != set(_COMPARISON_FIELDS):
        raise ValueError("regression report lacks the required safety comparison fields")
    for side in ("baseline", "candidate"):
        value = report.get(side)
        if not isinstance(value, dict) or not isinstance(value.get("bundle"), dict):
            raise ValueError(f"regression report lacks {side} bundle evidence")
    baseline = report["baseline"]
    candidate = report["candidate"]
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        raise ValueError("regression report has invalid A/B sides")
    baseline_safety = baseline.get("safety")
    candidate_safety = candidate.get("safety")
    if not isinstance(baseline_safety, dict) or not isinstance(candidate_safety, dict):
        raise ValueError("regression report lacks A/B safety evidence")
    for field in ("most_dangerous_tick", "minimum_ttc_seconds", "event_receipt"):
        if baseline_safety.get(field) == candidate_safety.get(field):
            raise ValueError(f"baseline and candidate {field} values must differ")
    if baseline_safety.get("collision") == candidate_safety.get("collision"):
        raise ValueError("baseline and candidate collision outcomes must differ")
    if baseline_safety.get("safety_verdict") == candidate_safety.get("safety_verdict"):
        raise ValueError("baseline and candidate safety verdicts must differ")
    execution = report.get("execution")
    if not isinstance(execution, dict) or not isinstance(execution.get("interpreter"), str):
        raise ValueError("regression report lacks the actual Python interpreter path")
    if any(report.get(key) != "passed" for key in ("tamper_negative", "exact_replay", "tolerance_calibration")):
        raise ValueError("regression report has an incomplete verification receipt")
    receipts = report.get("execution_receipts")
    if not isinstance(receipts, list) or len(receipts) != 2:
        raise ValueError("regression report requires CLI and Web API execution receipts")
    by_path = {receipt.get("path"): receipt for receipt in receipts if isinstance(receipt, dict)}
    if set(by_path) != {"cli", "web_api"}:
        raise ValueError("regression report requires distinct cli and web_api receipts")
    cli = by_path["cli"]
    web = by_path["web_api"]
    if cli.get("status") != "completed" or not isinstance(cli.get("command"), list):
        raise ValueError("CLI receipt does not prove a completed project CLI run")
    if web.get("status") != "completed" or web.get("submit_endpoint") != "/api/runs":
        raise ValueError("Web API receipt does not prove a completed API run")
    for receipt in (cli, web):
        if receipt.get("seed") != 17 or receipt.get("profile") != "default":
            raise ValueError("execution receipt does not bind the required seed and profile")


def _run_compiled_case(compiled: CompiledBundle, root: Path, run_id: str) -> Path:
    outcome = run_bundle(compiled, root, run_id=run_id)
    if outcome.status != "completed" or len(outcome.records) != 1:
        raise ValueError(
            f"{run_id} did not complete its real MetaDrive run: "
            f"status={outcome.status}, bundle={outcome.bundle_path}, records={len(outcome.records)}"
        )
    return outcome.bundle_path


def _cli_case(scenario: ScenarioSpec, root: Path, run_id: str, workspace: Path) -> tuple[Path, dict[str, object]]:
    workspace.mkdir(parents=True, exist_ok=True)
    scenario_path = workspace / f"{run_id}.json"
    request_path = workspace / f"{run_id}-request.json"
    scenario_path.write_text(scenario.model_dump_json(), encoding="utf-8")
    request_path.write_text(build_regression_request(scenario).model_dump_json(), encoding="utf-8")
    command = [str(_project_python()), "-m", "scenarioforge.app", "compile", str(scenario_path), "--request", str(request_path)]
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise ValueError(f"project CLI compile failed: {(completed.stderr or completed.stdout).strip()}")
    compiled = CompiledBundle.model_validate_json(completed.stdout)
    bundle = _run_compiled_case(compiled, root, run_id)
    return bundle, {
        "path": "cli",
        "status": "completed",
        "command": command,
        "bundle_path": bundle.relative_to(root.parent).as_posix(),
        "scenario_digest": compiled.scenario_digest,
        "seed": 17,
        "profile": "default",
    }


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request_json(url: str, path: str, *, method: str, payload: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{url}{path}",
        method=method,
        data=body,
        headers={
            "Origin": url,
            "Content-Type": "application/json",
            "X-ScenarioForge-Capability": "following-regression-capability",
            "X-ScenarioForge-CSRF": "following-regression-csrf",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _wait_for_api(url: str, server: subprocess.Popen[bytes]) -> None:
    for _ in range(300):
        if server.poll() is not None:
            raise ValueError("controlled Web API exited before readiness")
        try:
            status, payload = _request_json(url, "/api/health", method="GET")
            if status == 200 and payload.get("status") == "ready":
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.1)
    raise ValueError("controlled Web API did not become ready")


def _web_api_case(scenario: ScenarioSpec, root: Path, run_id: str) -> tuple[Path, dict[str, object]]:
    port = _port()
    url = f"http://127.0.0.1:{port}"
    environment = os.environ | {
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "SCENARIOFORGE_ALLOWED_ORIGIN": url,
        "SCENARIOFORGE_BUNDLE_ROOT": str(root),
        "SCENARIOFORGE_RUN_ROOT": str(root),
        "SCENARIOFORGE_CAPABILITY_TOKEN": "following-regression-capability",
        "SCENARIOFORGE_CSRF_TOKEN": "following-regression-csrf",
    }
    server = subprocess.Popen(
        [str(_project_python()), "-m", "scenarioforge.app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=PROJECT_ROOT,
        env=environment,
        start_new_session=True,
    )
    try:
        _wait_for_api(url, server)
        request = build_regression_request(scenario)
        status, submitted = _request_json(
            url,
            "/api/runs",
            method="POST",
            payload={"source": scenario.model_dump_json(), "media_type": "application/json", "request": request.model_dump(mode="json")},
        )
        if status != 202 or not isinstance(submitted.get("job_id"), str):
            raise ValueError(f"controlled Web API did not accept {run_id}")
        job_id = submitted["job_id"]
        for _ in range(600):
            status, snapshot = _request_json(url, f"/api/runs/{job_id}", method="GET")
            if status != 200:
                raise ValueError(f"controlled Web API lost {job_id}")
            if snapshot.get("status") == "completed":
                bundle_path = snapshot.get("bundle_path")
                if not isinstance(bundle_path, str):
                    raise ValueError("controlled Web API completed without a bundle path")
                bundle = Path(bundle_path)
                verify_bundle(bundle)
                return bundle, {
                    "path": "web_api",
                    "status": "completed",
                    "submit_endpoint": "/api/runs",
                    "status_endpoint": f"/api/runs/{job_id}",
                    "job_id": job_id,
                    "bundle_path": bundle.relative_to(root.parent).as_posix(),
                    "scenario_digest": canonical_scenario(scenario).digest,
                    "seed": 17,
                    "profile": "default",
                }
            if snapshot.get("status") in {"failed", "partial", "cancelled", "aborted"}:
                raise ValueError(f"controlled Web API run {job_id} ended as {snapshot.get('status')}")
            time.sleep(0.1)
        raise ValueError(f"controlled Web API run {job_id} timed out")
    finally:
        if server.poll() is None:
            server.terminate()
            server.wait(timeout=10)


def run(evidence_output: Path, *, repeat: int, paths: tuple[str, ...]) -> dict[str, object]:
    if repeat != 2 or set(paths) != {"cli", "web"}:
        raise ValueError("following-brake regression requires --repeat 2 --paths cli,web")
    report_path = evidence_output / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        validate_regression_report(report)
        return report
    if evidence_output.exists():
        raise ValueError("evidence output must be absent or contain a complete immutable report")
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    baseline, candidate = load_regression_cases(PROJECT_ROOT / "samples")
    temporary = Path(tempfile.mkdtemp(prefix=".following-brake-", dir=evidence_output.parent))
    succeeded = False
    try:
        cli_root = temporary / "cli"
        web_root = temporary / "web"
        baseline_bundle, cli_receipt = _cli_case(baseline, cli_root, "baseline", temporary / "cli-input")
        candidate_bundle, web_receipt = _web_api_case(candidate, web_root, "candidate")
        calibration = [
            _run_compiled_case(compile_scenario(baseline, build_regression_request(baseline)), temporary / "calibration", f"run-{index}")
            for index in range(5)
        ]
        tolerance_profile = calibrate_tolerance(calibration)
        _assert_tamper_negative(baseline_bundle, temporary)
        verify_exact_replay(baseline_bundle)
        verify_exact_replay(candidate_bundle)
        baseline_summary = _safety_summary(baseline_bundle)
        candidate_summary = _safety_summary(candidate_bundle)
        if baseline_summary == candidate_summary:
            raise ValueError("baseline and candidate did not produce a safety regression")
        report: dict[str, object] = {
            "schema_version": SCHEMA,
            "status": "passed",
            "provider": {"distribution": "metadrive-simulator", "version": "0.4.3", "kind": "real"},
            "execution": {
                "interpreter": str(Path(sys.executable).resolve()),
                "system_library_root": os.environ.get("SCENARIOFORGE_SYSTEM_LIBRARY_ROOT"),
            },
            "comparison_fields": list(_COMPARISON_FIELDS),
            "baseline": {"scenario_digest": canonical_scenario(baseline).digest, "bundle": _bundle_descriptor(baseline_bundle, root=temporary), "safety": baseline_summary},
            "candidate": {"scenario_digest": canonical_scenario(candidate).digest, "bundle": _bundle_descriptor(candidate_bundle, root=temporary), "safety": candidate_summary},
            "execution_receipts": [cli_receipt, web_receipt],
            "tolerance_profile": tolerance_profile.model_dump(mode="json"),
            "tamper_negative": "passed",
            "exact_replay": "passed",
            "tolerance_calibration": "passed",
        }
        validate_regression_report(report)
        write_immutable_json(temporary / "report.json", report)
        shutil.copytree(temporary, evidence_output)
        succeeded = True
        return report
    except Exception as error:
        raise ValueError(f"{error}; retained staging={temporary}") from error
    finally:
        if succeeded and temporary.exists():
            for path in temporary.rglob("*"):
                path.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))
            shutil.rmtree(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real following emergency-brake A/B regression")
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, required=True)
    parser.add_argument("--paths", required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args.evidence_output, repeat=args.repeat, paths=tuple(args.paths.split(",")))
    except (OSError, ValueError, BundleIntegrityError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
