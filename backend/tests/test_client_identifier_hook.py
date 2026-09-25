"""The pre-commit hook blocks client identifiers read from a LOCAL file.

Owner order 2026-09-25: the identifiers must not live in any tracked file, the
hook included, so `.githooks/pre-commit` reads them from the git-ignored
`.githooks/client-identifiers.local` next to itself. These tests install the
REAL hook into a throwaway repository (the pattern of test_worktree_guard.py)
and commit through it. The patterns used here are made up - a real client
identifier in this file would be exactly what the hook exists to stop.

gitleaks: the hook fails closed when the scanner is missing, which is its own
control and not what is under test here. GITLEAKS_PATH points at a stub that
exits 0, so a blocked commit in these tests can only have been blocked by the
identifier scan.
"""
import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / ".githooks" / "pre-commit"

#: Made up. Shaped like a document number so the regex is a real one.
PATTERN = "FAKE-ID-[0-9]{4}"


def _git(repo: pathlib.Path, *args: str, env: dict | None = None):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, env=env)


def _repo(tmp_path: pathlib.Path, patterns: str | None) -> tuple[pathlib.Path, dict]:
    repo = tmp_path / "repo"
    repo.mkdir()
    # NOT main: section 0 of the hook refuses a direct commit to main.
    subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    hooks = repo / ".githooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_bytes(HOOK.read_bytes())
    if patterns is not None:
        # BYTES, so the line endings are exactly the ones the test wrote -
        # write_text on Windows would turn "\r\n" into "\r\r\n".
        (hooks / "client-identifiers.local").write_bytes(patterns.encode("utf-8"))
    subprocess.run(["git", "config", "core.hooksPath", str(hooks).replace("\\", "/")],
                   cwd=repo, check=True)
    stub = tmp_path / "gitleaks-stub"
    stub.write_bytes(b"#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    env = dict(os.environ)
    env["GITLEAKS_PATH"] = str(stub).replace("\\", "/")
    return repo, env


def _commit(repo: pathlib.Path, env: dict, name: str, text: str):
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name, env=env)
    run = _git(repo, "commit", "-m", f"add {name}", env=env)
    return run, run.stdout + run.stderr


def _committed(repo: pathlib.Path) -> int:
    run = _git(repo, "rev-list", "--count", "HEAD")
    return int(run.stdout.strip()) if run.returncode == 0 else 0


def test_an_added_line_matching_a_local_pattern_is_blocked(tmp_path):
    """THE MUTATION TARGET (M541, M542). A staged line carrying an identifier
    listed only in the local file is refused, and the message names the file
    and the line."""
    repo, env = _repo(tmp_path, f"# comment lines are ignored\n\n{PATTERN}\n")
    run, out = _commit(repo, env, "notes.txt", "see FAKE-ID-0042 page 4\n")
    assert run.returncode != 0, out
    assert "BLOCKED: a client identifier in an added line" in out
    assert "notes.txt" in out and "FAKE-ID-0042" in out
    assert _committed(repo) == 0


def test_a_clean_line_passes_with_the_list_in_place(tmp_path):
    """The other half: the scan is not simply refusing everything."""
    repo, env = _repo(tmp_path, f"{PATTERN}\n")
    run, out = _commit(repo, env, "notes.txt", "see the pump datasheet, page 4\n")
    assert run.returncode == 0, out
    assert "BLOCKED" not in out
    assert _committed(repo) == 1


def test_crlf_and_several_patterns_are_all_read(tmp_path):
    """A list saved by a Windows editor ends its lines in CRLF; a pattern
    carrying a stray `\\r` would never match. Every line counts, not just
    the first or the last."""
    repo, env = _repo(tmp_path, f"OTHER-NAME\r\n{PATTERN}\r\nTHIRD-NAME\r\n")
    run, out = _commit(repo, env, "a.txt", "FAKE-ID-1234\n")
    assert run.returncode != 0 and "FAKE-ID-1234" in out, out
    run, out = _commit(repo, env, "b.txt", "OTHER-NAME\n")
    assert run.returncode != 0 and "OTHER-NAME" in out, out


def test_a_missing_list_is_a_notice_not_a_block(tmp_path):
    """THE MUTATION TARGET (M543). A fresh clone has no local list. The hook
    says so in one line and lets the commit through - a hook that blocked
    every commit for a missing local file would be bypassed until worthless."""
    repo, env = _repo(tmp_path, None)
    run, out = _commit(repo, env, "notes.txt", "see FAKE-ID-0042 page 4\n")
    assert run.returncode == 0, out
    assert "client identifier scan skipped" in out
    assert _committed(repo) == 1


def test_the_tracked_hook_names_no_identifier_list():
    """The list moved OUT of the tracked hook. It must not come back as a
    literal: the hook builds `client_ids` only from the local file."""
    text = HOOK.read_text(encoding="utf-8")
    assert "client-identifiers.local" in text
    assigned = [ln.strip() for ln in text.splitlines()
                if ln.strip().startswith("client_ids=")]
    assert assigned and all(a == "client_ids=''" or "$pattern" in a
                            for a in assigned), assigned
