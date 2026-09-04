"""Deterministic v1-rc1 assembly and read-only release verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any


RC_ID = "v1-rc1"
REGISTRY_PATH = "planning/highwaypilot-lab-v1/normalized_registry.json"
REGISTRY_DIGEST_PATH = "planning/highwaypilot-lab-v1/normalized_registry.sha256"
PERFORMANCE_CHECKPOINT = "OWNER-PERF-BUDGET-V1"


class ReleaseIntegrityError(RuntimeError):
    """Raised when a release input or assembled byte fails closed."""


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _write_canonical(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_bytes(value))
    os.replace(temporary, path)


def _required_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file():
        raise ReleaseIntegrityError(f"required release input is missing: {relative}")
    return path


def _digest_record(root: Path, relative: str) -> dict[str, Any]:
    path = _required_file(root, relative)
    return {"path": relative, "sha256": _sha256_file(path), "byte_length": path.stat().st_size}


class ReleaseAssembler:
    """Materialize one non-consumable staging tree, publishing its manifest last."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        rc_root: str | Path,
        evidence_root: str | Path,
        source_commit: str,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.rc_root = Path(rc_root).resolve()
        self.evidence_root = Path(evidence_root).resolve()
        self.source_commit = source_commit
        if len(source_commit) != 40 or any(character not in "0123456789abcdef" for character in source_commit):
            raise ReleaseIntegrityError("source commit must be a full lowercase Git object id")

    def _validate_compliance_inputs(self) -> dict[str, Any]:
        runtime_sbom = _digest_record(self.project_root, "sbom/runtime/index.json")
        training_sbom = _digest_record(self.project_root, "sbom/training/index.json")
        decisions: list[dict[str, Any]] = []
        expected = (
            ("licenses/training/construction-dqn-v1.json", "training_asset"),
            ("licenses/training/model-onnx.json", "runtime_model"),
        )
        for relative, scope in expected:
            path = _required_file(self.project_root, relative)
            try:
                decision = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ReleaseIntegrityError(f"license decision is invalid: {relative}") from error
            if decision.get("decision") != "approved" or decision.get("scope") != scope:
                raise ReleaseIntegrityError(f"license decision is not approved for {scope}: {relative}")
            decisions.append(
                {
                    "decision": "approved",
                    "path": relative,
                    "scope": scope,
                    "sha256": _sha256_file(path),
                }
            )
        return {
            "schema_version": "upstream-consumption-index/v1",
            "rc_id": RC_ID,
            "source_commit": self.source_commit,
            "runtime_sbom": {key: runtime_sbom[key] for key in ("path", "sha256")},
            "training_sbom": {key: training_sbom[key] for key in ("path", "sha256")},
            "license_decisions": decisions,
        }

    def _copy_runtime(self, staging: Path, built_web_root: Path) -> None:
        if not (built_web_root / "index.html").is_file():
            raise ReleaseIntegrityError("built Web root has no index.html")
        runtime = staging / "runtime"
        shutil.copytree(built_web_root, runtime / "web")
        shutil.copytree(
            self.project_root / "src/highwaypilot_lab",
            runtime / "python/highwaypilot_lab",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(self.project_root / "schemas", runtime / "schemas")
        shutil.copytree(self.project_root / "configs/presets", runtime / "configs/presets")
        shutil.copytree(self.project_root / "models/construction-dqn-v1", runtime / "models/construction-dqn-v1")
        for relative in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(_required_file(self.project_root, relative), runtime / relative)

        metadata = staging / "metadata"
        metadata.mkdir(parents=True)
        shutil.copy2(_required_file(self.project_root, "sbom/runtime/index.json"), metadata / "runtime-sbom.json")
        shutil.copy2(_required_file(self.project_root, "sbom/training/index.json"), metadata / "training-sbom.json")
        shutil.copy2(
            _required_file(self.project_root, "licenses/training/construction-dqn-v1.json"),
            metadata / "training-asset-license.json",
        )
        shutil.copy2(
            _required_file(self.project_root, "licenses/training/model-onnx.json"),
            metadata / "runtime-model-license.json",
        )

    @staticmethod
    def _payloads(staging: Path) -> list[dict[str, Any]]:
        payloads = []
        for path in sorted(path for path in staging.rglob("*") if path.is_file()):
            relative = path.relative_to(staging).as_posix()
            payloads.append({"path": relative, "byte_length": path.stat().st_size, "sha256": _sha256_file(path)})
        return payloads

    def _publish(self, staging: Path, manifest: dict[str, Any], manifest_bytes: bytes) -> None:
        self.rc_root.mkdir(parents=True, exist_ok=True)
        for child in tuple(self.rc_root.iterdir()):
            if child == staging:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in tuple(staging.iterdir()):
            os.replace(child, self.rc_root / child.name)
        staging.rmdir()
        checksum = f"{_sha256_bytes(manifest_bytes)}  release-manifest.json\n"
        (self.rc_root / "release-manifest.sha256").write_text(checksum, encoding="ascii")
        (self.rc_root / "release-manifest.json").write_bytes(manifest_bytes)

    def assemble(self, built_web_root: str | Path) -> dict[str, Any]:
        built_web = Path(built_web_root).resolve()
        upstream = self._validate_compliance_inputs()
        registry_path = _required_file(self.project_root, REGISTRY_PATH)
        declared_registry_digest = _required_file(self.project_root, REGISTRY_DIGEST_PATH).read_text().split()[0]
        if _sha256_file(registry_path) != declared_registry_digest:
            raise ReleaseIntegrityError("normalized registry digest mismatch")

        self.evidence_root.mkdir(parents=True, exist_ok=True)
        consumption_path = self.evidence_root / "producer-indexes/upstream-consumption.json"
        _write_canonical(consumption_path, upstream)

        self.rc_root.mkdir(parents=True, exist_ok=True)
        staging = self.rc_root / ".assembly-staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            self._copy_runtime(staging, built_web)
            producer_index = {
                "path": "artifacts/verification/releases/v1-rc1/producer-indexes/upstream-consumption.json",
                "sha256": _sha256_file(consumption_path),
            }
            manifest = {
                "schema_version": "highwaypilot-release-manifest/v1",
                "rc_id": RC_ID,
                "source_commit": self.source_commit,
                "registry": {"path": REGISTRY_PATH, "sha256": declared_registry_digest},
                "payloads": self._payloads(staging),
                "producer_indexes": [producer_index],
                "qualification": {
                    "performance_checkpoint": PERFORMANCE_CHECKPOINT,
                    "owner_budget_status": "pending",
                    "upload_authorized": False,
                },
            }
            manifest_bytes = _canonical_bytes(manifest)
            self._publish(staging, manifest, manifest_bytes)
            return manifest
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise


def _validate_visual_evidence(visual_root: Path) -> dict[str, Any]:
    required = ("desktop-before.png", "desktop-after.png", "mobile.png", "dynamic-difference.json")
    records = [_digest_record(visual_root, relative) for relative in required]
    try:
        delta = json.loads((visual_root / "dynamic-difference.json").read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseIntegrityError("dynamic visual evidence is invalid") from error
    if delta.get("distinct") is not True or not delta.get("dom_assertions"):
        raise ReleaseIntegrityError("dynamic visual evidence lacks state assertions")
    return {"schema_version": "visual-evidence-index/v1", "files": records}


def verify_release(
    project_root: str | Path,
    rc_root: str | Path,
    evidence_root: str | Path,
    *,
    visual_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify immutable inputs and write only the verifier receipt."""

    project = Path(project_root).resolve()
    rc = Path(rc_root).resolve()
    evidence = Path(evidence_root).resolve()
    visual = Path(visual_root).resolve() if visual_root is not None else project / "evidence/release/e2e"
    manifest_path = _required_file(rc, "release-manifest.json")
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseIntegrityError("release manifest is invalid") from error
    required_keys = {
        "schema_version",
        "rc_id",
        "source_commit",
        "registry",
        "payloads",
        "producer_indexes",
        "qualification",
    }
    if set(manifest) != required_keys or manifest.get("rc_id") != RC_ID:
        raise ReleaseIntegrityError("release manifest shape mismatch")
    if manifest_bytes != _canonical_bytes(manifest):
        raise ReleaseIntegrityError("release manifest is not canonical")
    checksum = _required_file(rc, "release-manifest.sha256").read_text(encoding="ascii")
    if checksum != f"{_sha256_bytes(manifest_bytes)}  release-manifest.json\n":
        raise ReleaseIntegrityError("release manifest checksum mismatch")

    declared_paths: set[str] = set()
    for item in manifest["payloads"]:
        if set(item) != {"path", "byte_length", "sha256"}:
            raise ReleaseIntegrityError("payload record shape mismatch")
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts or item["path"] in declared_paths:
            raise ReleaseIntegrityError("payload path is unsafe or duplicated")
        declared_paths.add(item["path"])
        path = rc.joinpath(*relative.parts)
        if not path.is_file() or path.stat().st_size != item["byte_length"] or _sha256_file(path) != item["sha256"]:
            raise ReleaseIntegrityError(f"payload digest mismatch: {item['path']}")
    actual_paths = {
        path.relative_to(rc).as_posix()
        for path in rc.rglob("*")
        if path.is_file() and path.name not in {"release-manifest.json", "release-manifest.sha256"}
    }
    if actual_paths != declared_paths:
        raise ReleaseIntegrityError("release payload inventory mismatch")

    registry = manifest["registry"]
    if registry != {"path": REGISTRY_PATH, "sha256": _sha256_file(_required_file(project, REGISTRY_PATH))}:
        raise ReleaseIntegrityError("release registry binding mismatch")
    for producer in manifest["producer_indexes"]:
        prefix = "artifacts/verification/releases/v1-rc1/"
        if producer["path"].startswith(prefix):
            producer_path = _required_file(evidence, producer["path"][len(prefix):])
        else:
            producer_path = _required_file(project, producer["path"])
        if _sha256_file(producer_path) != producer["sha256"]:
            raise ReleaseIntegrityError("producer index digest mismatch")

    visual_index = _validate_visual_evidence(visual)
    _write_canonical(evidence / "producer-indexes/visual-evidence.json", visual_index)
    receipt = {
        "schema_version": "release-verifier-receipt/v1",
        "command": "./scripts/verify-release.sh",
        "rc_id": RC_ID,
        "source_commit": manifest["source_commit"],
        "registry_sha256": registry["sha256"],
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "integrity_verdict": "passed",
        "upload_authorized": False,
        "qualification_reasons": ["OWNER_PERFORMANCE_BUDGET_NOT_FROZEN"],
        "visual_evidence_sha256": _sha256_file(evidence / "producer-indexes/visual-evidence.json"),
    }
    _write_canonical(evidence / "verifier-receipts/verify-release.json", receipt)
    _write_canonical(
        evidence / "verifier-receipts/upload-preflight.json",
        {
            "schema_version": "upload-preflight/v1",
            "rc_id": RC_ID,
            "manifest_sha256": receipt["manifest_sha256"],
            "authorized": False,
            "reason_codes": receipt["qualification_reasons"],
        },
    )
    return receipt
