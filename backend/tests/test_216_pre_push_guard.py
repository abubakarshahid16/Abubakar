"""Order 216: the pre-push guard refuses a badly formatted push and passes a clean one.

Each case builds a throwaway git repository (a copy of `quality_ratchet.py`
and `ruff.toml`, an `origin/main` ref, a branch with one new Python file) and
runs the real `scripts/pre_push_guard.py` logic on it. Nothing here touches
the working repository, the network or a model.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "pre_push_guard", REPO / "scripts" / "pre_push_guard.py"
)
guard = importlib.util.module_from_spec(spec)
sys.modules["pre_push_guard"] = guard
spec.loader.exec_module(guard)

needs_ruff = pytest.mark.skipif(
    not guard.has_ruff(sys.executable), reason="ruff 0.16.6 not installed here"
)
BAD = "def f( a,b ):\n    return {'a':a,\n        'b':b}\n"
CLEAN = 'def f(a, b):\n    return {"a": a, "b": b}\n'


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "quality_ratchet.py", tmp_path / "scripts")
    shutil.copy(REPO / "ruff.toml", tmp_path)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(tmp_path, "checkout", "-q", "-b", "work")
    (tmp_path / "backend" / "app").mkdir(parents=True)
    return tmp_path


def _commit(root: Path, name: str, text: str) -> None:
    (root / "backend" / "app" / name).write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "work")


def _format_step_only(monkeypatch):
    """Run the real format-check step; the other checks need the full repository."""
    real = guard.plan
    monkeypatch.setattr(
        guard,
        "plan",
        lambda files, python, root=guard.REPO: real(files, python, root)[:1],
    )
    monkeypatch.setattr(guard, "find_python", lambda root=guard.REPO: sys.executable)


@needs_ruff
def test_a_badly_formatted_new_file_is_refused_and_the_fix_is_named(
    repo, monkeypatch, capsys
):
    _commit(repo, "bad.py", BAD)
    _format_step_only(monkeypatch)
    assert guard.main(["--root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert (
        "REFUSED" in out
        and "formatting of the lines this branch touched" in out
        and "bad.py" in out
    )


@needs_ruff
def test_a_clean_file_passes(repo, monkeypatch, capsys):
    _commit(repo, "clean.py", CLEAN)
    _format_step_only(monkeypatch)
    assert guard.main(["--root", str(repo)]) == 0
    assert "pre-push: ok" in capsys.readouterr().out


def test_missing_ruff_refuses_loudly_never_silently(repo, monkeypatch, capsys):
    _commit(repo, "x.py", CLEAN)
    monkeypatch.setattr(guard, "find_python", lambda root=guard.REPO: None)
    assert guard.main(["--root", str(repo)]) == 1
    assert "No Python with ruff" in capsys.readouterr().out


def test_a_branch_with_no_python_change_needs_no_ruff(repo, monkeypatch, capsys):
    (repo / "notes.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "notes")
    monkeypatch.setattr(guard, "find_python", lambda root=guard.REPO: None)
    assert guard.main(["--root", str(repo)]) == 0


def test_a_branch_behind_main_gets_a_warning_not_a_block(repo, monkeypatch, capsys):
    _git(repo, "checkout", "-q", "main")
    (repo / "later.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "main moved")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-q", "work")
    (repo / "notes.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "notes")
    assert guard.main(["--root", str(repo)]) == 0
    assert "behind origin/main" in capsys.readouterr().out


def test_without_origin_main_it_says_so_and_does_not_pretend(tmp_path, capsys):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    assert guard.main(["--root", str(tmp_path)]) == 0
    assert "not found, nothing checked" in capsys.readouterr().out


def test_each_kind_of_change_selects_its_checks(tmp_path):
    names = lambda files: [s[0] for s in guard.plan(files, "py", tmp_path)]  # noqa: E731
    assert names(["README.md"]) == []
    py = names(["backend/app/x.py"])
    assert (
        py[0].startswith("formatting")
        and "mutation anchors" in py
        and "contract types" not in py
    )
    assert "contract types" in names(["contracts/types.ts", "backend/app/x.py"])
    assert (
        names(["frontend/src/a.tsx"]) == []
    )  # no node_modules here: skipped, not failed
