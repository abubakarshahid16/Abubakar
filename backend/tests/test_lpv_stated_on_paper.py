"""Order 14 LPV, V2: a row never asks the contractor to STATE a value the paper states. Invented data only.

The value counts as stated only when code finds the row's OWN label and a value TOGETHER on the row's OWN page (the same line, or
the label's own cell, the next line), the paper's stored reading on that page agrees, and every place on that page says the same
value (several tags on one page saying different values: the row keeps asking). Another point of the same review counts only when
its verified quote, on the same page, holds this row's label and a value. The page's own words are cited. One home decides it
(`crs_ai_actions.mark_stated` + `silent_row`), read by every CRS, the page's points and the lines tab with the same inputs."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import crs_ai_actions as A
from app import crs_ai_words
from tests.test_agent_review_crs import mk
from tests.test_crs_endpoint import temp_db  # noqa: F401  (fixture)

STATE = "Contractor to state"
PAGE2 = "Invented sheet\nBody material :\nXQ 70 plate\nColour : blue\nSpare : YES\nTested : YES\n"


def _silent(**kw) -> dict:
    """The reader says the paper does not state the field; its quote (page 2) is the field's label alone."""
    base = {"field": "Body material", "paper_quote": "Body material :", "reason_code": "sheet_silent", "paper_page": 2,
            "rule_label": {"field": "body_material"}, "field_roles": []}  # fmt: skip
    return mk(kw.pop("item_id", "R-1"), "Query", "Query", **{**base, **kw})


def _reader_met(**kw) -> dict:
    base = {"field": "Body material", "paper_quote": "Body material : XQ 70 plate", "reason_code": "met", "paper_page": 2,
            "rule_label": {"field": "body_material"}, "field_roles": []}  # fmt: skip
    return mk("R-2", "Query", "Pass", **{**base, **kw})


FACT = {
    "field_label": "Body material :",
    "field_value": "XQ 70 plate",
    "page": 2,
    "is_blank": 0,
}


def _reading(pages=None, facts=None) -> dict:
    return {
        "pages": {2: PAGE2} if pages is None else pages,
        "facts": [FACT] if facts is None else facts,
    }


def _action(line: dict) -> str:
    return A.query_action(line, "Body material", "STD-1 clause 4.1")


def _marked(lines, reading=None, context=None):
    return A.mark_stated([dict(x) for x in lines], reading, context)


def test_before_the_mark_the_label_alone_row_asks_the_contractor_to_state_it():
    assert _action(_silent()).startswith(STATE)


def test_the_label_and_its_value_together_on_the_rows_own_page_make_it_the_engineers_check():
    (silent,) = _marked([_silent()], _reading())
    assert silent[A.STATED_KEY] == {
        "quote": "Body material : XQ 70 plate",
        "page": 2,
        "from": A.FROM_READING,
    }
    action = _action(silent)
    assert STATE not in action and action.startswith(
        "Engineer to check Body material against the value the paper states"
    )
    row = A.silent_row(silent)
    assert (
        row.kind == A.CONTRADICTS and row.reason == A.STATED_REASON
    )  # neutral: the contractor copy never asks it
    assert "label and value found together on the page" in A.quote_cell(silent)


def test_a_value_elsewhere_or_without_its_label_or_not_agreed_by_the_reading_keeps_asking():
    for reading in (
        _reading(
            pages={2: "Body material :\n\nColour : blue"}
        ),  # the label's cell is another label's line
        _reading(
            pages={2: "Colour : blue\nXQ 70 plate"}
        ),  # the value on the page, never next to the label (the guard)
        _reading(facts=[{**FACT, "page": 5}]),  # read on another page
        _reading(
            facts=[{**FACT, "field_value": "ZZ 99 bar"}]
        ),  # the reading disagrees with the page
        _reading(facts=[{**FACT, "field_label": "Colour :"}]),  # another field's label
    ):
        (still,) = _marked([_silent()], reading)
        assert A.STATED_KEY not in still and _action(still).startswith(STATE)
    (other_page,) = _marked([_silent(paper_page=5)], _reading())
    assert A.STATED_KEY not in other_page


def test_a_yes_repeated_on_the_page_proves_nothing_for_a_label_with_no_value_next_to_it():
    page = "Gusset required\nRATING ____\nSpare : YES\nTested : YES\n"
    line = _silent(
        field="Gusset required",
        paper_quote="Gusset required",
        rule_label={"field": None},
    )
    facts = [
        {
            "field_label": "Gusset required",
            "field_value": "YES",
            "page": 2,
            "is_blank": 0,
        }
    ]
    (still,) = _marked([line], _reading(pages={2: page}, facts=facts))
    assert A.STATED_KEY not in still


def test_four_tags_on_one_page_with_different_values_keep_asking_one_tag_per_page_cites_its_own():
    one_page = "".join(f"Tag T-{n}\nSet pressure : {n}0 units\n" for n in range(1, 5))
    line = _silent(
        field="Set pressure",
        paper_quote="Set pressure",
        paper_page=1,
        rule_label={"field": "set_pressure"},
    )
    facts = [
        {
            "field_label": "Set pressure",
            "field_value": f"{n}0 units",
            "page": 1,
            "is_blank": 0,
        }
        for n in range(1, 5)
    ]
    (still,) = _marked([line], _reading(pages={1: one_page}, facts=facts))
    assert A.STATED_KEY not in still
    pages = {n: f"Tag T-{n}\nSet pressure : {n}0 units\n" for n in range(1, 5)}
    facts = [
        {
            "field_label": "Set pressure",
            "field_value": f"{n}0 units",
            "page": n,
            "is_blank": 0,
        }
        for n in (4, 3, 2, 1)
    ]
    for n in range(1, 5):
        (got,) = _marked(
            [{**line, "paper_page": n}], _reading(pages=pages, facts=facts)
        )
        assert (
            got[A.STATED_KEY]["quote"] == f"Set pressure : {n}0 units"
            and got[A.STATED_KEY]["page"] == n
        )


def test_another_point_counts_only_with_this_rows_label_and_a_value_on_the_same_page():
    silent, _ = _marked([_silent(), _reader_met()])
    assert silent[A.STATED_KEY] == {
        "quote": "Body material : XQ 70 plate",
        "page": 2,
        "from": A.FROM_LINE,
    }
    for other in (
        _reader_met(
            paper_quote="XQ 70 plate"
        ),  # a value with no label: tied only by the rule's label, not enough
        _reader_met(paper_page=3),  # another page
        _reader_met(reason_code="sheet_silent"),  # its own record says "not stated"
        _reader_met(ai_verdict="Query"),  # read no value
        _reader_met(paper_quote="Body material : TBA"),  # a placeholder
        _reader_met(
            quotes_checked={"paper": False, "clause": True}
        ),  # a quote code did not find
    ):
        silent, _ = _marked([_silent(), other])
        assert A.STATED_KEY not in silent and _action(silent).startswith(STATE)


def test_a_deferred_quote_keeps_its_own_row():
    silent, _ = _marked([_silent(paper_quote="Body material : TBA"), _reader_met()])
    row = A.silent_row(silent)
    assert row is None or "stated on the paper" not in row.check


def test_a_row_with_no_quote_uses_its_one_page_hint():
    line = _silent(
        paper_quote="",
        quotes_checked={"paper": False, "clause": True},
        paper_page=None,
        page_hint=[2],
    )
    (got,) = _marked([line], _reading())
    assert _action(got).startswith(
        "Engineer to check Body material against the value the paper states"
    )
    (two,) = _marked([{**line, "page_hint": [2, 3]}], _reading())
    assert A.STATED_KEY not in two  # two pages: not the row's own page, keeps asking


def test_the_points_page_and_the_file_agree_on_a_row_with_no_quote():
    from app import review_points

    line = _silent(
        paper_quote="",
        quotes_checked={"paper": False, "clause": True},
        paper_page=None,
        page_hint=[2],
    )
    (got,) = _marked([line], _reading())
    ctx = {
        "run_id": "r",
        "paper_document_id": "d",
        "book_of": {"R-1": ("doc_std", "STD-1")},
        "readable": frozenset({"doc_std"}),
    }
    assert (
        review_points.ai_point(got, ctx)["paper_quote_note"] == A.silent_row(got).note
    )


def test_every_reading_marks_the_lines_with_the_same_inputs(monkeypatch):
    """`read_now` (files, points, gates) and the lines tab (one line at a time, with the run's `context`) say the same."""
    monkeypatch.setattr(A, "paper_reading", lambda paper: _reading() if paper else {})
    lines = [_reader_met(), _silent(item_id="R-3")]
    every = crs_ai_words.read_now(lines, [], paper="p")
    one_by_one = [
        crs_ai_words.read_now([ln], [], paper="p", context=lines)[0] for ln in lines
    ]
    assert [x.get(A.STATED_KEY) for x in every] == [
        x.get(A.STATED_KEY) for x in one_by_one
    ]
    assert every[1][A.STATED_KEY]["from"] == A.FROM_LINE


def test_the_lines_tab_reads_the_runs_inputs(monkeypatch):
    from app.api import agent_review as api

    monkeypatch.setattr(
        A, "paper_reading", lambda paper: _reading() if paper == "p" else {}
    )
    row = {
        "item_id": "R-1",
        "verdict_class": "Query for the engineer",
        "word": "Query",
        "line_json": json.dumps(_silent()),
    }
    assert (
        api._line_now(row, [], {"paper": "p", "context": [_silent()]})[A.STATED_KEY][
            "page"
        ]
        == 2
    )
    assert A.STATED_KEY not in api._line_now(row, [], None)


def test_the_paper_reading_is_ordered(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE submittal_facts (submittal_document_id TEXT, field_label TEXT, field_value TEXT, page INTEGER,"
        " is_blank INTEGER, superseded_at TEXT);"
    )
    con.executemany("INSERT INTO pages VALUES ('p', ?, ?)", [(3, "c"), (1, "a")])
    con.executemany(
        "INSERT INTO submittal_facts VALUES ('p', 'L', ?, ?, 0, NULL)",
        [("v3", 3), ("v1", 1), ("v1b", 1)],
    )
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "connect", lambda: con)
    got = A.paper_reading("p")
    assert list(got["pages"]) == [1, 3] and [
        f["field_value"] for f in got["facts"]
    ] == ["v1", "v1b", "v3"]
    assert A.paper_reading(None) == {}


# ---- round 2 of the review ----------------------------------------------------------------------------------------------------


def test_no_value_forms_and_a_unit_alone_are_not_a_stated_value():
    for cell in (
        "N/A",
        "n/a",
        "N.A.",
        "N/A (Note 2)",
        "None",
        "Note 3",
        "see note 3",
        "see notes",
        "Refer note 2",
        "kPa(g)",
        "bar (g)",
    ):
        page = f"Body material : {cell}\n"
        fact = {**FACT, "field_value": cell}
        (still,) = _marked([_silent()], _reading(pages={2: page}, facts=[fact]))
        assert A.STATED_KEY not in still, cell
    page = "Rated flow (m3/h) :\nm3/h\n"
    line = _silent(
        field="Rated flow",
        paper_quote="Rated flow (m3/h) :",
        rule_label={"field": "rated_flow"},
    )
    fact = {
        "field_label": "Rated flow :",
        "field_value": "m3/h",
        "page": 2,
        "is_blank": 0,
    }
    (still,) = _marked([line], _reading(pages={2: page}, facts=[fact]))
    assert A.STATED_KEY not in still  # the unit under its label is no value


def test_the_page_is_said_once():
    words = A.stated_row_words(
        "Body material",
        {"quote": "Body material : XQ 70 plate", "page": 3, "from": A.FROM_READING},
        ", page 3",
    )
    assert words.action.count("page 3") == 1


def test_a_may_state_it_row_takes_the_stated_wording_when_code_found_the_value():
    silent, _ = _marked(
        [_silent(paper_quote="Body material : see sheet"), _reader_met()]
    )
    assert (
        A.silent_row(silent).reason == A.STATED_REASON
    )  # one wording, never "may state it" beside a stated mark


def test_a_stated_row_is_no_question_for_the_contractor_in_the_groups():
    from app import agent_review_wording as W

    line = _silent(silence_query=True)
    assert W.reader_query_group(line) == W.GROUP_SILENT
    (marked,) = _marked([line], _reading())
    assert W.reader_query_group(marked) is None


@pytest.fixture()
def lines_world(temp_db, monkeypatch):  # noqa: F811  (the fixture, imported above)
    from app.config import settings

    monkeypatch.setattr(settings, "agent_review_enabled", True)
    """An invented AI run whose silent line's value the paper states on its own page (temp database, the route's own client)."""
    from app import datasheets, db
    from tests.test_b1_review_points import ai_run
    from tests.test_crs_endpoint import NOW, _client, _submittal

    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, needs_ocr, batch_no) VALUES (?, 2, ?, 9, 0, 0)",
            (doc, PAGE2),
        )
        conn.execute(
            "INSERT INTO chunks (id, document_id, filename, ordinal, page_start, page_end, section, kind, text, token_count, content_hash,"
            " retrievable) VALUES (?, ?, 'drum.pdf', 2, 2, 2, NULL, 'prose', ?, 1, 'h', 1)",
            (f"{doc}-2", doc, PAGE2),
        )
    datasheets.create_fact(
        submittal_document_id=doc,
        chunk_id=f"{doc}-2",
        field_label="Body material :",
        raw_value="XQ 70 plate",
        page=2,
    )
    run = ai_run(doc, [_silent(silence_query=True)])
    assert NOW
    return run, _client(doc, "doc_std")


def test_the_lines_tab_and_its_query_groups_read_the_stated_value(lines_world):
    from app.api import agent_review as api
    from app.db import connect

    run, client = lines_world
    groups, _none = api._query_groups(connect(), run)
    assert (
        groups.contractor_silent == 0
    )  # the page states it: no question for the contractor
    got = client.get(f"/api/reviews/runs/{run}/agent/lines")
    assert got.status_code == 200, got.text
    (line,) = got.json()["lines"]
    assert (
        "against the value the paper states" in line["reason"]
        and STATE not in line["reason"]
    )


def test_a_container_label_keeps_its_own_wording():
    page = "Nozzle notes : flanges to be supplied loose\n"
    line = _silent(
        field="Nozzle notes",
        paper_quote="Nozzle notes : flanges",
        rule_label={"field": None},
    )
    fact = {
        "field_label": "Nozzle notes :",
        "field_value": "flanges to be supplied loose",
        "page": 2,
        "is_blank": 0,
    }
    (still,) = _marked([line], _reading(pages={2: page}, facts=[fact]))
    assert (
        A.STATED_KEY not in still
    )  # "Notes" holds many things: never cited as THE value of the rule's field
