"""#315: one Claude spend ledger per machine, not one per git worktree.

WHAT WAS WRONG. `claude_spend_log` defaulted to `<this checkout>/backend/data/`.
A script run from a worktree therefore checked the USD 20 total cap against
the worktree's own, nearly empty, ledger - found with USD 7.79 on the main
checkout's ledger and USD 0.08 on the worktree's. The cap was per checkout.

Built on invented directory layouts in a temporary folder; no git needed.
"""
from __future__ import annotations

from pathlib import Path

from app import config
from app.config import shared_backend_dir


def _main_checkout(root: Path) -> Path:
    main = root / "main"
    (main / ".git" / "worktrees" / "wt1").mkdir(parents=True)
    (main / "backend" / "data").mkdir(parents=True)
    return main


def test_a_worktree_shares_the_main_checkouts_backend(tmp_path):
    main = _main_checkout(tmp_path)
    gitdir = main / ".git" / "worktrees" / "wt1"
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp_path / "elsewhere" / "wt1"
    (wt / "backend").mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert shared_backend_dir(wt / "backend") == (main / "backend").resolve()


def test_a_relative_gitdir_and_no_commondir_file_still_resolve(tmp_path):
    main = _main_checkout(tmp_path)
    wt = main / ".worktrees" / "wt1"
    (wt / "backend").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: ../../.git/worktrees/wt1\n", encoding="utf-8")
    assert shared_backend_dir(wt / "backend") == (main / "backend").resolve()


def test_a_normal_checkout_keeps_its_own_backend(tmp_path):
    main = _main_checkout(tmp_path)
    assert shared_backend_dir(main / "backend") == main / "backend"
    bare = tmp_path / "no-git" / "backend"
    bare.mkdir(parents=True)
    assert shared_backend_dir(bare) == bare


def test_a_marker_that_is_not_a_worktree_is_not_followed(tmp_path):
    wt = tmp_path / "odd"
    (wt / "backend").mkdir(parents=True)
    (wt / ".git").write_text("something else\n", encoding="utf-8")
    assert shared_backend_dir(wt / "backend") == wt / "backend"
    # a gitdir whose main checkout has no backend/ is not guessed at
    gitdir = tmp_path / "repo" / ".git" / "worktrees" / "x"
    gitdir.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert shared_backend_dir(wt / "backend") == wt / "backend"


def test_the_ledger_default_uses_the_shared_backend():
    default = config.Settings.model_fields["claude_spend_log"].default
    assert default == shared_backend_dir() / "data" / "claude_spend.jsonl"
