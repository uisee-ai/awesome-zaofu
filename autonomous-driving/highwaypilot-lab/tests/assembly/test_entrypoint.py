from __future__ import annotations

from pathlib import Path

import pytest

from highwaypilot_lab.app import parse_cli_args, resolve_static_root


def test_product_entrypoint_is_fixed_to_loopback_and_rc_static_root(tmp_path: Path) -> None:
    static_root = tmp_path / "dist/release-candidates/v1-rc1/runtime/web"
    static_root.mkdir(parents=True)
    (static_root / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")

    args = parse_cli_args(["--port", "4317", "--static-root", str(static_root)])

    assert args.host == "127.0.0.1"
    assert args.port == 4317
    assert resolve_static_root(tmp_path, args.static_root) == static_root.resolve()


def test_product_entrypoint_rejects_missing_or_non_rc_static_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="assembled Web root"):
        resolve_static_root(tmp_path, None)

    outside = tmp_path / "web"
    outside.mkdir()
    (outside / "index.html").write_text("placeholder", encoding="utf-8")
    with pytest.raises(ValueError, match="release candidate"):
        resolve_static_root(tmp_path, outside)
