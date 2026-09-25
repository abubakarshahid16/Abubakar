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


# --------------------------------------------------- the live checkout
#
# Owner rule 2026-09-25, after a session did branch work in the MAIN working
# tree - the checkout the live server runs from - 16 times in one day (git
# reflog), instead of in isolated worktrees. The main working tree must stay
# on `main`. Git has no pre-checkout hook, so `.githooks/post-checkout` calls
# `enforce_live_checkout`: a checkout/switch there to anything but `main` is
# reported as REFUSED and switched straight back. Linked worktrees (every
# `.claude/worktrees/*`) are not affected - that is where branch work belongs.

LIVE_BRANCH = "main"


def is_main_working_tree(cwd: Path) -> bool:
    """True in the repository's MAIN working tree, False in a linked
    worktree. A linked worktree has its own git dir under the common one."""
    git_dir = Path(_git(cwd, "rev-parse", "--path-format=absolute", "--git-dir")).resolve()
    common = Path(_git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    return git_dir == common


def live_checkout_violation(cwd: Path) -> str | None:
    """A refusal message when the main working tree is not on `main`."""
    if not is_main_working_tree(cwd):
        return None
    branch = _git(cwd, "branch", "--show-current")
    if branch == LIVE_BRANCH:
        return None
    return (f"REFUSED: the main working tree ({cwd}) is the LIVE checkout and must "
            f"stay on '{LIVE_BRANCH}', but it was switched to "
            f"'{branch or 'a detached HEAD'}'. Do branch work in a worktree: "
            f"git worktree add .claude/worktrees/<name> -b <branch> main")


def enforce_live_checkout(cwd: Path) -> int:
    """Post-checkout action: 0 when nothing is wrong; otherwise say so and
    switch the main working tree back to `main` (1), or say loudly that it
    could not (2) - never silently."""
    import sys
    message = live_checkout_violation(cwd)
    if message is None:
        return 0
    print(message, file=sys.stderr)
    back = subprocess.run(["git", "checkout", LIVE_BRANCH], cwd=cwd,
                          capture_output=True, text=True)
    if back.returncode != 0:
        print(f"COULD NOT switch back to '{LIVE_BRANCH}' - fix this by hand now: "
              f"{back.stderr.strip()}", file=sys.stderr)
        return 2
    print(f"Switched the live checkout back to '{LIVE_BRANCH}'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--post-checkout"]:
        raise SystemExit(enforce_live_checkout(Path.cwd()))
    if len(sys.argv) != 3:
        print("usage: worktree_guard.py <expected_dir_name> <expected_branch>\n"
              "       worktree_guard.py --post-checkout", file=sys.stderr)
        raise SystemExit(2)
    try:
        assert_worktree(sys.argv[1], sys.argv[2])
    except WorktreeMismatch as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    print("worktree check ok")
