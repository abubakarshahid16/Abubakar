# ruff: noqa: F811
"""A run stored before the engine de-duplicated the not-held list is still SERVED with each standard once, on the page and in the
team file (planner 18 Nov 23:40-7). Invented names only."""

from __future__ import annotations

import json
from io import BytesIO

from openpyxl import load_workbook

from app import db
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import (  # noqa: F401 - fixtures
    BASE,
    BOOK,
    PAPER,
    RUN,
    client,
    world,
)

STORED = [
    {"name": "QX 100 Part II", "why": "governs the equipment type; not held"},
    {"name": "QX 200", "why": "governs the equipment type; not held"},
    {"name": "QX-200", "why": "named by the AI"},  # the same number with a dash
    {
        "name": "QX 100 Pt-2",
        "why": "named by the AI",
    },  # the same part, spelled another way
    {"name": "ZY 300 Invented Title", "why": "named by the AI"},
]


def _store():
    with db.connect() as conn:
        conn.execute(
            "UPDATE aim_runs SET not_held_json = ? WHERE run_id = ?",
            (json.dumps(STORED), RUN),
        )


def test_page_and_team_file_list_each_not_held_standard_once(world):
    _store()
    c = client(PAPER, BOOK)
    page = c.get(f"{BASE}?run_id={RUN}").json()
    names = [n["name"] for n in page["not_held"]]
    assert names == ["QX 100 Part II", "QX 200", "ZY 300 Invented Title"]
    r = c.get(f"{BASE}/sheet?run_id={RUN}")
    assert r.status_code == 200, r.text
    wb = load_workbook(BytesIO(r.content))
    cells = [
        str(v) for ws in wb for row in ws.iter_rows(values_only=True) for v in row if v
    ]
    assert "QX 200" in cells and "QX-200" not in cells and "QX 100 Pt-2" not in cells
    assert [x for x in cells if x.startswith("QX 100")] == ["QX 100 Part II"]
