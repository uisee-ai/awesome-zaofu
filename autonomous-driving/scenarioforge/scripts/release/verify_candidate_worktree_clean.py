"""Verify that the committed production Web build is reproducible and clean."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_INDEX = "web/dist/index.html"
SEQUENCE = (
    ("npm", "--prefix", "web", "run", "build"),
    ("npm", "--prefix", "web", "test"),
)


def _run(command: tuple[str, ...], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _assert_dist_is_tracked() -> None:
    if not (PROJECT_ROOT / WEB_INDEX).is_file():
        raise RuntimeError(f"missing committed production artifact: {WEB_INDEX}")
    _run(("git", "ls-files", "--error-unmatch", WEB_INDEX), capture_output=True)
    tracked = set(_run(("git", "ls-files", "--", "web/dist"), capture_output=True).stdout.splitlines())
    produced = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "web/dist").rglob("*")
        if path.is_file()
    }
    missing = sorted(produced - tracked)
    if missing:
        raise RuntimeError(f"untracked production artifacts: {', '.join(missing)}")
    if not any(path.startswith("web/dist/assets/") for path in produced):
        raise RuntimeError("production build has no hashed assets")


def _assert_clean(sequence_number: int) -> None:
    status = _run(
        ("git", "status", "--porcelain", "--untracked-files=all"),
        capture_output=True,
    ).stdout
    if status:
        raise RuntimeError(f"worktree drift after sequence {sequence_number}:\n{status}")


def main() -> int:
    _assert_dist_is_tracked()
    for sequence_number in range(2):
        for command in SEQUENCE:
            _run(command)
        _assert_dist_is_tracked()
        _assert_clean(sequence_number + 1)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"candidate worktree hygiene failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
