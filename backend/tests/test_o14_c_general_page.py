"""Order 14 lane C (17 Nov 2026): a general review's lines keep their page in every home, and two comments on two different clauses
of one book are two topics. Invented data only: no client paper, no real book text, invented book names (STD-A-100 ...)."""

from __future__ import annotations

import importlib.util
import io
import sys
import uuid
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app import agent_general_crs, agent_general_job, agent_review_schema, crs_one, db
from app import agent_general_review as core
from app.config import settings
from tests.test_crs_endpoint import NOW, _submittal, temp_db  # noqa: F401 - fixture
from tests.test_k4_one_crs import rows_after, scope_all

_SPEC = importlib.util.spec_from_file_location(
    "crs_gates", Path(__file__).resolve().parents[2] / "scripts" / "crs_gates.py"
)
g = importlib.util.module_from_spec(_SPEC)
sys.modules["crs_gates"] = g  # the dataclasses look their module up by name
_SPEC.loader.exec_module(g)

QUOTE = "The invented review interval is set at every twelve months by the area lead."


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)


def _lines(doc: str) -> list[dict]:
    note = {"item_id": "G-1", "part": 5, "verdict_class": core.CLASS_NOTE, "word": "AI note", "subkind": core.SUB_ENGINEERING,
            "document": doc, "text": "invented comment on the interval", "quotes_verified_by_code": True,
            "quote_a": {"document": doc, "page": 3, "text": QUOTE}, "quote_b": None}  # fmt: skip
    query = {"item_id": "G-2", "part": 2, "verdict_class": core.CLASS_QUERY, "word": "Query", "document": doc, "topic": "invented topic",
             "checklist_item": "G-2", "text": "checklist: invented topic: not found in the paper", "reason": "not found"}  # fmt: skip
    # a quote whose page code did NOT verify: its page is never shown (never a guessed page)
    unverified = {**note, "item_id": "G-3", "text": "invented second comment", "quotes_verified_by_code": False,
                  "quote_a": {"document": doc, "page": 4, "text": "words the paper does not hold"}}  # fmt: skip
    return [note, query, unverified]


def general_world() -> tuple[str, str, list[dict]]:
    """An invented finished GENERAL review of a procedure: three lines stored by the general review's own writer."""
    agent_review_schema.ensure_schema()
    doc, run_id = _submittal("doc_proc", "procedure.pdf"), str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, started_at)"
                     " VALUES (?,?,?,?,?,?)", (run_id, doc, "completed", NOW, NOW, NOW))  # fmt: skip
        conn.execute("INSERT INTO agent_review_run (run_id, submittal_document_id, paper_kind, kind_source, usd, started_at)"
                     " VALUES (?,?,?,?,?,?)", (run_id, doc, "procedure", "test", 0.0, NOW))  # fmt: skip
        conn.execute("INSERT INTO agent_review_general (run_id) VALUES (?)", (run_id,))
    lines = _lines(doc)
    agent_general_job.store_lines(db.connect(), run_id, lines)
    return doc, run_id, lines


def _ai_pages(data: bytes, sheet: str, first: str, page_col: str) -> list:
    head, rows = rows_after(load_workbook(io.BytesIO(data))[sheet], first)
    return sorted(
        str(r[head.index(page_col)])
        for r in rows
        if "AI review" in [str(c) for c in r] or sheet == crs_one.TEAM_SHEET
    )


def test_a_general_lines_stored_page_shows_in_the_team_file_and_none_is_never_guessed():
    doc, run_id, _ = general_world()
    stored = dict(
        db.connect()
        .execute(
            "SELECT item_id, page FROM agent_review_line WHERE run_id = ?", (run_id,)
        )
        .fetchall()
    )
    assert stored == {
        "G-1": 3,
        "G-2": None,
        "G-3": None,
    }  # the column holds the verified page only
    data = crs_one.build_team(doc, scope_all())
    assert _ai_pages(data, crs_one.EVIDENCE_SHEET, "No", "Page") == [
        "3",
        "not recorded",
        "not recorded",
    ]
    assert _ai_pages(data, crs_one.TEAM_SHEET, "Comment", "Pages") == [
        "3",
        "not recorded",
        "not recorded",
    ]


def test_the_run_file_shows_the_same_page_as_the_team_file():
    _doc, _run, lines = general_world()
    assert [agent_general_crs._page_text(ln) for ln in lines] == [
        agent_general_crs._page_cell(3),
        None,
        None,
    ]


# ------------------------------------------------------------------------------------------------ G4: a clause written "cl. N (p.M)"


def test_a_book_name_with_cl_and_its_page_bracket_is_read_as_book_and_clause():
    assert g.split_fused("STD-A-100 (edition not recorded) cl. 5.6.2 (p.23)") == (
        "STD-A-100 (edition not recorded)",
        "5.6.2",
    )
    assert g.split_fused("std-a-100 (2020) cl. 6.1 (page 4)") == (
        "std-a-100 (2020)",
        "6.1",
    )
    assert g.split_fused("STD-A-100 (edition not recorded) (p.23)") == (
        "STD-A-100 (edition not recorded) (p.23)",
        "",
    )


def test_g4_two_clauses_of_one_book_are_two_topics_and_one_clause_twice_fails():
    a = g.Row(
        "C1", field="api 9999 (edition not recorded) cl. 5.6.2 (p.23)", book="API 9999"
    )
    b = g.Row(
        "C2", field="api 9999 (edition not recorded) cl. 6.1.6 (p.25)", book="API 9999"
    )
    same = g.Row(
        "C3", field="API 9999 (edition not recorded) cl. 5.6.2 (p.24)", book="API 9999"
    )
    assert g.key_of(a) != g.key_of(b) and g.key_of(a) == g.key_of(same)
    assert g.g4_one_per_field([a, b]).failed == []
    assert [i for i, _w in g.g4_one_per_field([a, b, same]).failed] == ["C1", "C3"]
