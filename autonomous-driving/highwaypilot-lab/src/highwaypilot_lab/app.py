"""Executable composition root for the assembled local product."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from highwaypilot_lab.api import run


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m highwaypilot_lab")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--static-root", type=Path)
    return parser.parse_args(argv)


def resolve_static_root(project_root: str | Path, configured: str | Path | None) -> Path:
    project = Path(project_root).resolve()
    expected = (project / "dist/release-candidates/v1-rc1/runtime/web").resolve()
    selected = Path(configured).resolve() if configured is not None else expected
    if selected != expected:
        raise ValueError("static root must be the v1-rc1 release candidate Web root")
    if not (selected / "index.html").is_file():
        raise FileNotFoundError("assembled Web root is missing index.html")
    return selected


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_cli_args(argv)
    project_root = Path.cwd()
    static_root = resolve_static_root(project_root, args.static_root)
    run(host=args.host, port=args.port, static_root=static_root)
