"""Order 14 LPV, V2: a row never asks the contractor to STATE a value the paper states. Invented data only.

The owner found two rows asking the contractor to state materials that the paper states (the review's own other points quote them).
Rule: when code finds the value on the paper (another point of the same review on the same field read it from a quote code verified
on the page, or the paper's stored reading holds the field's own label with a value code found on its page), the row is the
engineer's check citing that quote, never "Contractor to state". One home decides it: `crs_ai_actions.mark_stated` + `silent_row`."""

from __future__ import annotations

import sqlite3

from app import crs_ai_actions as A
from app import crs_ai_words
from tests.test_agent_review_crs import mk

STATE = "Contractor to state"


def _silent(**kw) -> dict:
    """The reader says the paper does not state the field; its quote is the field's label alone (code can show it holds no value)."""
    base = {"field": "Body material", "paper_quote": "Body material :", "reason_code": "sheet_silent",
            "rule_label": {"field": "body_material"}, "field_roles": []}  # fmt: skip
    return mk("R-1", "Query", "Query", **{**base, **kw})


def _reader_met(**kw) -> dict:
    """Another point of the same review on the same rule field: the reader read a value from a quote code found on the page."""
    base = {"field": "Casing material", "paper_quote": "XQ 70 plate", "reason_code": "met", "paper_page": 3,
            "rule_label": {"field": "body_material"}, "field_roles": []}  # fmt: skip
    return mk("R-2", "Query", "Pass", **{**base, **kw})


def _action(line: dict) -> str:
    return A.query_action(line, "Body material", "STD-1 clause 4.1")


def test_before_the_mark_the_label_alone_row_asks_the_contractor_to_state_it():
    assert _action(_silent()).startswith(STATE)


def test_another_point_that_read_the_value_makes_the_row_the_engineers_check_citing_it():
    silent, met = A.mark_stated([_silent(), _reader_met()])
    assert silent[A.STATED_KEY] == {
        "quote": "XQ 70 plate",
        "page": 3,
        "from": A.FROM_LINE,
    }
    assert A.STATED_KEY not in met  # a line that read its value is left as it is
    action = _action(silent)
    assert STATE not in action and action.startswith(
        "Engineer to check Body material against the value the paper states"
    )
    assert '"XQ 70 plate", page 3' in action
    row = A.silent_row(silent)
    assert (
        row.kind == A.CONTRADICTS and row.reason == A.STATED_REASON
    )  # the contractor copy never asks it (neutral kind)
    assert A.reason_for(
        silent, "x"
    ) == A.STATED_REASON and "XQ 70 plate" in A.quote_cell(silent)


def test_a_point_that_says_not_stated_or_did_not_read_a_value_is_no_evidence():
    for other in (
        _reader_met(
            reason_code="sheet_silent"
        ),  # its own record says "not stated", whatever its verdict
        _reader_met(
            ai_verdict="Query"
        ),  # no reading of a value (does not apply, could not decide)
        _reader_met(paper_quote="Casing material :"),  # the label alone
        _reader_met(paper_quote="Casing material : TBA"),  # a placeholder
        _reader_met(
            quotes_checked={"paper": False, "clause": True}
        ),  # a quote code did not find
        _reader_met(rule_label={"field": "tube_material"}),  # another field
    ):
        silent, _ = A.mark_stated([_silent(), other])
        assert A.STATED_KEY not in silent and _action(silent).startswith(STATE)


def test_the_papers_stored_reading_with_the_fields_own_label_and_a_value_found_on_its_page():
    reading = [
        {
            "field_label": "Body material :",
            "field_value": "XQ 70 plate",
            "page": 2,
            "is_blank": 0,
            "on_page": True,
        }
    ]
    (silent,) = A.mark_stated([_silent()], reading)
    assert silent[A.STATED_KEY] == {
        "quote": "Body material: XQ 70 plate",
        "page": 2,
        "from": A.FROM_READING,
    }
    assert STATE not in _action(silent)
    for bad in (
        {"on_page": False},
        {"field_label": "Tube material :"},
        {"field_value": "TBA"},
        {"is_blank": 1},
    ):
        (still,) = A.mark_stated([_silent()], [{**reading[0], **bad}])
        assert A.STATED_KEY not in still and _action(still).startswith(STATE)


def test_a_deferred_quote_keeps_its_own_row_the_paper_marks_the_value_to_be_given():
    """The reader quoted a placeholder: the paper itself leaves the value to be given; a value read elsewhere does not hide that."""
    silent, _ = A.mark_stated(
        [_silent(paper_quote="Body material : TBA"), _reader_met()]
    )
    assert (
        "stated on the paper"
        not in (A.silent_row(silent) or A.SilentRow("", "", "", "", "")).check
    )


def test_a_row_with_no_quote_at_all_is_covered_too():
    silent, _ = A.mark_stated(
        [
            _silent(paper_quote="", quotes_checked={"paper": False, "clause": True}),
            _reader_met(),
        ]
    )
    assert _action(silent).startswith(
        "Engineer to check Body material against the value the paper states"
    )


def test_the_paper_reading_checks_value_and_label_on_the_page(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE pages (document_id TEXT, page_no INTEGER, text TEXT);"
        "CREATE TABLE submittal_facts (submittal_document_id TEXT, field_label TEXT, field_value TEXT, page INTEGER,"
        " is_blank INTEGER, superseded_at TEXT);"
    )
    con.execute(
        "INSERT INTO pages VALUES ('p', 2, 'Body material : XQ 70 plate\nColour : blue')"
    )
    con.executemany(
        "INSERT INTO submittal_facts VALUES ('p', ?, ?, ?, 0, NULL)",
        [
            ("Body material :", "XQ 70 plate", 2),
            ("Colour :", "green", 2),
            ("Body material :", "XQ 70 plate", 5),
        ],
    )
    import app.db as db_mod

    monkeypatch.setattr(db_mod, "connect", lambda: con)
    got = A.paper_reading("p")
    assert [f["on_page"] for f in got] == [
        True,
        False,
        False,
    ]  # a value not on its page, or a page that does not hold it
    assert A.paper_reading(None) == []


def test_every_crs_reading_marks_the_lines_once(monkeypatch):
    """`crs_ai_words.read_now` is the one reading of stored lines (the page's points, both files, the gates): it marks them."""
    monkeypatch.setattr(A, "paper_reading", lambda paper: [])
    now = crs_ai_words.read_now([_silent(), _reader_met()], [], paper="p")
    assert now[0][A.STATED_KEY]["quote"] == "XQ 70 plate"
