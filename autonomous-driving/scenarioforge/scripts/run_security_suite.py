from __future__ import annotations

import argparse
import io
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from scenarioforge.api import ApiConfig, create_app  # noqa: E402
from run_offline_demo import write_evidence  # noqa: E402


SCHEMA = "scenarioforge.local-security-evidence.v1"
ORIGIN = "http://127.0.0.1:4173"
CAPABILITY = "cap-5b07f965f85244ce"
CSRF = "csrf-e4f520d0b4894c37"
SECRET_CANARY = "SECRET_CANARY_ATTACK_BODY"
REAL_BUNDLE = PROJECT_ROOT / "evidence/runtime/metadrive-smoke/bundle"


def _headers(**updates: str) -> dict[str, str]:
    headers = {
        "Origin": ORIGIN,
        "X-ScenarioForge-Capability": CAPABILITY,
        "X-ScenarioForge-CSRF": CSRF,
    }
    headers.update(updates)
    return headers


def _scenario(name: str = "security-suite") -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.scenario-spec.v1",
        "name": name,
        "map": {"block_sequence": "S", "lane_count": 2, "lane_width": 3.5},
        "actors": [{"id": "ego", "role": "ego"}],
        "environment": {"traffic_density": 0.1},
        "tags": ["local-security"],
    }


def _make_attack_bundles(root: Path) -> None:
    symlink_bundle = root / "symlink-bundle"
    shutil.copytree(REAL_BUNDLE, symlink_bundle)
    symlink_trace = symlink_bundle / "traces/case-000.json"
    symlink_trace.unlink()
    symlink_trace.symlink_to(REAL_BUNDLE.resolve() / "traces/case-000.json")

    hardlink_bundle = root / "hardlink-bundle"
    shutil.copytree(REAL_BUNDLE, hardlink_bundle)
    hardlink_trace = hardlink_bundle / "traces/case-000.json"
    outside = root / "outside-trace.json"
    outside.write_bytes(hardlink_trace.read_bytes())
    hardlink_trace.unlink()
    os.link(outside, hardlink_trace)


def _record(response: Any, expected_status: int, expected_code: str) -> dict[str, object]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {}
    code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
    return {
        "http_status": response.status_code,
        "error_code": code,
        "rejected": response.status_code == expected_status and code == expected_code,
    }


def _response_surface(response: Any) -> str:
    headers = "\n".join(f"{key}:{value}" for key, value in response.headers.items())
    return "\n".join((response.text, headers, str(response.cookies)))


def build_report() -> dict[str, Any]:
    captured_logs = io.StringIO()
    handler = logging.StreamHandler(captured_logs)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    surfaces: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="scenarioforge-security-") as temporary:
            bundle_root = Path(temporary)
            shutil.copytree(REAL_BUNDLE, bundle_root / "bundle")
            _make_attack_bundles(bundle_root)
            app = create_app(
                ApiConfig(
                    bundle_root=bundle_root,
                    run_output_root=bundle_root,
                    allowed_origin=ORIGIN,
                    capability_token=CAPABILITY,
                    csrf_token=CSRF,
                )
            )
            client = TestClient(
                app,
                base_url="http://127.0.0.1",
                client=("127.0.0.1", 50123),
            )
            responses: dict[str, tuple[Any, int, str]] = {
                "illegal_origin": (
                    client.post(
                        "/api/replays/load",
                        headers=_headers(Origin="https://attacker.invalid"),
                        json={"bundle_id": "bundle"},
                    ),
                    403,
                    "origin_denied",
                ),
                "csrf": (
                    client.post(
                        "/api/replays/load",
                        headers=_headers(**{"X-ScenarioForge-CSRF": "invalid"}),
                        json={"bundle_id": "bundle"},
                    ),
                    403,
                    "csrf_denied",
                ),
                "capability_token": (
                    client.post(
                        "/api/replays/load",
                        headers=_headers(**{"X-ScenarioForge-Capability": "invalid"}),
                        json={"bundle_id": "bundle"},
                    ),
                    403,
                    "capability_denied",
                ),
                "path_traversal": (
                    client.post(
                        "/api/replays/load",
                        headers=_headers(),
                        json={"bundle_id": "../bundle"},
                    ),
                    400,
                    "invalid_bundle_id",
                ),
                "symlink_traversal": (
                    client.post(
                        "/api/replays/load",
                        headers=_headers(),
                        json={"bundle_id": "symlink-bundle"},
                    ),
                    422,
                    "unsafe_filesystem_entry",
                ),
                "hardlink_traversal": (
                    client.post(
                        "/api/replays/load",
                        headers=_headers(),
                        json={"bundle_id": "hardlink-bundle"},
                    ),
                    422,
                    "unsafe_filesystem_entry",
                ),
                "archive_bomb": (
                    client.post(
                        "/api/bundles/import",
                        headers=_headers(),
                        json={"archive": "UEsDBAoAAAAA" * 4096},
                    ),
                    415,
                    "archive_import_disabled",
                ),
                "xss": (
                    client.post(
                        "/api/scenarios/validate",
                        headers=_headers(),
                        json={
                            "source": json.dumps(_scenario("<script>alert(1)</script>")),
                            "media_type": "application/json",
                        },
                    ),
                    400,
                    "unsafe_input",
                ),
                "pickle": (
                    client.post(
                        "/api/bundles/import",
                        headers=_headers(),
                        json={"archive": "\u0080\u0004pickle"},
                    ),
                    415,
                    "archive_import_disabled",
                ),
                "secret_canary": (
                    client.post(
                        "/api/scenarios/validate",
                        headers=_headers(),
                        json={
                            "source": json.dumps(_scenario(SECRET_CANARY)),
                            "media_type": "application/json",
                        },
                    ),
                    400,
                    "unsafe_input",
                ),
            }
            attacks = {
                name: _record(response, status, code)
                for name, (response, status, code) in responses.items()
            }
            surfaces.extend(_response_surface(response) for response, _, _ in responses.values())

            export_response = client.post(
                "/api/scenarios/export",
                headers=_headers(),
                json={
                    "source": json.dumps(_scenario()),
                    "media_type": "application/json",
                    "format": "json",
                },
            )
            surfaces.append(_response_surface(export_response))
            for path in sorted((bundle_root / "bundle").rglob("*")):
                if path.is_file() and not path.is_symlink():
                    surfaces.append(path.read_text(encoding="utf-8", errors="replace"))
            surfaces.append(captured_logs.getvalue())
            combined = "\n".join(surfaces)
            has_auth = CAPABILITY in combined or CSRF in combined
            has_canary = SECRET_CANARY in combined
            has_host_path = any(marker in combined for marker in ("/home/", "/tmp/", "C:\\Users\\"))
            no_cookies = all("set-cookie" not in response.headers for response, _, _ in responses.values())
            required_security_headers = {
                "cache-control",
                "content-security-policy",
                "cross-origin-resource-policy",
                "permissions-policy",
                "referrer-policy",
                "x-content-type-options",
                "x-frame-options",
            }
            security_headers_present = all(
                required_security_headers <= set(response.headers)
                for response, _, _ in responses.values()
            )
            passed = (
                export_response.status_code == 200
                and all(result["rejected"] for result in attacks.values())
                and not has_auth
                and not has_canary
                and not has_host_path
                and no_cookies
                and security_headers_present
            )
    finally:
        root_logger.removeHandler(handler)

    return {
        "schema_version": SCHEMA,
        "acceptance_criterion": "AC-12",
        "status": "passed" if passed else "failed",
        "attacks": attacks,
        "disclosure_scan": {
            "auth_material": "present" if has_auth else "absent",
            "secret_canaries": "present" if has_canary else "absent",
            "host_absolute_paths": "present" if has_host_path else "absent",
        },
        "response_surface": {
            "cookies": "absent" if no_cookies else "present",
            "security_headers": "present" if security_headers_present else "missing",
            "exports_scanned": 1,
            "sealed_bundle_files_scanned": len(list(REAL_BUNDLE.rglob("*"))),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the ScenarioForge local security matrix")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    write_evidence(args.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
