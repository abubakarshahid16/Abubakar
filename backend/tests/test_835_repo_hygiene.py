"""#835 / order 68: repo hygiene before the Mac move.

* Line endings stay LF in the repository (`* text=auto eol=lf`): a Windows
  editor once left 16 files showing one-line, whitespace-only diffs.
* Proof and scratch output that once landed in the tree is ignored, and no
  tracked file matches those patterns.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STRAYS = ["pump_elapsed.txt", "rehearsal_v9.py", "rehearsal_v9.json", "rehearsal_v9.txt",
          "backend/rehearsal_out.json", "frontend/dash-body.txt", "docs/review-command.md"]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)


def test_text_files_are_stored_lf():
    lines = (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "* text=auto eol=lf" in [line.strip() for line in lines]


@pytest.mark.parametrize("path", STRAYS)
def test_a_stray_proof_file_is_ignored(path):
    assert _git("check-ignore", "-q", "--no-index", path).returncode == 0, path


def test_a_real_script_is_not_ignored():
    """The patterns are anchored: a tracked script whose name starts the same
    way (scripts/rehearse_requirement_reextraction.py) stays visible."""
    assert _git("check-ignore", "-q", "--no-index", "scripts/rehearse_requirement_reextraction.py").returncode == 1


def test_no_tracked_file_is_a_stray():
    """None of the patterns added for #835 hides a file the repository tracks
    (checked per tracked path against exactly those patterns)."""
    tracked = _git("ls-files").stdout.splitlines()

    def stray(path: str) -> bool:
        name = path.rsplit("/", 1)[-1]
        top = "/" not in path or path.startswith("backend/") and path.count("/") == 1
        return (name.endswith("_elapsed.txt")
                or (top and name.startswith("rehearsal") and name.rsplit(".", 1)[-1] in ("py", "json", "txt"))
                or path in ("frontend/dash-body.txt", "docs/review-command.md"))

    assert [p for p in tracked if stray(p)] == []


def test_no_tracked_text_file_is_stored_with_crlf():
    """13 files were committed with mixed line endings, so every checkout on
    every machine showed them as modified (the '16 changed files' of 18 Oct).
    They are renormalised to LF; this keeps it that way."""
    rows = _git("ls-files", "--eol").stdout.splitlines()
    bad = [row.split()[-1] for row in rows if row.split()[0] in ("i/crlf", "i/mixed")]
    assert bad == [], bad
