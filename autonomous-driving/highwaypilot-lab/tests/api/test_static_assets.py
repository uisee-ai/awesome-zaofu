from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from highwaypilot_lab.api import RuntimeService, create_app


BASE_URL = "http://127.0.0.1:4317"


@pytest.fixture
def static_root(tmp_path: Path) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html><title>HMI</title>")
    (assets / "app.js").write_text("export const ready = true;")
    (assets / "app.css").write_text("canvas{display:block}")
    (assets / "config.json").write_text('{"ready":true}')
    (assets / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (assets / "mesh.glb").write_bytes(b"glTF")
    (assets / "module.wasm").write_bytes(b"\x00asm")
    (tmp_path / "secret.txt").write_text("not public")
    return assets


@pytest.fixture
def client(static_root: Path) -> TestClient:
    runtime = RuntimeService(project_root=static_root.parent)
    return TestClient(create_app(runtime=runtime, static_root=static_root), base_url=BASE_URL)


@pytest.mark.parametrize(
    ("path", "content_type", "body"),
    [
        ("/", "text/html; charset=utf-8", b"<!doctype html><title>HMI</title>"),
        ("/app.js", "text/javascript; charset=utf-8", b"export const ready = true;"),
        ("/app.css", "text/css; charset=utf-8", b"canvas{display:block}"),
        ("/config.json", "application/json", b'{"ready":true}'),
        ("/icon.png", "image/png", b"\x89PNG\r\n\x1a\n"),
        ("/mesh.glb", "model/gltf-binary", b"glTF"),
        ("/module.wasm", "application/wasm", b"\x00asm"),
    ],
)
def test_static_allowlist_returns_one_exact_mime_and_preserves_bytes(
    client: TestClient,
    path: str,
    content_type: str,
    body: bytes,
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.content == body
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/unknown.exe",
        "/../secret.txt",
        "/%2e%2e/secret.txt",
        "/%252e%252e/secret.txt",
        "/etc/passwd",
    ],
)
def test_unknown_and_traversal_paths_fail_closed(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"

def test_symlink_escape_fails_closed(static_root: Path) -> None:
    (static_root / "escape.json").symlink_to(static_root.parent / "secret.txt")
    client = TestClient(
        create_app(
            runtime=RuntimeService(project_root=static_root.parent),
            static_root=static_root,
        ),
        base_url=BASE_URL,
    )

    response = client.get("/escape.json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"
