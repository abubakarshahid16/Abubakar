"""A worktree test runner that does not check where it landed can silently
test the wrong worktree's copy of a file and report success - this happened
for real on 2026-09-24 (see scripts/worktree_guard.py's docstring). These
tests prove the guard actually refuses on a mismatch, on each axis
separately, rather than only checking the happy path."""
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from worktree_guard import (WorktreeMismatch, assert_worktree, live_checkout_violation,
                            resolve_worktree)


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


# ------------------------------------------ the live checkout stays on main
#
# Owner rule 2026-09-25: the MAIN working tree is the live checkout. These run
# against real throwaway repositories; the e2e ones install the REAL hook from
# this repository's .githooks/ and the REAL scripts/worktree_guard.py.


def test_the_main_working_tree_on_main_is_fine(tmp_path):
    _init_repo(tmp_path, "main")
    assert live_checkout_violation(tmp_path) is None


def test_the_main_working_tree_on_another_branch_is_a_violation(tmp_path):
    """THE MUTATION TARGET (M531)."""
    _init_repo(tmp_path, "main")
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=tmp_path, check=True)
    message = live_checkout_violation(tmp_path)
    assert message is not None and "REFUSED" in message and "feature" in message


def test_a_linked_worktree_may_be_on_any_branch(tmp_path):
    main = tmp_path / "live"
    main.mkdir()
    _init_repo(main, "main")
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "feature", str(wt)],
                   cwd=main, check=True)
    assert live_checkout_violation(wt) is None


def _install_hook(repo: pathlib.Path) -> dict:
    hooks = repo / ".githooks"
    hooks.mkdir()
    hook_copy = hooks / "post-checkout"
    hook_copy.write_bytes((REPO / ".githooks" / "post-checkout").read_bytes())
    hook_copy.chmod(0o755)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "worktree_guard.py").write_bytes(
        (REPO / "scripts" / "worktree_guard.py").read_bytes())
    subprocess.run(["git", "config", "core.hooksPath", str(hooks)], cwd=repo, check=True)
    import os
    env = dict(os.environ)
    env["WORKTREE_GUARD_PYTHON"] = sys.executable.replace("\\", "/")
    return env


def _branch(repo: pathlib.Path) -> str:
    return subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                          capture_output=True, text=True, check=True).stdout.strip()


def test_the_hook_switches_the_live_checkout_straight_back_to_main(tmp_path):
    """THE MUTATION TARGET (M532), end to end through the real hook."""
    _init_repo(tmp_path, "main")
    env = _install_hook(tmp_path)
    run = subprocess.run(["git", "checkout", "-b", "feature"], cwd=tmp_path,
                         capture_output=True, text=True, env=env)
    assert _branch(tmp_path) == "main", run.stderr
    assert "REFUSED" in run.stderr


def test_git_pull_on_main_in_the_live_checkout_is_not_refused(tmp_path):
    """Owner check: the live checkout's only routine operation is `git pull
    origin main`. A pull (fetch + fast-forward merge) must still work with the
    hook installed and must never print REFUSED; neither must a
    `git checkout main` while already on main."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    live = tmp_path / "live"
    live.mkdir()
    _init_repo(live, "main")
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=live, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=live, check=True)
    env = _install_hook(live)
    # a second clone pushes a new commit to main
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=other, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=other, check=True)
    (other / "new.txt").write_text("y", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=other, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=other, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=other, check=True)

    pull = subprocess.run(["git", "pull", "origin", "main"], cwd=live,
                          capture_output=True, text=True, env=env)
    assert pull.returncode == 0, pull.stderr
    assert "REFUSED" not in pull.stdout + pull.stderr
    assert (live / "new.txt").exists()
    assert _branch(live) == "main"

    again = subprocess.run(["git", "checkout", "main"], cwd=live,
                           capture_output=True, text=True, env=env)
    assert again.returncode == 0
    assert "REFUSED" not in again.stdout + again.stderr


def test_the_hook_leaves_a_linked_worktree_on_its_branch(tmp_path):
    main = tmp_path / "live"
    main.mkdir()
    _init_repo(main, "main")
    env = _install_hook(main)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "feature", str(wt)],
                   cwd=main, check=True, env=env)
    assert _branch(wt) == "feature"
    assert _branch(main) == "main"
