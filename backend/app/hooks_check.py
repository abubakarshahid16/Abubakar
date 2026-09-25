"""Say at boot when this checkout's git hooks are not switched on.

`core.hooksPath` is local git config - a clone does not carry it - and two
guards depend on it: `.githooks/pre-commit` (secret scan, client-data path
checks) and `.githooks/post-checkout` (the live checkout stays on `main`).
Without it both are silently off. The server cannot fix that and must not
refuse to start over it, so it WARNS, in the stream the operator watches.

Owner order 2026-09-25, section 1.3: a log line, not a crash."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = ".githooks"


def _git(repo: Path, *args: str) -> str | None:
    try:
        run = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def hooks_path_warning(repo: Path | None = None) -> str | None:
    """A warning when `repo` (default: this checkout) is a git checkout whose
    core.hooksPath does not resolve to `<top>/.githooks`; None when it does,
    or when `repo` is not a git checkout at all (nothing to guard)."""
    repo = repo or REPO_ROOT
    top = _git(repo, "rev-parse", "--show-toplevel")
    if not top:
        return None
    configured = _git(repo, "config", "--get", "core.hooksPath")
    expected = (Path(top) / EXPECTED).resolve()
    if configured:
        actual = Path(configured)
        if not actual.is_absolute():
            actual = Path(top) / actual
        if actual.resolve() == expected:
            return None
    return (f"core.hooksPath is {configured or 'NOT SET'} in {top} - the pre-commit "
            f"secret scan and the post-checkout live-checkout guard are OFF. Fix: "
            f"git -C \"{top}\" config core.hooksPath {EXPECTED}")
