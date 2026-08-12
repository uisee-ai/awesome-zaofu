from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Sequence

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from scenarioforge.api import ApiConfig, create_app as create_api_app
from scenarioforge.compiler import compile_scenario
from scenarioforge.oracle import ToleranceProfile, compare_bundles, verify_exact_replay
from scenarioforge.spec import RunRequest, canonical_scenario, load_scenario


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIST_ROOT = PROJECT_ROOT / "web/dist"


def _regular_single_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def _production_tree(dist_root: Path) -> tuple[str, frozenset[str]]:
    if dist_root.is_symlink() or not dist_root.is_dir():
        raise RuntimeError(f"production Web build is missing or unsafe: {dist_root}")
    files: list[Path] = []
    for entry in sorted(dist_root.rglob("*"), key=lambda value: value.as_posix()):
        if entry.is_symlink():
            raise RuntimeError(f"production Web build contains an unsafe link: {entry}")
        if entry.is_dir():
            continue
        if not _regular_single_link(entry):
            raise RuntimeError(f"production Web build contains an unsafe entry: {entry}")
        files.append(entry)
    index = dist_root / "index.html"
    if index not in files:
        raise RuntimeError("production Web build has no safe index.html")
    digest = hashlib.sha256()
    relative_paths: set[str] = set()
    for entry in files:
        relative = entry.relative_to(dist_root).as_posix()
        relative_paths.add(relative)
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(entry.stat().st_size.to_bytes(8, "big"))
        digest.update(hashlib.sha256(entry.read_bytes()).digest())
    return digest.hexdigest(), frozenset(relative_paths)


def create_release_app(
    config: ApiConfig | None = None,
    *,
    dist_root: Path = DEFAULT_DIST_ROOT,
) -> FastAPI:
    """Create the loopback API and exact production Web artifact as one ASGI app."""

    root = dist_root.resolve(strict=False)
    dist_digest, allowed_files = _production_tree(root)
    release_app = FastAPI(
        title="ScenarioForge Offline Studio",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    headers = {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'self'; connect-src 'self' http://127.0.0.1:*; "
            "img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; object-src 'none'; frame-ancestors 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-ScenarioForge-Dist-SHA256": dist_digest,
    }

    def artifact(relative: str) -> FileResponse:
        if relative not in allowed_files:
            raise HTTPException(status_code=404, detail="production artifact not found")
        candidate = root / relative
        if not _regular_single_link(candidate):
            raise HTTPException(status_code=404, detail="production artifact not found")
        return FileResponse(candidate, headers=headers)

    @release_app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return artifact("index.html")

    @release_app.get("/assets/{asset_path:path}", include_in_schema=False)
    def assets(asset_path: str) -> FileResponse:
        return artifact(f"assets/{asset_path}")

    release_app.mount("/", create_api_app(config or ApiConfig.from_environment()))
    return release_app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the supported ScenarioForge release")
    commands = parser.add_subparsers(dest="command")
    samples = commands.add_parser("samples")
    samples.add_argument("action", choices=["list"])
    validate = commands.add_parser("validate")
    validate.add_argument("scenario", type=Path)
    compile_command = commands.add_parser("compile")
    compile_command.add_argument("scenario", type=Path)
    compile_command.add_argument("--request", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("action", choices=["verify"])
    replay.add_argument("--bundle", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4174)
    parser.add_argument("--dist-root", type=Path, default=DEFAULT_DIST_ROOT)
    args = parser.parse_args(argv)
    if args.command == "samples":
        print((Path("samples") / "catalog.json").read_text(encoding="utf-8"), end="")
        return 0
    if args.command in {"validate", "compile"}:
        source = args.scenario.read_text(encoding="utf-8")
        media_type = "application/x-yaml" if args.scenario.suffix in {".yaml", ".yml"} else "application/json"
        scenario = load_scenario(source, media_type)
        if args.command == "validate":
            print(json.dumps({"valid": True, "digest": canonical_scenario(scenario).digest}, sort_keys=True))
            return 0
        request = RunRequest.model_validate(json.loads(args.request.read_text(encoding="utf-8")))
        print(compile_scenario(scenario, request).model_dump_json())
        return 0
    if args.command == "replay":
        print(verify_exact_replay(args.bundle).model_dump_json())
        return 0
    if args.command == "compare":
        profile = ToleranceProfile.model_validate_json(args.profile.read_bytes())
        print(compare_bundles(args.baseline, args.candidate, profile).model_dump_json())
        return 0
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    origin_host = "[::1]" if args.host == "::1" else args.host
    os.environ.setdefault("SCENARIOFORGE_ALLOWED_ORIGIN", f"http://{origin_host}:{args.port}")
    uvicorn.run(
        create_release_app(dist_root=args.dist_root),
        host=args.host,
        port=args.port,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
