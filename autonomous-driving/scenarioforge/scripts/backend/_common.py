from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import rfc8785

from scenarioforge.bundle import load_bundle_json, verify_bundle
from scenarioforge.compiler import compile_scenario
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


def build_demo(
    *,
    profile: str,
    seeds: list[int],
    actors: int,
    workers: int,
    max_steps: int,
):
    scenario_payload = {
        "schema_version": "scenarioforge.scenario-spec.v1",
        "name": "real-metadrive-evidence",
        "map": {"block_sequence": "S", "lane_count": 2, "lane_width": 3.5},
        "actors": [
            {"id": "ego", "role": "ego"},
            *({"id": f"npc-{index}", "role": "traffic"} for index in range(actors - 1)),
        ],
        "environment": {"traffic_density": min(0.8, max(0.0, (actors - 1) / 10))},
        "tags": ["real-provider", profile],
    }
    scenario = load_scenario(json.dumps(scenario_payload), "application/json")
    hard = profile == "boundary"
    request = RunRequest.model_validate(
        {
            "schema_version": "scenarioforge.run-request.v1",
            "scenario_digest": canonical_scenario(scenario).digest,
            "seeds": seeds,
            "profile": profile,
            "limits": {
                "workers": workers,
                "aggregate_cpu_threads": 4 if hard else 2,
                "max_steps": max_steps,
                "max_simulated_seconds": 60.0 if hard else 30.0,
                "case_wall_seconds": 120.0 if hard else 60.0,
                "bundle_wall_seconds": 1800.0 if hard else 600.0,
                "bundle_disk_bytes": 2_147_483_648 if hard else 1_073_741_824,
            },
        }
    )
    return scenario, request, compile_scenario(scenario, request)


def canonical_bytes(payload: object) -> bytes:
    return rfc8785.dumps(payload) + b"\n"


def bundle_digest(bundle: Path) -> str:
    verify_bundle(bundle)
    return (bundle / "bundle.sha256").read_text(encoding="ascii").split()[0]


def has_real_provider_provenance(bundle: Path) -> bool:
    provenance = load_bundle_json(bundle, "provenance.json")
    if not isinstance(provenance, dict):
        return False
    cases = provenance.get("cases")
    if not isinstance(cases, list) or not cases:
        return False
    required = {
        "backend",
        "backend_version",
        "asset_version",
        "asset_lock_sha256",
        "scenarioforge_version",
        "python_version",
        "platform",
        "worker_pid",
        "execution_kind",
        "network_policy",
        "auto_download",
    }
    return all(
        isinstance(case, dict)
        and set(case) == required
        and case["execution_kind"] == "real-metadrive"
        and case["network_policy"] == "denied"
        and case["auto_download"] is False
        for case in cases
    )


def prepare_output(output: Path) -> None:
    if output.is_symlink():
        raise RuntimeError(f"evidence output must not be a symlink: {output}")
    output.mkdir(parents=True, exist_ok=True)


def write_report_once(output: Path, payload: dict[str, Any]) -> None:
    report = output / "report.json"
    sidecar = output / "report.sha256"
    if report.exists() or sidecar.exists():
        raise FileExistsError(f"evidence report already exists: {output}")
    data = canonical_bytes(payload)
    digest = hashlib.sha256(data).hexdigest()
    temporary_report = output / f".report-{uuid.uuid4().hex}.json"
    temporary_sidecar = output / f".report-{uuid.uuid4().hex}.sha256"
    temporary_report.write_bytes(data)
    temporary_sidecar.write_text(f"{digest}  report.json\n", encoding="ascii")
    os.replace(temporary_report, report)
    os.replace(temporary_sidecar, sidecar)
    report.chmod(0o444)
    sidecar.chmod(0o444)


def read_existing_report(output: Path, schema_version: str) -> dict[str, Any] | None:
    report = output / "report.json"
    sidecar = output / "report.sha256"
    if not report.exists() and not sidecar.exists():
        return None
    if report.is_symlink() or sidecar.is_symlink() or not report.is_file() or not sidecar.is_file():
        raise RuntimeError("evidence report or digest sidecar is missing/unsafe")
    match = re.fullmatch(r"([0-9a-f]{64})  report\.json\n", sidecar.read_text(encoding="ascii"))
    data = report.read_bytes()
    if not match or hashlib.sha256(data).hexdigest() != match.group(1):
        raise RuntimeError("evidence report digest mismatch")
    payload = json.loads(data)
    if payload.get("schema_version") != schema_version:
        raise RuntimeError("evidence report schema mismatch")
    for reference in payload.get("bundles", []):
        path = output / reference["path"]
        if bundle_digest(path) != reference["manifest_digest"]:
            raise RuntimeError(f"referenced bundle digest mismatch: {reference['path']}")
        if payload.get("provider", {}).get("kind") == "real" and not has_real_provider_provenance(path):
            raise RuntimeError(f"referenced bundle lacks complete real-provider provenance: {reference['path']}")
    return payload


def elapsed_seconds(started: float) -> float:
    return round(time.monotonic() - started, 6)


def print_report(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
