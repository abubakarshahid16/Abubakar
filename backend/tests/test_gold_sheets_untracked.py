"""Filled gold sheets stay out of Git (CLAUDE.md rule 3, gold/README.md).

A filled gold sheet describes client standards and documents, so only the blank
templates are tracked. Two filled sheets were once tracked as named exceptions in
.gitignore; the repository is public now, and they are untracked. These tests
fail if a filled sheet is tracked again or an exception comes back.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = {"TEMPLATE.csv", "PAIRS-TEMPLATE.csv", "FINDINGS-TEMPLATE.csv", "QUESTIONS-TEMPLATE.csv"}


def _tracked_gold_csvs() -> set[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "gold/"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return {Path(p).name for p in out.splitlines() if p.lower().endswith(".csv")}


def test_only_blank_templates_are_tracked_under_gold():
    extra = _tracked_gold_csvs() - TEMPLATES
    assert not extra, f"{len(extra)} filled gold sheet(s) tracked; untrack with git rm --cached"


def test_gitignore_has_no_exception_for_a_filled_sheet():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    exceptions = {l.strip()[len("!gold/"):] for l in lines if l.strip().startswith("!gold/")}
    assert exceptions <= TEMPLATES, f"{len(exceptions - TEMPLATES)} non-template gold exception(s) in .gitignore"
