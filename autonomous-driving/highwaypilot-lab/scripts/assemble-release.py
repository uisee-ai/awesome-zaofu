#!/usr/bin/env python3
"""Build the real HMI entry and materialize the v1-rc1 candidate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from highwaypilot_lab.api import create_app  # noqa: E402
from highwaypilot_lab.release import ReleaseAssembler  # noqa: E402


RC_ROOT = PROJECT_ROOT / "dist/release-candidates/v1-rc1"
EVIDENCE_ROOT = PROJECT_ROOT / "artifacts/verification/releases/v1-rc1"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_web() -> Path:
    source_root = RC_ROOT / ".web-source"
    output_root = RC_ROOT / ".web-output"
    for path in (source_root, output_root):
        if path.exists():
            shutil.rmtree(path)
    (source_root / "src").mkdir(parents=True)
    shutil.copytree(PROJECT_ROOT / "web/src", source_root / "src", dirs_exist_ok=True)
    shutil.copytree(PROJECT_ROOT / "web/public", source_root / "public", dirs_exist_ok=True)
    (source_root / "index.html").write_text(
        """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="dark">
    <title>HighwayPilot Lab</title>
  </head>
  <body>
    <div id="app" aria-live="polite"><p>正在加载 HighwayPilot Lab…</p></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
""",
        encoding="utf-8",
    )
    # The project-level vite.config.ts uses `root: web` and an output path for
    # the normal development build.  Release assembly builds from a copied,
    # self-contained source tree, so provide an explicit config; otherwise the
    # CLI silently writes dist/web and leaves the release staging directory
    # stale, causing start-demo.sh to serve an older UI bundle.
    config_path = source_root / "vite.config.mjs"
    config_path.write_text(
        "import { defineConfig } from 'vite';\n\n"
        f"export default defineConfig({{ root: {json.dumps(str(source_root))}, "
        f"build: {{ outDir: {json.dumps(str(output_root))}, emptyOutDir: true }} }});\n",
        encoding="utf-8",
    )
    vite = PROJECT_ROOT / "node_modules/.bin/vite"
    if not vite.is_file():
        raise SystemExit("frozen npm dependencies are missing; run npm ci")
    subprocess.run(
        [str(vite), "build", "--config", str(config_path), "--logLevel", "warn"],
        cwd=PROJECT_ROOT,
        check=True,
    )
    return output_root


def _measure_baseline(source_commit: str) -> None:
    samples: list[float] = []
    with TestClient(create_app(), base_url="http://127.0.0.1:4317") as client:
        for _ in range(40):
            started = time.perf_counter_ns()
            response = client.get("/api/health")
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            if response.status_code != 200:
                raise SystemExit("performance suite health probe failed")
            samples.append(elapsed_ms)
    ordered = sorted(samples)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    _write_json(
        PROJECT_ROOT / "evidence/release/performance/baseline.json",
        {
            "schema_version": "performance-baseline/v1",
            "rc_id": "v1-rc1",
            "source_commit": source_commit,
            "suite_id": "highwaypilot-local-smoke/v1",
            "metric": "health_request_latency_ms",
            "sample_count": len(samples),
            "p50_ms": round(ordered[len(ordered) // 2], 6),
            "p95_ms": round(p95, 6),
            "owner_budget_ref": "OWNER-PERF-BUDGET-V1",
            "owner_budget_status": "pending",
        },
    )


def main() -> None:
    source_commit = os.environ.get("HIGHWAYPILOT_SOURCE_COMMIT")
    if source_commit is None:
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
    built_web = _build_web()
    _measure_baseline(source_commit)
    ReleaseAssembler(
        project_root=PROJECT_ROOT,
        rc_root=RC_ROOT,
        evidence_root=EVIDENCE_ROOT,
        source_commit=source_commit,
    ).assemble(built_web)


if __name__ == "__main__":
    main()
