"""The pre-commit hook lets an invented PDF into ONE folder and no other.

Owner decision, 12 Oct (planner's note on #692, part of #830): the hook's
allow-list named `tests/fixtures/synthetic/`, a folder this repository does
not have - its invented fixtures live under `backend/tests/fixtures/synthetic/`
- so a new invented datasheet could not be committed at all. The allow-list
now names exactly that folder (the one the CI guard already names). The
client-document block stays for every other path: one folder outside it a PDF
is still refused.

The REAL hook is installed into a throwaway repository (the pattern of
test_client_identifier_hook.py); the "PDF" is a few made-up bytes.
"""
import pathlib

import pytest

from tests.test_client_identifier_hook import _committed, _git, _repo

PDF = b"%PDF-1.4 invented"


def _commit_pdf(repo: pathlib.Path, env: dict, name: str):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PDF)
    _git(repo, "add", name, env=env)
    run = _git(repo, "commit", "-m", "add a pdf", env=env)
    return run, run.stdout + run.stderr


def test_an_invented_pdf_in_the_synthetic_folder_is_accepted(tmp_path):
    repo, env = _repo(tmp_path, None)
    run, out = _commit_pdf(repo, env, "backend/tests/fixtures/synthetic/datasheets/ds99_invented.pdf")
    assert run.returncode == 0, out
    assert _committed(repo) == 1


@pytest.mark.parametrize("name", [
    "backend/tests/fixtures/ds99.pdf",                       # one folder outside it
    "backend/tests/fixtures/real/synthetic/ds99.pdf",
    "backend/tests/ds99.pdf",
    "docs/backend/tests/fixtures/synthetic/ds99.pdf",        # the folder's name deeper in a path
    "tests/fixtures/synthetic/ds99.pdf",                     # the old entry: no such folder here
    "backend/data/ds99.pdf",
    "ds99.pdf",
])
def test_a_pdf_anywhere_else_is_still_refused(tmp_path, name):
    repo, env = _repo(tmp_path, None)
    run, out = _commit_pdf(repo, env, name)
    assert run.returncode != 0, out
    assert "BLOCKED: forbidden file type staged" in out
    assert _committed(repo) == 0
