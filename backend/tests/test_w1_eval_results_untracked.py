"""W1: eval output must stay out of git.

`eval/results/*.json` holds the corpus file names and up to 600 characters of
passage text per row. Committed, it is a copy of the library's file list (and a
confidential register's name) in a public repository (CLAUDE.md rule 3).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_eval_results_is_git_ignored():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "eval/results/" in [line.strip() for line in lines]


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(),
                    reason="needs a git checkout")
def test_no_eval_result_file_is_tracked():
    out = subprocess.run(["git", "ls-files", "eval/results"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "", f"tracked eval output: {out.split()[:3]}"
