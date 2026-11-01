"""#645 slice 3: the local model reads a standard's chunks (tables too); CODE
checks every field; what passes is a DRAFT. A fake model stands in for the
local one. Invented clauses only."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import ai_requirement_chunks as arc
from app import ai_requirements as air
from app.config import settings
from app.db import connect
from tests.test_645_clause_checks import Fake
from tests.test_w5_677_scope_ledger import (  # noqa: F401 - fixture
    _chunk,
    _doc,
    temp_storage,
)

TEXT = "The hydrostatic test pressure shall not exceed 10 bar."
TABLE = "Item | Limit\nMax design temperature | 120 degC"


def item(**over) -> dict:
    base = {"quote": "hydrostatic test pressure shall not exceed 10 bar",
            "subject": "hydrostatic test pressure", "operator": "<=", "value": "10",
            "value_to": None, "unit": "bar", "condition": None, "standard": None}
    return {**base, **over}


def reply(*items):
    return {"requirements": list(items)}


@pytest.fixture
def standard(monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_extraction_enabled", True)
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
    _doc("std", "STD-1.pdf", "COMPANY_STANDARD")
    return "std"


def run(model_reply, text=TEXT, *, doc="std", page_end=1):
    _chunk("c1", doc, text)
    with connect() as conn:
        conn.execute("UPDATE chunks SET page_end = ? WHERE id = 'c1'", (page_end,))
    return arc.extract_standard(doc, allowed_document_ids=frozenset({doc}), max_chunks=5,
                                provider=Fake(*([model_reply] * 3)))


def drafts():
    air.ensure_schema()
    return [dict(r) for r in connect().execute("SELECT * FROM clause_check_drafts")]


def test_shall_not_exceed_is_a_verified_draft(standard):
    report = run(reply(item()))
    assert report["proposed"] == 1 and report["refused"] == {}
    [draft] = drafts()
    assert (draft["operator"], draft["value"], draft["unit"], draft["status"]) == ("<=", "10", "bar", "draft")
    assert draft["quote"] in TEXT
    row = connect().execute("SELECT * FROM standard_requirements").fetchone()
    assert row["requirement_type"] == "statement" and row["page"] == 1  # no verdict-bearing limit


def test_a_number_the_quote_does_not_hold_is_refused(standard):
    report = run(reply(item(value="15")))
    assert report["proposed"] == 0 and drafts() == []
    assert sum(report["refused"].values()) == 1


def test_a_quote_not_in_the_chunk_is_refused(standard):
    report = run(reply(item(quote="the pressure shall not exceed 10 bar at all times")))
    assert report["proposed"] == 0 and drafts() == []


def test_a_range_or_no_comparator_is_not_a_single_limit(standard):
    report = run(reply(item(operator="range", value_to="12")))
    assert report["proposed"] == 0 and sum(report["refused"].values()) == 1 and drafts() == []


def test_a_comparator_the_words_contradict_is_refused(standard):
    report = run(reply(item(operator=">=")))
    assert report["proposed"] == 0 and drafts() == []


def test_a_conditional_sentence_without_its_condition_is_refused(standard):
    text = "When the service is sour, the vent pressure shall not exceed 22 bar."
    report = run(reply(item(quote="the vent pressure shall not exceed 22 bar", subject="vent pressure",
                            value="22", unit="bar")), text)
    assert report["proposed"] == 0 and air.CONDITION_MISSING in report["refused"]


def test_a_table_row_is_read(standard):
    report = run(reply(item(quote="Max design temperature | 120 degC", subject="design temperature",
                            operator="<=", value="120", unit="degC")), TABLE)
    # a bare table row states no comparator in words: code does not guess one
    assert report["proposed"] == 0 or drafts()[0]["value"] == "120"


def test_a_chunk_across_pages_is_refused_not_cited_to_a_guessed_page(standard):
    report = run(reply(item()), page_end=2)
    assert report["proposed"] == 0 and report["refused"] == {arc.PAGE_UNCERTAIN: 1}


def test_words_an_existing_requirement_holds_are_not_proposed_again(standard):
    _chunk("c0", "std", "x")
    from app import standards
    standards.create_requirement(
        standard_document_id="std", chunk_id="c0", clause="5", page=1, requirement_text=TEXT,
        source_text=TEXT, structured={"requirement_type": "statement"})
    report = run(reply(item()))
    assert report["proposed"] == 0 and report["refused"] == {arc.ALREADY_HELD: 1}


def test_switch_off_reads_nothing(standard, monkeypatch):
    monkeypatch.setattr(settings, "ai_requirement_extraction_enabled", False)
    model = Fake()  # no reply queued: any call would raise
    _chunk("c1", "std", TEXT)
    report = arc.extract_standard("std", allowed_document_ids=frozenset({"std"}), max_chunks=5,
                                  provider=model)
    assert report["chunks"] == 0 and drafts() == []


def test_a_standard_the_caller_may_not_read_is_not_read(standard):
    _chunk("c1", "std", TEXT)
    report = arc.extract_standard("std", allowed_document_ids=frozenset(), max_chunks=5, provider=Fake())
    assert report["chunks"] == 0 and drafts() == []


@pytest.mark.parametrize("provider", ["claude", "per_task"])
def test_no_route_to_claude_under_any_reasoning_provider(standard, monkeypatch, provider):
    from app import reader_transport

    monkeypatch.setattr(settings, "reasoning_provider", provider)
    for name in dir(reader_transport):
        if name.startswith(("call", "send", "post", "request", "read")) and callable(getattr(reader_transport, name)):
            monkeypatch.setattr(reader_transport, name,
                                lambda *a, **k: (_ for _ in ()).throw(AssertionError("Claude lane used")))
    assert run(reply(item()))["proposed"] == 1
    assert "reader_transport" not in Path(arc.__file__).read_text().replace("`reader_transport`", "")


def test_an_accepted_draft_becomes_a_confirmed_limit(standard):
    run(reply(item()))
    [draft] = drafts()
    done = air.decide_draft(draft["id"], decision="accept", allowed_document_ids=frozenset({"std"}),
                            actor={"id": None})
    assert done["status"] == air.ACCEPTED and done["new_requirement_id"]


def test_the_admin_route_reports_counts_and_stores_drafts(standard, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    _chunk("c1", "std", TEXT)
    monkeypatch.setattr(air.ai_task_runner, "run_task", lambda spec, text, provider=None, use_cache=True:
                        air.ai_task_runner.TaskResult(spec.name, air.ai_task_runner.STATE_OK,
                                                      reply(item()), None, "m"))
    monkeypatch.setattr(arc.ai_task_runner, "make_provider", lambda *a, **k: Fake())
    body = TestClient(app).post("/api/standards/std/clause-checks/extract").json()
    assert body["proposed"] == 1 and "quote" not in str(body)
    monkeypatch.setattr(settings, "ai_requirement_extraction_enabled", False)
    assert TestClient(app).post("/api/standards/std/clause-checks/extract").json()["chunks"] == 0
