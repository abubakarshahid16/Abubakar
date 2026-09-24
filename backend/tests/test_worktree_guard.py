"""A worktree test runner that does not check where it landed can silently
test the wrong worktree's copy of a file and report success - this happened
for real on 2026-09-24 (see scripts/worktree_guard.py's docstring). These
tests prove the guard actually refuses on a mismatch, on each axis
separately, rather than only checking the happy path."""
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from worktree_guard import WorktreeMismatch, assert_worktree, resolve_worktree


def _init_repo(path: pathlib.Path, branch: str) -> None:
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                    cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    (path / "placeholder.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_resolve_worktree_reads_the_real_directory_name_and_branch(tmp_path):
    repo = tmp_path / "b5-standards"
    repo.mkdir()
    _init_repo(repo, "b5-standards-branch")
    dir_name, branch = resolve_worktree(repo)
    assert dir_name == "b5-standards"
    assert branch == "b5-standards-branch"


def test_a_matching_worktree_and_branch_is_accepted(tmp_path):
    repo = tmp_path / "b5-standards"
    repo.mkdir()
    _init_repo(repo, "b5-standards-branch")
    assert_worktree("b5-standards", "b5-standards-branch", cwd=repo)  # no raise


def test_the_wrong_worktree_directory_is_refused(tmp_path):
    """THE CASE THAT CAUGHT THE REAL BUG: a script written for b5-standards,
    run from a directory that resolves to a different worktree entirely."""
    repo = tmp_path / "b4-extraction"
    repo.mkdir()
    _init_repo(repo, "b5-standards-branch")
    with pytest.raises(WorktreeMismatch, match="b5-standards"):
        assert_worktree("b5-standards", "b5-standards-branch", cwd=repo)


def test_the_right_worktree_on_the_wrong_branch_is_also_refused(tmp_path):
    """Same directory name is not enough on its own - a worktree left
    checked out to the wrong branch must be refused too."""
    repo = tmp_path / "b5-standards"
    repo.mkdir()
    _init_repo(repo, "main")
    with pytest.raises(WorktreeMismatch, match="main"):
        assert_worktree("b5-standards", "b5-standards-branch", cwd=repo)
