from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_REQUIREMENT = "PyYAML==6.0.3"
EXPECTED_VERSION = "6.0.3"


def _assert_exact_yaml_lock(project_text: str, lock_text: str) -> None:
    project = tomllib.loads(project_text)
    lock = tomllib.loads(lock_text)

    dependencies = project["project"]["dependencies"]
    yaml_requirements = [
        dependency
        for dependency in dependencies
        if dependency.lower().startswith("pyyaml")
    ]
    assert yaml_requirements == [EXPECTED_REQUIREMENT]

    yaml_packages = [
        package
        for package in lock["package"]
        if package["name"].lower() == "pyyaml"
    ]
    assert [package["version"] for package in yaml_packages] == [
        EXPECTED_VERSION
    ]

    scenarioforge = [
        package for package in lock["package"] if package["name"] == "scenarioforge"
    ]
    assert len(scenarioforge) == 1
    locked_dependencies = [
        dependency["name"]
        for dependency in scenarioforge[0]["dependencies"]
        if dependency["name"].lower() == "pyyaml"
    ]
    assert locked_dependencies == ["pyyaml"]

    required = scenarioforge[0]["metadata"]["requires-dist"]
    yaml_metadata = [
        item
        for item in required
        if item["name"].lower() == "pyyaml"
    ]
    assert yaml_metadata == [
        {"name": "pyyaml", "specifier": f"=={EXPECTED_VERSION}"}
    ]


def test_yaml_dependency_is_exact_and_uniquely_resolved() -> None:
    _assert_exact_yaml_lock(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        (ROOT / "uv.lock").read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize(
    ("project_mutation", "lock_mutation"),
    [
        (lambda text: text.replace(f'  "{EXPECTED_REQUIREMENT}",\n', ""), lambda text: text),
        (
            lambda text: text.replace(EXPECTED_REQUIREMENT, "PyYAML>=6.0.3"),
            lambda text: text,
        ),
        (
            lambda text: text,
            lambda text: text.replace(
                'name = "pyyaml"\nversion = "6.0.3"',
                'name = "pyyaml"\nversion = "6.0.2"',
                1,
            ),
        ),
        (
            lambda text: text,
            lambda text: text
            + '\n[[package]]\nname = "pyyaml"\nversion = "6.0.2"\n',
        ),
    ],
)
def test_dependency_verifier_rejects_missing_nonexact_or_divergent_versions(
    project_mutation: object,
    lock_mutation: object,
) -> None:
    project_text = project_mutation(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    lock_text = lock_mutation((ROOT / "uv.lock").read_text(encoding="utf-8"))

    with pytest.raises(AssertionError):
        _assert_exact_yaml_lock(project_text, lock_text)
