"""The whole app, with the nine-role switch OFF and ON (each in its own process, the switch is read once when `app.main` is imported).

OFF: no `app.nine_*` module and no `app.api.nine_roles` in `sys.modules`, no /roles path in the OpenAPI document.
ON: every role module has registered its templates and vocabularies BEFORE `nine_call.freeze()` runs in the lifespan (shown by really starting
the lifespan, not by reading source text); afterwards a late registration raises."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OFF = """
import json, sys
import app.main as m
bad = sorted(k for k in sys.modules if k.split('.')[-1].startswith('nine_') or k == 'app.api.nine_roles')
paths = [p for p in m.app.openapi()['paths'] if p.endswith('/roles')]
print(json.dumps({"bad": bad, "role_paths": paths}))
"""
ON = """
import json, sys
import app.main as m
from app import nine_call
seen = {}
real = nine_call.freeze
def watching():
    seen["templates_at_freeze"] = sorted(t for t in nine_call._TEMPLATES if t.startswith("nine_"))
    seen["modules_at_freeze"] = sorted(k for k in sys.modules if k in ("app.nine_job", "app.nine_writer", "app.nine_reader", "app.nine_reviewer", "app.nine_context", "app.nine_librarian"))
    seen["frozen_before"] = nine_call._FROZEN
    real()
nine_call.freeze = watching
seen["frozen_at_import"] = nine_call._FROZEN
import os
from pathlib import Path
from app.config import settings
tmp = Path(os.environ["NINE_TMP"])
settings.data_dir, settings.upload_dir, settings.db_path = tmp, tmp / "uploads", tmp / "boot.sqlite"
settings.startup_warmup = False
from app import db
db.reset_connection()
from fastapi.testclient import TestClient
with TestClient(m.app):
    seen["frozen_after_start"] = nine_call._FROZEN
    try:
        nine_call.vocabulary("late_vocab", ["words"])
        seen["late_vocab"] = "accepted"
    except nine_call.NineCallError:
        seen["late_vocab"] = "refused"
    try:
        nine_call.template("late_template", "words")
        seen["late"] = "accepted"
    except nine_call.NineCallError:
        seen["late"] = "refused"
seen["role_paths"] = [p for p in m.app.openapi()["paths"] if p.endswith("/roles")]
print(json.dumps(seen))
"""


def run(code: str, switch: str, tmp: Path | None = None) -> dict:
    env = {
        **os.environ,
        "AGENT_REVIEW_NINE_ROLES_ENABLED": switch,
        "AGENT_REVIEW_ENABLED": "true",
        "AUTH_MODE": "disabled",
        "PYTHONPATH": str(BACKEND),
        **({"NINE_TMP": str(tmp)} if tmp else {}),
    }
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert out.returncode == 0, out.stderr[-1000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_with_the_switch_off_the_whole_app_imports_no_nine_module_and_has_no_roles_route():
    got = run(OFF, "false")
    assert got["bad"] == [] and got["role_paths"] == []


def test_with_the_switch_on_every_role_module_registered_before_the_lifespan_froze_the_registries(
    tmp_path,
):
    got = run(ON, "true", tmp_path)
    assert (
        got["frozen_at_import"] is False and got["frozen_before"] is False
    )  # nothing froze before the lifespan reached `freeze()`
    for template in (
        "nine_writer_question",
        "nine_writer_system",
        "nine_reviewer_question",
        "nine_reviewer_system",
    ):
        assert template in got["templates_at_freeze"], (
            template
        )  # registered by the time `freeze()` ran
    assert {
        "app.nine_job",
        "app.nine_writer",
        "app.nine_reader",
        "app.nine_reviewer",
        "app.nine_context",
        "app.nine_librarian",
    } <= set(got["modules_at_freeze"])
    assert (
        got["frozen_after_start"] is True
        and got["late_vocab"] == "refused"
        and got["late"] == "refused"
    )  # no template or vocabulary can register after the freeze
    assert got["role_paths"]  # the record route exists with the switch on


READER = """
import json, os
from pathlib import Path
import app.main as m
from app.config import settings
tmp = Path(os.environ["NINE_TMP"])
settings.data_dir, settings.upload_dir, settings.db_path = tmp, tmp / "uploads", tmp / "boot.sqlite"
settings.startup_warmup = False
from app import db
db.reset_connection()
from fastapi.testclient import TestClient
from app import datasheet_checks, nine_reader
from app.form_reader_fields import batches, field_list_for
out = {"error": None, "groups": 0}
with TestClient(m.app):
    groups = list(batches(field_list_for("relief valve", dict(datasheet_checks.load_rules()))))
    out["groups"] = len(groups)
    try:
        for g in groups:
            nine_reader.form_template(g)
    except Exception as exc:
        out["error"] = type(exc).__name__
print(json.dumps(out))
"""


def test_the_readers_question_templates_can_be_used_after_the_freeze(tmp_path):
    got = run(READER, "true", tmp_path)
    assert got["groups"] > 0 and got["error"] is None
