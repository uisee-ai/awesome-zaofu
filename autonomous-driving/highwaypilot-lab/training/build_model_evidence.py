"""Build replayable author evidence for strategy/model/training acceptance."""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from highwaypilot_lab.model import VerifiedOnnxModel  # noqa: E402
from highwaypilot_lab.strategies import run_four_policy_comparison  # noqa: E402


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    evidence_root = ROOT / "evidence/model"
    model_dir = ROOT / "models/construction-dqn-v1"
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))

    started = time.perf_counter()
    model = VerifiedOnnxModel.load(model_dir)
    initialization_ms = (time.perf_counter() - started) * 1000
    sample = np.zeros(model.input_shape, dtype=np.float32)
    durations = []
    for _ in range(100):
        tick = time.perf_counter()
        model.infer(sample)
        durations.append((time.perf_counter() - tick) * 1000)
    p95_ms = statistics.quantiles(durations, n=100, method="inclusive")[94]
    limits = manifest["resource_limits"]
    resource_verdict = (
        manifest["byte_length"] <= limits["max_model_bytes"]
        and initialization_ms <= limits["max_initialization_ms"]
        and p95_ms <= limits["max_inference_p95_ms"]
    )
    if not resource_verdict:
        raise RuntimeError("model resource qualification failed")
    write(
        evidence_root / "model-verification.json",
        {
            "schema_version": "model-verification/v1",
            "author_self_check": "passed",
            "candidate_admission": "unverified",
            "source_commit": head(),
            "model_sha256": model.sha256,
            "providers": list(model.providers),
            "input": {"name": model.input_name, "shape": list(model.input_shape)},
            "output": {"name": model.output_name, "shape": list(model.output_shape)},
            "operators": sorted(model.operators),
            "measurements": {
                "model_bytes": manifest["byte_length"],
                "initialization_ms": round(initialization_ms, 6),
                "inference_p95_ms": round(p95_ms, 6),
                "inference_samples": len(durations),
            },
            "limits": limits,
        },
    )

    config = json.loads((ROOT / "configs/presets/normal-v1.json").read_text(encoding="utf-8"))
    comparison = run_four_policy_comparison(
        config,
        manual_actions=["SLOWER"] * 60,
        model_dir=model_dir,
        max_steps=60,
    )
    write(
        evidence_root / "four-policy-comparison.json",
        {
            "schema_version": "four-policy-comparison-receipt/v1",
            "author_self_check": "passed",
            "candidate_hmi_e2e": "unverified",
            "source_commit": head(),
            "seed": comparison["seed"],
            "config_digest": comparison["config_digest"],
            "aggregation": comparison["aggregation"],
            "episodes": [
                {
                    "strategy": episode["strategy"],
                    "result": episode["result"],
                    "metrics": episode["metrics"],
                    "decision_count": len(episode["decisions"]),
                    "trace_sha256": digest(episode),
                }
                for episode in comparison["episodes"]
            ],
        },
    )

    runtime_roots = [ROOT / "models", ROOT / "src", ROOT / "web"]
    forbidden_suffixes = {".zip", ".pkl", ".pickle", ".pt", ".pth", ".npz"}
    forbidden_names = {"checkpoint", "replay_buffer", "resume_training"}
    scanned: list[str] = []
    findings: list[str] = []
    for runtime_root in runtime_roots:
        if not runtime_root.exists():
            continue
        for path in runtime_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            scanned.append(relative)
            lowered = path.name.lower()
            if path.suffix.lower() in forbidden_suffixes or any(name in lowered for name in forbidden_names):
                findings.append(relative)
    if findings:
        raise RuntimeError(f"training artifacts leaked into runtime surfaces: {findings}")
    write(
        evidence_root / "training-isolation-scan.json",
        {
            "schema_version": "training-isolation-scan/v1",
            "author_self_check": "passed",
            "candidate_admission": "unverified",
            "source_commit": head(),
            "runtime_roots": [path.relative_to(ROOT).as_posix() for path in runtime_roots],
            "scanned_files": sorted(scanned),
            "forbidden_suffixes": sorted(forbidden_suffixes),
            "forbidden_name_fragments": sorted(forbidden_names),
            "findings": findings,
            "training_checkpoint": "training/assets/construction-dqn-v1/checkpoint.zip",
        },
    )


if __name__ == "__main__":
    main()
