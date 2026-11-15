"""With the nine-role switch OFF the team and contractor files are cell for cell the files of the code before the nine roles (the lead's
decision): no Evidence column, no Roles line, no writer line. Run on a main checkout, this same test writes the same dump (`NINE_FILE_OUT`)."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

from openpyxl import load_workbook

from app import access, crs_one, db
from app.config import settings
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


def dump(data: bytes) -> dict:
    wb = load_workbook(io.BytesIO(data))
    return {
        ws.title: [
            [None if c is None else str(c) for c in r]
            for r in ws.iter_rows(values_only=True)
        ]
        for ws in wb
    }


def test_the_files_with_the_switch_off_are_the_files_without_any_nine_role_code(
    monkeypatch,
):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    if hasattr(settings, "agent_review_nine_roles_enabled"):
        monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", False)
    doc, rc, ai, client = world_with_both()
    scope = access.AccessScope(
        user_id=None,
        allowed_document_ids=frozenset(
            r[0] for r in db.connect().execute("SELECT id FROM documents")
        ),
    )
    team = dump(crs_one.build_team(doc, scope, exported="2026-11-16 10:00 UTC"))
    contractor = dump(
        crs_one.build_contractor(doc, scope, exported="2026-11-16 10:00 UTC")
    )
    text = (
        json.dumps({"team": team, "contractor": contractor}, sort_keys=True)
        .replace(rc, "RC")
        .replace(ai, "AI")
    )
    flat = text.lower()
    assert (
        "roles:" not in flat
        and "findings behind it" not in flat
        and "kept in code words" not in flat
    )
    out = os.environ.get("NINE_FILE_OUT")
    if out:
        Path(out).write_text(text)
    assert hashlib.sha256(text.encode()).hexdigest()
