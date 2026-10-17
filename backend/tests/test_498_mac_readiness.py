"""#498 Mac readiness: the code runs on macOS (Apple Silicon) as on the Windows PC.

What is checked here, without a Mac:
  * no hard-coded Windows path (a drive letter, `.venv\\Scripts`) in a string
    the code USES - backend, tools, scripts, eval - except the heavy-job lock's
    owner-named Windows default, which only applies when `os.name == "nt"`;
  * every path setting is built from the code's own location (BACKEND_DIR),
    never a drive path, so a Mac checkout finds its own data and models;
  * the heavy-job lock falls back to the temp folder away from Windows;
  * no PowerShell script, and every Windows launcher (`.bat`) has a POSIX twin.
Comments and docstrings may show Windows examples; only live strings count.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import heavy_lock
from app.config import BACKEND_DIR, Settings

REPO = Path(__file__).resolve().parents[2]
#: A drive letter that STARTS a path (string start, or after a space, quote or
#: "="), or a Windows venv interpreter. "(?i:\b" in a regex is not a path.
WINDOWS_PATH = re.compile(r"(?:^|[\s\"'=])[A-Za-z]:[\\/]+[A-Za-z]|\.venv[\\/]+Scripts", re.IGNORECASE)
#: (file, string): the ONE allowed Windows path, guarded by `os.name == "nt"`.
ALLOWED = {("backend/app/heavy_lock.py", "D:/project/.heavy-job.lock")}


def _tracked(*patterns: str) -> list[Path]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", *patterns], capture_output=True, text=True)
    return [REPO / line for line in out.stdout.splitlines() if (REPO / line).exists()]


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _live_strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            yield node.lineno, node.value


def test_no_live_string_holds_a_windows_path():
    found = []
    for path in _tracked("backend/app/*.py", "backend/tools/*.py", "backend/run.py", "scripts/*.py", "eval/*.py",
                         "eval/**/*.py"):
        rel = path.relative_to(REPO).as_posix()
        for line, text in _live_strings(path):
            if WINDOWS_PATH.search(text) and (rel, text) not in ALLOWED:
                found.append(f"{rel}:{line}")
    assert found == [], found


def test_the_scanner_catches_what_it_is_for(tmp_path):
    """Not vacuous: a planted drive path and a planted venv path are found."""
    planted = tmp_path / "planted.py"
    planted.write_text('"""C:\\\\docs may show a Windows path"""\n'
                       'DB = r"d:\\\\project\\\\x.sqlite"\nPY = ".venv/Scripts/python.exe"\n'
                       'RX = r"(?i:\\bclass)"\n', encoding="utf-8")
    hits = [line for line, text in _live_strings(planted) if WINDOWS_PATH.search(text)]
    assert hits == [2, 3]


def test_every_path_setting_is_built_from_the_code_location():
    settings = Settings()
    paths = {name: getattr(settings, name) for name, field in Settings.model_fields.items()
             if isinstance(getattr(settings, name), Path)}
    assert len(paths) >= 5, paths
    for name, value in paths.items():
        assert Path(value).resolve().is_relative_to(BACKEND_DIR.resolve()), (name, value)


def test_the_heavy_job_lock_uses_the_temp_folder_away_from_windows(monkeypatch):
    monkeypatch.setattr(heavy_lock, "os", SimpleNamespace(name="posix", environ={}))
    path = heavy_lock.lock_path()
    assert path.name == "rag-intelligence-heavy-job.lock" and "project" not in path.parts


def test_no_powershell_script_and_every_launcher_has_a_posix_twin():
    assert _tracked("*.ps1") == []
    for bat in _tracked("*.bat"):
        assert bat.with_suffix(".sh").exists(), f"{bat.name} has no .sh twin for macOS / Linux"
