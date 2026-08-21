#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from scenarioforge.security import assert_no_marked_secrets


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "tests/fixtures/p1/visual-review-schema.json"
REPORT_REF = PurePosixPath("p1-release-browser-report.json")
RECEIPT_REF = PurePosixPath("visual-review-receipt.json")
RECEIPT_DIGEST_ENV = "SCENARIOFORGE_VISUAL_REVIEW_RECEIPT_DIGEST"
SCENARIO_IDS = (
    "highway_merge",
    "competitive_lane_change",
    "cross_traffic_red_light_violation",
    "unprotected_left_turn",
    "pedestrian_red_light_crossing",
)
MEDIA_KINDS = ("screenshot", "video", "trace")
SCENARIO_IDENTITY_FIELDS = (
    "run_id",
    "attempt_id",
    "execution_snapshot_id",
    "execution_snapshot_digest",
)
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9+.-])/(?:home|root|tmp|var|workspace|Users)(?:/[^\s,;\"']*)?"
)
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


class CandidateEvidenceError(Exception):
    pass


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CandidateEvidenceError("candidate delivery arguments are invalid")


def _parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser()
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--source-candidate-commit")
    parser.add_argument("--evidence-dir")
    parser.add_argument("--marked-secret", action="append", default=[])
    return parser


def _write_json(stream: Any, payload: dict[str, object]) -> None:
    stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _health() -> dict[str, object]:
    return {
        "schema_version": "scenarioforge.candidate-delivery-health/v2",
        "status": "ready",
        "entrypoint_id": "p1-candidate-gate",
        "required_arguments": ["--source-candidate-commit", "--evidence-dir"],
        "browser_report": REPORT_REF.as_posix(),
        "visual_review_receipt": RECEIPT_REF.as_posix(),
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CandidateEvidenceError("candidate evidence JSON is ambiguous")
        value[key] = item
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CandidateEvidenceError("candidate evidence input is not a regular file")
    if path.stat().st_size > 1_048_576:
        raise CandidateEvidenceError("candidate evidence input is too large")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CandidateEvidenceError("candidate evidence JSON is invalid") from error
    if not isinstance(value, dict):
        raise CandidateEvidenceError("candidate evidence JSON must be an object")
    return value


def _current_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise CandidateEvidenceError("candidate commit cannot be resolved") from error


def _evidence_root(raw: str) -> Path:
    requested = Path(raw)
    try:
        resolved = requested.resolve(strict=True)
    except OSError as error:
        raise CandidateEvidenceError("candidate evidence directory is unavailable") from error
    if requested.is_symlink() or not resolved.is_dir():
        raise CandidateEvidenceError("candidate evidence directory is unsafe")
    try:
        resolved.relative_to(ROOT.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise CandidateEvidenceError("candidate evidence must be an external sidecar")
    return resolved


def _resolve_artifact(root: Path, reference: str) -> Path:
    pure = PurePosixPath(reference)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise CandidateEvidenceError("candidate artifact reference is unsafe")
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise CandidateEvidenceError("candidate artifact path contains a link")
    try:
        target = (root / Path(*pure.parts)).resolve(strict=True)
        target.relative_to(root)
    except (OSError, ValueError) as error:
        raise CandidateEvidenceError("candidate artifact reference escapes evidence root") from error
    mode = target.lstat().st_mode
    if target.is_symlink() or not stat.S_ISREG(mode):
        raise CandidateEvidenceError("candidate artifact is not a regular file")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_receipt_digest(path: Path) -> str:
    if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise CandidateEvidenceError("visual review receipt must be read only")
    expected = os.environ.get(RECEIPT_DIGEST_ENV)
    if expected is None or not DIGEST.fullmatch(expected):
        raise CandidateEvidenceError("visual review receipt digest is unavailable")
    observed = _sha256(path)
    if observed != expected:
        raise CandidateEvidenceError("visual review receipt digest does not match")
    return observed


def _validate_receipt_shape(receipt: dict[str, Any]) -> None:
    schema = _read_json(SCHEMA_PATH)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)
    except Exception as error:
        raise CandidateEvidenceError("visual review receipt violates its schema") from error


def _canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _package_digest(report_digest: str, media_digest: str) -> str:
    return hashlib.sha256(
        f"{report_digest}\n{media_digest}\n".encode("ascii")
    ).hexdigest()


def _validate_report(
    report: dict[str, Any],
    *,
    source_candidate_commit: str,
    evidence_root: Path,
    report_path: Path,
) -> tuple[str, str, dict[str, dict[str, Any]]]:
    if set(report) != {
        "schema_version",
        "acceptance_coverage",
        "assertion_summary",
        "browser",
        "console_errors",
        "evidence_package",
        "page_errors",
        "scenarios",
        "service_url",
        "source_candidate_bound",
        "source_candidate_commit",
    }:
        raise CandidateEvidenceError("browser report shape is invalid")
    if (
        report["schema_version"] != "scenarioforge.p1-candidate-media/v3"
        or report["source_candidate_bound"] is not True
        or report["source_candidate_commit"] != source_candidate_commit
    ):
        raise CandidateEvidenceError("browser report targets another source candidate")
    coverage = report["acceptance_coverage"]
    if not isinstance(coverage, list) or not {
        "AC-P1-014",
        "AC-P1-017",
        "AC-P1-018",
    } <= set(coverage):
        raise CandidateEvidenceError("browser report acceptance coverage is incomplete")
    browser = report["browser"]
    if (
        not isinstance(browser, dict)
        or set(browser) != {"name", "version"}
        or browser["name"] != "chromium"
        or not isinstance(browser["version"], str)
        or not browser["version"]
    ):
        raise CandidateEvidenceError("browser report runtime is invalid")
    if report["console_errors"] != [] or report["page_errors"] != []:
        raise CandidateEvidenceError("browser report contains runtime errors")
    summary = report["assertion_summary"]
    if (
        not isinstance(summary, dict)
        or set(summary)
        != {
            "heading_tangent_assertion_count",
            "media_count",
            "scenario_count",
            "status",
        }
        or summary["status"] != "passed"
        or summary["scenario_count"] != len(SCENARIO_IDS)
        or summary["media_count"] != len(SCENARIO_IDS) * len(MEDIA_KINDS)
        or not isinstance(summary["heading_tangent_assertion_count"], int)
        or summary["heading_tangent_assertion_count"] <= 0
    ):
        raise CandidateEvidenceError("browser report assertions are incomplete")

    scenarios = report["scenarios"]
    if (
        not isinstance(scenarios, list)
        or tuple(item.get("scenario_id") for item in scenarios if isinstance(item, dict))
        != SCENARIO_IDS
    ):
        raise CandidateEvidenceError("browser report scenarios are incomplete or unordered")
    media_manifest: list[dict[str, object]] = []
    report_bindings: dict[str, dict[str, Any]] = {}
    run_identities: dict[str, set[str]] = {
        "run_id": set(),
        "attempt_id": set(),
        "execution_snapshot_id": set(),
    }
    for scenario in scenarios:
        if set(scenario) != {
            "attempt_id",
            "backend",
            "camera",
            "execution_snapshot_digest",
            "execution_snapshot_id",
            "follow_pose_samples",
            "media",
            "run_id",
            "scenario_id",
            "terminal_status",
        }:
            raise CandidateEvidenceError("browser report scenario shape is invalid")
        if scenario["backend"] != {
            "id": "scenarioforge.smarts",
            "version": "2.0.1",
        } or scenario["terminal_status"] != "completed":
            raise CandidateEvidenceError("browser report backend evidence is invalid")
        if scenario["camera"] != {
            "available_modes": ["ego-follow", "overview", "fixed", "free"],
            "default_mode": "ego-follow",
            "pose_source": "recorded-trajectory",
            "target_participant_id": "ego",
        }:
            raise CandidateEvidenceError("browser report camera evidence is invalid")
        follow_samples = scenario["follow_pose_samples"]
        if (
            not isinstance(follow_samples, list)
            or [item.get("source_tick") for item in follow_samples if isinstance(item, dict)]
            != [5, 10]
        ):
            raise CandidateEvidenceError("browser report follow-camera evidence is invalid")
        snapshot_digest = scenario["execution_snapshot_digest"]
        if not isinstance(snapshot_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", snapshot_digest
        ):
            raise CandidateEvidenceError("browser report snapshot digest is invalid")
        for identity in run_identities:
            value = scenario[identity]
            if not isinstance(value, str) or not value or value in run_identities[identity]:
                raise CandidateEvidenceError("browser report run identities are invalid")
            run_identities[identity].add(value)

        media = scenario["media"]
        if not isinstance(media, dict) or set(media) != set(MEDIA_KINDS):
            raise CandidateEvidenceError("browser report media kinds are incomplete")
        scenario_media: dict[str, dict[str, object]] = {}
        for kind in MEDIA_KINDS:
            item = media[kind]
            if not isinstance(item, dict) or set(item) != {"byte_count", "path", "sha256"}:
                raise CandidateEvidenceError("browser report media shape is invalid")
            reference = item["path"]
            if not isinstance(reference, str):
                raise CandidateEvidenceError("browser report media reference is invalid")
            target = _resolve_artifact(evidence_root, reference)
            digest = _sha256(target)
            if (
                item["byte_count"] != target.stat().st_size
                or item["sha256"] != digest
            ):
                raise CandidateEvidenceError("browser report media binding does not match")
            bound_item = {
                "byte_count": target.stat().st_size,
                "path": reference,
                "sha256": digest,
            }
            media_manifest.append(bound_item)
            scenario_media[kind] = bound_item
        report_bindings[scenario["scenario_id"]] = {
            identity: scenario[identity] for identity in SCENARIO_IDENTITY_FIELDS
        } | {"media": scenario_media}

    references = [str(item["path"]) for item in media_manifest]
    if len(references) != len(set(references)):
        raise CandidateEvidenceError("browser report media references are duplicated")
    media_digest = _canonical_digest(media_manifest)
    if report["evidence_package"] != {
        "schema_version": "scenarioforge.p1-media-package/v1",
        "artifact_count": len(media_manifest),
        "content_digest": media_digest,
        "content_ref": f"sha256:{media_digest}",
    }:
        raise CandidateEvidenceError("browser report media package does not match")
    return _sha256(report_path), media_digest, report_bindings


def _validate_bindings(
    receipt: dict[str, Any],
    *,
    source_candidate_commit: str,
    evidence_root: Path,
    report_digest: str,
    media_digest: str,
    report_bindings: dict[str, dict[str, Any]],
) -> tuple[str, tuple[str, ...]]:
    if receipt["source_candidate_commit"] != source_candidate_commit:
        raise CandidateEvidenceError("visual review receipt targets another source candidate")
    redaction = receipt["redaction_evidence"]
    if redaction["source_candidate_commit"] != source_candidate_commit:
        raise CandidateEvidenceError("redaction evidence targets another source candidate")
    package_digest = _package_digest(report_digest, media_digest)
    if receipt["evidence_package"] != {
        "schema_version": "scenarioforge.candidate-evidence-package/v1",
        "report_ref": REPORT_REF.as_posix(),
        "report_digest": report_digest,
        "media_digest": media_digest,
        "content_digest": package_digest,
        "content_ref": f"sha256:{package_digest}",
    }:
        raise CandidateEvidenceError("visual review evidence package does not match")
    scenarios = receipt["scenarios"]
    if tuple(item["scenario_id"] for item in scenarios) != SCENARIO_IDS:
        raise CandidateEvidenceError("visual review scenarios are incomplete or unordered")
    for identity in ("run_id", "attempt_id", "execution_snapshot_id"):
        values = [item[identity] for item in scenarios]
        if len(values) != len(set(values)):
            raise CandidateEvidenceError("visual review run identities are not unique")

    media_refs: list[str] = []
    for scenario in scenarios:
        if set(scenario["media"]) != set(MEDIA_KINDS):
            raise CandidateEvidenceError("visual review media kinds are incomplete")
        report_binding = report_bindings.get(scenario["scenario_id"])
        if report_binding is None:
            raise CandidateEvidenceError("visual review scenario has no browser report binding")
        if any(
            scenario[identity] != report_binding[identity]
            for identity in SCENARIO_IDENTITY_FIELDS
        ):
            raise CandidateEvidenceError("visual review run identity does not match")
        report_media = report_binding["media"]
        for kind, media in scenario["media"].items():
            reference = media["content_ref"]
            target = _resolve_artifact(evidence_root, reference)
            if (
                _sha256(target) != media["content_digest"]
                or reference != report_media[kind]["path"]
                or media["content_digest"] != report_media[kind]["sha256"]
            ):
                raise CandidateEvidenceError("visual review media digest does not match")
            media_refs.append(reference)

    if len(media_refs) != len(set(media_refs)):
        raise CandidateEvidenceError("visual review media references are duplicated")
    scanned_refs = redaction["scanned_artifact_refs"]
    if not set(media_refs) <= set(scanned_refs):
        raise CandidateEvidenceError("redaction evidence omits reviewed media")
    for reference in scanned_refs:
        _resolve_artifact(evidence_root, reference)
    return package_digest, tuple(sorted(media_refs))


def _text_payloads(path: Path) -> Iterable[bytes]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                member = PurePosixPath(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise CandidateEvidenceError("trace archive member is unsafe")
                yield info.filename.encode("utf-8")
                if not info.is_dir():
                    yield archive.read(info)
    elif path.suffix.lower() in TEXT_SUFFIXES:
        yield path.read_bytes()


def _assert_no_absolute_paths(root: Path) -> None:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        for payload in _text_payloads(path):
            text = payload.decode("utf-8", errors="ignore")
            text = re.sub(r"(?:https?|wss?)://[^\s\"'<>]+", "", text)
            if ABSOLUTE_PATH.search(text):
                raise CandidateEvidenceError("candidate evidence contains an absolute path")


def _sensitive_values(arguments: list[str], evidence_root: Path) -> tuple[str, ...]:
    values = [
        *arguments,
        os.environ.get("SCENARIOFORGE_MARKED_SECRET", ""),
        os.environ.get("SCENARIOFORGE_MEDIA_CANARY", ""),
        str(ROOT),
        str(evidence_root),
    ]
    return tuple(dict.fromkeys(value for value in values if value))


def _evidence_ref(root: Path, scanned: tuple[str, ...]) -> str:
    try:
        relative = root.relative_to(ROOT)
    except ValueError:
        digest = hashlib.sha256()
        for reference in scanned:
            digest.update(reference.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_sha256(root / reference).encode("ascii"))
            digest.update(b"\n")
        return f"sha256:{digest.hexdigest()}"
    return f"project://{relative.as_posix()}"


def _validate(
    source_candidate_commit: str | None,
    evidence_dir: str | None,
    secrets: list[str],
) -> dict[str, object]:
    if (
        source_candidate_commit is None
        or evidence_dir is None
        or not COMMIT.fullmatch(source_candidate_commit)
    ):
        raise CandidateEvidenceError("candidate delivery arguments are incomplete")
    if _current_head() != source_candidate_commit:
        raise CandidateEvidenceError("requested candidate is not the current frozen HEAD")
    root = _evidence_root(evidence_dir)
    report_path = _resolve_artifact(root, REPORT_REF.as_posix())
    report = _read_json(report_path)
    report_digest, media_digest, report_bindings = _validate_report(
        report,
        source_candidate_commit=source_candidate_commit,
        evidence_root=root,
        report_path=report_path,
    )
    receipt_path = _resolve_artifact(root, RECEIPT_REF.as_posix())
    receipt_digest = _validate_receipt_digest(receipt_path)
    receipt = _read_json(receipt_path)
    _validate_receipt_shape(receipt)
    package_digest, _ = _validate_bindings(
        receipt,
        source_candidate_commit=source_candidate_commit,
        evidence_root=root,
        report_digest=report_digest,
        media_digest=media_digest,
        report_bindings=report_bindings,
    )
    scanned = assert_no_marked_secrets(
        root,
        sensitive_values=_sensitive_values(secrets, root),
    )
    _assert_no_absolute_paths(root)
    return {
        "schema_version": "scenarioforge.candidate-delivery-result/v2",
        "status": "passed",
        "source_candidate_commit": source_candidate_commit,
        "evidence_package_digest": package_digest,
        "evidence_package_ref": f"sha256:{package_digest}",
        "sidecar_ref": _evidence_ref(root, scanned),
        "report_ref": REPORT_REF.as_posix(),
        "receipt_ref": RECEIPT_REF.as_posix(),
        "visual_review_receipt_digest": receipt_digest,
        "scenario_ids": list(SCENARIO_IDS),
        "scanned_artifact_count": len(scanned),
    }


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.health_check:
            _write_json(sys.stdout, _health())
            return 0
        result = _validate(
            arguments.source_candidate_commit,
            arguments.evidence_dir,
            arguments.marked_secret,
        )
    except Exception:
        _write_json(
            sys.stderr,
            {
                "schema_version": "scenarioforge.candidate-delivery-error/v2",
                "status": "failed",
                "error_code": "candidate_evidence_invalid",
            },
        )
        return 2
    _write_json(sys.stdout, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
