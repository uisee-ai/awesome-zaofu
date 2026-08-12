from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scenarioforge.bundle import verify_bundle  # noqa: E402
from scripts.release._common import (  # noqa: E402
    EvidenceError,
    read_digest_sidecar,
    read_verified_json,
    write_digest_sidecar,
    write_immutable_json,
)

SCHEMA = "scenarioforge.following-brake-browser-e2e.v1"
SHA256 = re.compile(r"[0-9a-f]{64}")
REQUIRED_PRODUCT_ASSERTIONS = {
    "job_status",
    "baseline_actor_replay",
    "candidate_actor_replay",
    "event",
    "minimum_ttc",
    "safety_verdict",
    "comparison",
}


def _browser_bundle_sources(bundle_root: Path) -> dict[str, Path]:
    report = read_verified_json(bundle_root / "report.json")
    sources: dict[str, Path] = {}
    for side in ("baseline", "candidate"):
        descriptor = report.get(side)
        bundle = descriptor.get("bundle") if isinstance(descriptor, dict) else None
        path = bundle.get("path") if isinstance(bundle, dict) else None
        relative = Path(path) if isinstance(path, str) else None
        if relative is None or relative.is_absolute() or ".." in relative.parts:
            raise EvidenceError(f"regression report lacks a safe {side} bundle path")
        sources[side] = bundle_root / relative
    return sources


def _comparison_profile(bundle_root: Path) -> dict[str, object]:
    report = read_verified_json(bundle_root / "report.json")
    profile = report.get("tolerance_profile")
    if not isinstance(profile, dict):
        raise EvidenceError("regression report lacks its calibrated tolerance profile")
    return profile


def validate_browser_report(output: Path) -> dict[str, Any]:
    report = read_verified_json(output / "report.json")
    if report.get("schema_version") != SCHEMA or report.get("status") != "passed":
        raise ValueError("browser report did not pass")
    network = report.get("network_log")
    screenshots = report.get("screenshots")
    bundles = report.get("bundles")
    bundle_ids = report.get("bundle_ids")
    if not isinstance(network, dict) or network.get("path") != "network.json":
        raise ValueError("browser report lacks network evidence")
    if network.get("sha256") != read_digest_sidecar(output / "network.json"):
        raise ValueError("browser network digest disagrees with its sidecar")
    network_payload = read_verified_json(output / "network.json")
    responses = network_payload.get("responses")
    if not isinstance(responses, list):
        raise ValueError("browser network log lacks API responses")
    assertions = report.get("product_assertions")
    if not isinstance(assertions, dict) or set(assertions) != REQUIRED_PRODUCT_ASSERTIONS:
        raise ValueError("browser report lacks required visible product assertions")
    if not all(assertions.values()):
        raise ValueError("browser report contains a failed visible product assertion")
    loaded = {
        response.get("bundle_id")
        if isinstance(response.get("bundle_id"), str)
        else response.get("body", {}).get("bundle_id")
        for response in responses
        if isinstance(response, dict)
        and response.get("method") == "POST"
        and isinstance(response.get("url"), str)
        and response["url"].endswith("/api/replays/load")
        and response.get("response_status") == 200
    }
    if (
        not isinstance(bundle_ids, dict)
        or set(bundle_ids) != {"baseline", "candidate"}
        or not all(isinstance(bundle_id, str) for bundle_id in bundle_ids.values())
        or len(set(bundle_ids.values())) != 2
    ):
        raise ValueError("browser report lacks distinct sealed bundle ids")
    if loaded != set(bundle_ids.values()):
        raise ValueError("browser network log does not prove both replay loads succeeded")
    if not isinstance(screenshots, list) or len(screenshots) != 2:
        raise ValueError("browser report lacks baseline/candidate screenshots")
    expected_screenshots = {"baseline.png", "candidate.png"}
    if {item.get("path") for item in screenshots if isinstance(item, dict)} != expected_screenshots:
        raise ValueError("browser report screenshots are not the baseline/candidate pair")
    for screenshot in screenshots:
        if not isinstance(screenshot, dict) or not isinstance(screenshot.get("sha256"), str):
            raise ValueError("browser report has an invalid screenshot descriptor")
        if screenshot["sha256"] != read_digest_sidecar(output / screenshot["path"]):
            raise ValueError("browser screenshot digest disagrees with its sidecar")
    if (
        not isinstance(bundles, dict)
        or set(bundles) != {"baseline", "candidate"}
        or not all(isinstance(digest, str) and SHA256.fullmatch(digest) for digest in bundles.values())
    ):
        raise ValueError("browser report lacks both bundle digests")
    image = report.get("docker_image")
    if not isinstance(image, dict) or image.get("reference") != "mcp/playwright:latest":
        raise ValueError("browser report lacks Docker image reference")
    if not isinstance(image.get("image_id"), str) or not SHA256.fullmatch(image["image_id"].removeprefix("sha256:")):
        raise ValueError("browser report lacks Docker image id")
    if (
        not isinstance(image.get("repo_digest"), str)
        or not image["repo_digest"].startswith("mcp/playwright@sha256:")
        or not SHA256.fullmatch(image["repo_digest"].removeprefix("mcp/playwright@sha256:"))
    ):
        raise ValueError("browser report lacks Docker image digest")
    return report


def _docker_image_identity() -> dict[str, str]:
    inspected = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}} {{index .RepoDigests 0}}", "mcp/playwright:latest"],
        capture_output=True,
        text=True,
        check=False,
    )
    identity = inspected.stdout.strip().split()
    if inspected.returncode or len(identity) != 2:
        raise EvidenceError("could not resolve the mcp/playwright image id and digest")
    return {"reference": "mcp/playwright:latest", "image_id": identity[0], "repo_digest": identity[1]}


def _remove_temporary_tree(path: Path) -> None:
    for entry in sorted(path.rglob("*"), key=lambda item: item.as_posix(), reverse=True):
        if not entry.is_symlink():
            entry.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if entry.is_dir() else 0))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    shutil.rmtree(path)


def _port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait(url: str, process: subprocess.Popen[bytes]) -> None:
    import urllib.request

    for _ in range(300):
        if process.poll() is not None:
            raise EvidenceError("release server exited before readiness")
        try:
            if urllib.request.urlopen(url, timeout=0.2).status == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise EvidenceError("release server did not become ready")


def run(bundle_root: Path, output: Path) -> dict[str, Any]:
    if (output / "report.json").exists():
        return validate_browser_report(output)
    if output.exists() or output.is_symlink():
        raise EvidenceError("browser output must be absent or complete")
    sources = _browser_bundle_sources(bundle_root)
    comparison_profile = _comparison_profile(bundle_root)
    for bundle in sources.values():
        verify_bundle(bundle)
    temporary = Path(tempfile.mkdtemp(prefix=".following-brake-browser-", dir=output.parent))
    server: subprocess.Popen[bytes] | None = None
    try:
        runs = temporary / "runs"
        bundle_ids = {name: bundle.name for name, bundle in sources.items()}
        for name, bundle in sources.items():
            shutil.copytree(bundle, runs / bundle_ids[name])
        port = _port()
        url = f"http://127.0.0.1:{port}"
        env = os.environ | {"PYTHONPATH": str(PROJECT_ROOT / "src"), "SCENARIOFORGE_ALLOWED_ORIGIN": url, "SCENARIOFORGE_BUNDLE_ROOT": str(runs), "SCENARIOFORGE_RUN_ROOT": str(runs), "SCENARIOFORGE_CAPABILITY_TOKEN": "following-browser-capability", "SCENARIOFORGE_CSRF_TOKEN": "following-browser-csrf"}
        server = subprocess.Popen([str(PROJECT_ROOT / ".venv/bin/python"), "-m", "scenarioforge.app", "--host", "127.0.0.1", "--port", str(port), "--dist-root", str(PROJECT_ROOT / "web/dist")], cwd=PROJECT_ROOT, env=env, start_new_session=True)
        _wait(url, server)
        relative = temporary.resolve().relative_to(PROJECT_ROOT).as_posix()
        script = """import pkg from '/app/node_modules/playwright/index.js'; import { writeFile } from 'node:fs/promises'; const { chromium }=pkg; const b=await chromium.launch({headless:true,executablePath:'/ms-playwright/chromium-1226/chrome-linux64/chrome',args:['--disable-crash-reporter']}); const c=await b.newContext(); const p=await c.newPage(); const seen=[]; p.on('response',r=>{const q=r.request(); if(new URL(r.url()).pathname.startsWith('/api/')){seen.push({method:q.method(),url:r.url(),response_status:r.status(),body:q.postDataJSON?.()})}}); await p.goto(process.env.URL,{waitUntil:'networkidle'}); await p.getByLabel('API endpoint').fill(process.env.URL); await p.getByLabel('Capability token').fill('following-browser-capability'); await p.getByLabel('CSRF token').fill('following-browser-csrf'); const bundle=p.getByRole('textbox',{name:'Bundle ID',exact:true}); const assertions={job_status:await p.getByTestId('job-status').isVisible(),baseline_actor_replay:false,candidate_actor_replay:false,event:false,minimum_ttc:false,safety_verdict:false,comparison:false}; await bundle.fill(process.env.BASELINE_BUNDLE_ID); await p.getByRole('button',{name:'Load sealed replay'}).click(); await p.getByTestId('replay-status').getByText('Sealed replay ready').waitFor(); assertions.baseline_actor_replay=(await p.getByTestId('metrics').textContent()).includes('ego:')&&(await p.getByTestId('metrics').textContent()).includes('lead:'); assertions.event=(await p.getByTestId('events').textContent()).includes('lead-emergency-brake'); assertions.minimum_ttc=(await p.getByTestId('minimum-ttc').textContent()).includes('s'); assertions.safety_verdict=(await p.getByTestId('metrics').textContent()).includes('Safety verdict:'); await p.screenshot({path:process.env.OUT+'/baseline.png'}); await p.getByLabel('New bundle ID').fill(process.env.CANDIDATE_BUNDLE_ID); await p.getByLabel('Tolerance profile JSON').fill(process.env.COMPARISON_PROFILE); await p.getByRole('button',{name:'Compare immutable bundles'}).click(); await p.getByTestId('comparison-result').getByText(/differences/).waitFor(); assertions.comparison=(await p.getByTestId('comparison-result').textContent()).includes('differences'); await bundle.fill(process.env.CANDIDATE_BUNDLE_ID); await p.getByRole('button',{name:'Load sealed replay'}).click(); await p.getByTestId('replay-status').getByText('Sealed replay ready').waitFor(); assertions.candidate_actor_replay=(await p.getByTestId('metrics').textContent()).includes('ego:')&&(await p.getByTestId('metrics').textContent()).includes('lead:'); await p.screenshot({path:process.env.OUT+'/candidate.png'}); if(!Object.values(assertions).every(Boolean)) throw new Error('native UI did not show every required product state'); await writeFile(process.env.OUT+'/network.json',JSON.stringify({responses:seen,product_assertions:assertions})); await writeFile(process.env.OUT+'/product-assertions.json',JSON.stringify(assertions)); await c.close(); await b.close();"""
        completed = subprocess.run(["docker", "run", "--rm", "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "node", "-v", f"{PROJECT_ROOT}:/work", "-w", "/work", "-e", "HOME=/tmp", "-e", f"URL={url}", "-e", f"OUT=/work/{relative}", "-e", f"BASELINE_BUNDLE_ID={bundle_ids['baseline']}", "-e", f"CANDIDATE_BUNDLE_ID={bundle_ids['candidate']}", "-e", f"COMPARISON_PROFILE={json.dumps(comparison_profile, sort_keys=True)}", "mcp/playwright:latest", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=300)
        if completed.returncode:
            raise EvidenceError((completed.stderr or completed.stdout)[-2000:])
        descriptors = []
        for name in ("baseline.png", "candidate.png"):
            descriptors.append({"path": name, "sha256": write_digest_sidecar(temporary / name)})
        network_digest = write_digest_sidecar(temporary / "network.json")
        network_payload = json.loads((temporary / "network.json").read_text(encoding="utf-8"))
        report = {"schema_version": SCHEMA, "status": "passed", "network_log": {"path": "network.json", "sha256": network_digest}, "screenshots": descriptors, "bundles": {name: (runs / bundle_ids[name] / "bundle.sha256").read_text(encoding="ascii").split()[0] for name in ("baseline", "candidate")}, "bundle_ids": bundle_ids, "product_assertions": network_payload["product_assertions"], "docker_image": _docker_image_identity(), "network_mode": "host"}
        write_immutable_json(temporary / "report.json", report)
        validate_browser_report(temporary)
        os.replace(temporary, output)
        return report
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            server.wait(timeout=10)
        if temporary.exists():
            _remove_temporary_tree(temporary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.bundle_root, args.output), sort_keys=True))
    except (EvidenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
