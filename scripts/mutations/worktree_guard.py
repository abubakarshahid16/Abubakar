"""Mutations of `scripts/worktree_guard.py`."""

from __future__ import annotations

from ._base import REPO, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M531", phase=61,
        description="treat every working tree as a linked worktree, so the "
                    "live checkout on a feature branch is never flagged",
        path=REPO / "scripts" / "worktree_guard.py",
        anchor="    return git_dir == common",
        replacement="    return False",
        target="tests/test_worktree_guard.py",
        keyword="the_main_working_tree_on_another_branch_is_a_violation",
        tags=("safety", "live"),
    ),
    Mutation(
        id="M532", phase=61,
        description="report the violation but never switch back, so the "
                    "live checkout stays on the feature branch",
        path=REPO / "scripts" / "worktree_guard.py",
        anchor='    back = subprocess.run(["git", "checkout", LIVE_BRANCH], cwd=cwd,\n'
               '                          capture_output=True, text=True)',
        replacement='    back = subprocess.run(["git", "status"], cwd=cwd,\n'
                    '                          capture_output=True, text=True)',
        target="tests/test_worktree_guard.py",
        keyword="the_hook_switches_the_live_checkout_straight_back_to_main",
        tags=("safety", "live"),
    ),
    Mutation(
        id="M533", phase=61,
        description="flag the live checkout even when it is on main, so a "
                    "routine checkout/pull of main prints REFUSED (slow, "
                    "about 12 min: the mutant re-fires the hook on its own "
                    "switch back to main)",
        path=REPO / "scripts" / "worktree_guard.py",
        anchor="    if branch == LIVE_BRANCH:\n        return None\n",
        replacement="    if branch == 'never-a-branch':\n        return None\n",
        target="tests/test_worktree_guard.py",
        keyword="git_pull_on_main_in_the_live_checkout_is_not_refused",
        tags=("safety", "live"),
    ),
)
