"""A worktree test runner that silently tests the wrong copy of a file is
worse than one that fails to run at all: on 2026-09-24 a saved PowerShell
runner hardcoded to the b4-extraction worktree was reused unmodified against
the b5-standards worktree, and it happily reported "186 passed" for the
UNMODIFIED b4-extraction copy of the file that had actually been edited in
b5-standards. It was caught only because the environment's own working-
directory banner disagreed with the worktree just edited - the runner itself
detected nothing.

`assert_worktree` is the fix: every runner calls it, with the worktree
directory name and branch it was written for, before invoking pytest. A
mismatch is a refusal, not a warning.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class WorktreeMismatch(RuntimeError):
    """Raised when the resolved worktree does not match what the caller expected."""


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def resolve_worktree(cwd: Path) -> tuple[str, str]:
    """The current git worktree's top-level directory NAME and branch, as seen
    from `cwd`. Raises if `cwd` is not inside a git working tree."""
    toplevel = Path(_git(cwd, "rev-parse", "--show-toplevel"))
    branch = _git(cwd, "branch", "--show-current")
    return toplevel.name, branch


def assert_worktree(expected_dir_name: str, expected_branch: str,
                     cwd: Path | None = None) -> None:
    """Refuse to proceed unless `cwd` (default: the process cwd) sits inside
    the git worktree named `expected_dir_name` on branch `expected_branch`.

    A test runner calls this BEFORE invoking pytest, so a mismatch stops the
    run instead of silently testing the wrong worktree's copy of a file."""
    cwd = cwd or Path.cwd()
    actual_dir_name, actual_branch = resolve_worktree(cwd)
    if actual_dir_name != expected_dir_name or actual_branch != expected_branch:
        raise WorktreeMismatch(
            f"refusing to run: this runner is written for worktree "
            f"'{expected_dir_name}' on branch '{expected_branch}', but "
            f"{cwd} resolves to worktree '{actual_dir_name}' on branch "
            f"'{actual_branch}'. Fix the runner's expected values or run it "
            f"from the correct worktree - do not ignore this."
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("usage: worktree_guard.py <expected_dir_name> <expected_branch>",
              file=sys.stderr)
        raise SystemExit(2)
    try:
        assert_worktree(sys.argv[1], sys.argv[2])
    except WorktreeMismatch as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    print("worktree check ok")
