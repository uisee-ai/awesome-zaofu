from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.release._common import EvidenceError, canonical_json_bytes  # noqa: E402


def _spdx_id(ecosystem: str, name: str, version: str) -> str:
    digest = hashlib.sha256(f"{ecosystem}\0{name}\0{version}".encode()).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9.-]", "-", name)
    return f"SPDXRef-{ecosystem}-{safe}-{digest}"


def _python_components(project_root: Path) -> list[dict[str, Any]]:
    lock = tomllib.loads((project_root / "uv.lock").read_text(encoding="utf-8"))
    components = []
    for package in lock["package"]:
        archive = (package.get("wheels") or [package.get("sdist") or {}])[0]
        checksum = str(archive.get("hash", "")).removeprefix("sha256:")
        components.append(
            {
                "ecosystem": "python",
                "name": package["name"],
                "version": package["version"],
                "scope": "locked",
                "license_declared": "NOASSERTION",
                "redistribution": "source-only; dependency license review required",
                "download_location": package.get("source", {}).get("registry", "NOASSERTION"),
                "checksum_algorithm": "SHA256" if len(checksum) == 64 else None,
                "checksum": checksum if len(checksum) == 64 else None,
            }
        )
    return components


def _npm_components(project_root: Path) -> list[dict[str, Any]]:
    lock = json.loads((project_root / "web/package-lock.json").read_bytes())
    components = []
    for package_path, package in lock["packages"].items():
        if not package_path.startswith("node_modules/"):
            continue
        integrity = package.get("integrity", "")
        checksum_algorithm = None
        checksum = None
        if integrity.startswith("sha512-"):
            checksum_algorithm = "SHA512"
            checksum = base64.b64decode(integrity.removeprefix("sha512-")).hex()
        components.append(
            {
                "ecosystem": "npm",
                "name": package_path.removeprefix("node_modules/"),
                "version": package["version"],
                "scope": "development" if package.get("dev") else "bundled-runtime",
                "license_declared": package.get("license", "NOASSERTION"),
                "redistribution": "bundled in web/dist" if not package.get("dev") else "not bundled",
                "download_location": package.get("resolved", "NOASSERTION"),
                "checksum_algorithm": checksum_algorithm,
                "checksum": checksum,
            }
        )
    return components


def build_compliance_documents(project_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    components = sorted(
        [*_python_components(project_root), *_npm_components(project_root)],
        key=lambda value: (value["ecosystem"], value["name"], value["version"]),
    )
    packages = [
        {
            "SPDXID": "SPDXRef-Package-ScenarioForge",
            "name": "scenarioforge",
            "versionInfo": "0.1.0",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "LicenseRef-ScenarioForge-All-Rights-Reserved",
            "copyrightText": "Copyright (c) 2026 ScenarioForge contributors",
        }
    ]
    relationships = []
    for component in components:
        package = {
            "SPDXID": _spdx_id(
                component["ecosystem"], component["name"], component["version"]
            ),
            "name": component["name"],
            "versionInfo": component["version"],
            "downloadLocation": component["download_location"],
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": component["license_declared"],
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": (
                        f"pkg:pypi/{component['name']}@{component['version']}"
                        if component["ecosystem"] == "python"
                        else f"pkg:npm/{component['name'].replace('/', '%2F')}@{component['version']}"
                    ),
                }
            ],
        }
        if component["checksum_algorithm"] and component["checksum"]:
            package["checksums"] = [
                {
                    "algorithm": component["checksum_algorithm"],
                    "checksumValue": component["checksum"],
                }
            ]
        packages.append(package)
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-ScenarioForge",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package["SPDXID"],
            }
        )
    locks = {
        path: hashlib.sha256((project_root / path).read_bytes()).hexdigest()
        for path in ("uv.lock", "web/package-lock.json", "config/metadrive-assets.lock.json")
    }
    namespace_digest = hashlib.sha256(canonical_json_bytes({"locks": locks})).hexdigest()
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "ScenarioForge-0.1.0",
        "documentNamespace": f"urn:scenarioforge:sbom:{namespace_digest}",
        "creationInfo": {
            "created": "2026-08-03T00:00:00Z",
            "creators": ["Tool: scripts/release/generate_compliance_artifacts.py"],
        },
        "packages": packages,
        "relationships": relationships,
    }
    matrix = {
        "schema_version": "scenarioforge.license-matrix.v1",
        "status": "passed",
        "locks": locks,
        "project_license": "LicenseRef-ScenarioForge-All-Rights-Reserved",
        "asset_redistribution": "prohibited_until_release_license_review",
        "policy": (
            "NOASSERTION entries require review before redistributing dependency source; "
            "the release contains source plus the locked production Web bundle only."
        ),
        "components": [
            {key: value for key, value in component.items() if key not in {"checksum", "checksum_algorithm"}}
            for component in components
        ],
    }
    return sbom, matrix


def _write_exact(path: Path, payload: dict[str, Any]) -> None:
    data = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != data:
        raise EvidenceError(f"generated compliance artifact differs: {path}")
    if not path.exists():
        path.write_bytes(data)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate exact-lock SPDX and license artifacts")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "sbom")
    args = parser.parse_args(argv)
    sbom, matrix = build_compliance_documents(PROJECT_ROOT)
    _write_exact(args.output / "scenarioforge.spdx.json", sbom)
    _write_exact(args.output / "license-matrix.json", matrix)
    print(json.dumps({"status": "passed", "packages": len(sbom["packages"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
