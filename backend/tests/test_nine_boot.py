"""Every module of the nine-role job registers its templates, vocabularies and id sources at IMPORT, and the registries freeze at app start
(`nine_call.freeze`): with the switch ON the app must import them all before that, with the switch OFF nothing nine-role is imported."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROBE = """
import json
from app import nine_call
import app.main  # noqa: F401
have = sorted(nine_call._TEMPLATES)
import sys
print(json.dumps({"templates": have, "job": "app.nine_job" in sys.modules, "frozen_after_start": nine_call._FROZEN}))
"""


def run(switch: str) -> dict:
    env = {
        **os.environ,
        "AGENT_REVIEW_NINE_ROLES_ENABLED": switch,
        "AGENT_REVIEW_ENABLED": "true",
        "PYTHONPATH": str(BACKEND),
    }
    out = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-800:]
    import json

    return json.loads(out.stdout.strip().splitlines()[-1])


def test_with_the_switch_on_every_role_module_has_registered_before_the_app_starts():
    got = run("true")
    assert got["job"] is True
    for template in (
        "nine_writer_question",
        "nine_writer_system",
        "nine_reviewer_question",
        "nine_reviewer_system",
    ):
        assert template in got["templates"], template


def test_with_the_switch_off_nothing_nine_role_is_imported_by_the_app():
    got = run("false")
    assert got["job"] is False
