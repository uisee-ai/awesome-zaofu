from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_clean_tree_verifier_preserves_tracked_production_dist_and_runs_two_sequences() -> None:
    verifier = PROJECT_ROOT / "scripts/release/verify_candidate_worktree_clean.py"
    source = verifier.read_text(encoding="utf-8")
    ignore_patterns = {
        line.strip()
        for line in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert (PROJECT_ROOT / "web/dist/index.html").is_file()
    assert not any("web/dist" in pattern for pattern in ignore_patterns)
    assert "range(2)" in source
    assert '"npm", "--prefix", "web", "run", "build"' in source
    assert '"npm", "--prefix", "web", "test"' in source
    assert '"git", "status", "--porcelain", "--untracked-files=all"' in source
    assert 'WEB_INDEX = "web/dist/index.html"' in source
    assert '"git", "ls-files", "--error-unmatch", WEB_INDEX' in source
    assert '"git", "ls-files", "--", "web/dist"' in source
    assert "untracked production artifacts" in source
