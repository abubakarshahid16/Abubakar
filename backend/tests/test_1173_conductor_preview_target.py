"""#1173 review blocker: the Conductor "screens" preview never talks to the
live app's server (port 8000) unless PREVIEW_AGAINST_LIVE=1 is set on
purpose. A workspace's screens are unmerged code; a click in them would
write the owner's real reviews.

The real script runs with a fake `npx` on PATH that only prints the server
it was given, so nothing starts.

MUTATION PROOF (by hand once): restore the old default
`VITE_API_TARGET=${VITE_API_TARGET:-http://127.0.0.1:8000}` and the first
two tests fail; drop the port-8000 case and the third fails.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "conductor" / "run-screens.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="a bash script for the Mac's Conductor workspaces",
)


def _run(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    (tmp_path / "frontend").mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "npx"
    fake.write_text('#!/bin/bash\necho "VITE STARTED target=$VITE_API_TARGET"\n')
    fake.chmod(0o755)
    base = {k: v for k, v in os.environ.items()
            if k not in ("VITE_API_TARGET", "PREVIEW_AGAINST_LIVE")}
    base.update(PATH=f"{bin_dir}{os.pathsep}{base.get('PATH', '')}",
                CONDUCTOR_WORKSPACE_PATH=str(tmp_path), CONDUCTOR_PORT="5199", **env)
    return subprocess.run(["bash", str(SCRIPT)], env=base, capture_output=True, text=True, timeout=30)


def test_no_server_chosen_does_not_start(tmp_path):
    out = _run(tmp_path)
    assert out.returncode == 2
    assert "VITE STARTED" not in out.stdout
    assert "no server chosen" in out.stderr


def test_a_target_on_the_live_port_is_refused_without_the_flag(tmp_path):
    for target in ("http://127.0.0.1:8000", "http://localhost:8000/", "http://0.0.0.0:8000"):
        out = _run(tmp_path, VITE_API_TARGET=target)
        assert out.returncode == 2, target
        assert "VITE STARTED" not in out.stdout, target
        assert "live app's port" in out.stderr, target


def test_the_live_app_only_on_purpose_and_with_a_warning(tmp_path):
    out = _run(tmp_path, PREVIEW_AGAINST_LIVE="1")
    assert out.returncode == 0
    assert "VITE STARTED target=http://127.0.0.1:8000" in out.stdout
    assert "WARNING" in out.stdout and "LIVE" in out.stdout


def test_a_workspace_backend_starts_without_a_warning(tmp_path):
    out = _run(tmp_path, VITE_API_TARGET="http://127.0.0.1:8011")
    assert out.returncode == 0
    assert "VITE STARTED target=http://127.0.0.1:8011" in out.stdout
    assert "WARNING" not in out.stdout


def test_a_flag_other_than_1_is_not_consent(tmp_path):
    for flag in ("yes", "true", "0", ""):
        out = _run(tmp_path, PREVIEW_AGAINST_LIVE=flag)
        assert out.returncode == 2, flag
        assert "VITE STARTED" not in out.stdout, flag
