"""First-time-user test of live update 16 (17 Nov 2026): the contractor's first sheet in contractor words with counts that add up, the
two sources of the rule books not held kept apart, one wording per silent row (a placeholder quote is a value deferred), one open count
on every proposal line, and book names without their clause. Every check reads the file AS BUILT. Invented values only."""

from __future__ import annotations

import io
import re

import pytest
from openpyxl import load_workbook

from app import (
    agent_review_schema,
    crs_completeness,
    crs_one,
    db,
    review_code_proposal,
    review_points,
    review_points_service,
)
from app.config import settings
from tests.test_agent_review_crs import mk
from tests.test_b1_review_points import ai_run, decide, points_of, world_with_both
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)
from tests.test_ftu1_first_time_user import silent_line
from tests.test_k4_one_crs import rows_after, scope_all
from tests.test_o14_review_code_honest import _record


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def _book(data: bytes):
    return load_workbook(io.BytesIO(data))


def _texts(ws) -> list[str]:
    return [str(c) for r in ws.iter_rows(values_only=True) for c in r if c is not None]


# ------------------------------------------------------------------------------------------------ 2. the contractor's first sheet

INTERNAL = re.compile(
    r"engineer|internal copy|proven by code|code-proven|\bAI\b", re.IGNORECASE
)
COUNT_LINE = re.compile(
    r"^(\d+) points reviewed, (\d+) in this file, (\d+) not issued: (.+)$"
)


def test_the_contractor_first_sheet_has_no_internal_word_and_its_counts_add_up_once_each():
    doc, _rc, _ai, client = world_with_both()
    listing = points_of(client, doc)
    opinions = [p for p in listing["points"] if p["rank"] != 1]
    assert len(opinions) >= 2, (
        "the invented world must hold two points that are not proven Fails"
    )
    assert (
        decide(client, doc, opinions[0]["id"], "keep").status_code == 200
    )  # kept, no words of the company's own: not issued
    assert (
        decide(
            client, doc, opinions[1]["id"], "remove", reason="invented reason"
        ).status_code
        == 200
    )
    recorded = _record(
        client,
        points_of(client, doc)["code_run_id"],
        "Approved with Comments",
        "invented reason",
    )
    assert recorded.status_code == 200, recorded.text
    listing = points_of(client, doc)
    ws = _book(
        crs_completeness.file_or_refuse(doc, scope_all(), "contractor")
    ).worksheets[0]
    texts = _texts(ws)
    assert not [t for t in texts if INTERNAL.search(t)], [
        t for t in texts if INTERNAL.search(t)
    ]
    lines = [m for t in texts if (m := COUNT_LINE.match(t))]
    assert len(lines) == 1, "ONE count line"
    n, m, k, why = int(lines[0][1]), int(lines[0][2]), int(lines[0][3]), lines[0][4]
    reasons = {r: int(c) for c, r in re.findall(r"(\d+) ([^;]+)", why)}
    assert n == listing["of"] and n == m + k and sum(reasons.values()) == k
    assert (
        reasons[crs_completeness.REASON_REMOVED] == 1
        and reasons[crs_completeness.REASON_NO_WORDING] == 1
    )
    assert (
        reasons[crs_completeness.REASON_NOT_DECIDED]
        == listing["of"] - listing["decided"]
    )
    # the removed point is counted once on the sheet, and no line outside the count line repeats a count of points
    assert sum(t.count("removed") for t in texts) == 1
    assert not [
        t
        for t in texts
        if re.search(r"\d+ (?:points?|row\(s\))", t) and not COUNT_LINE.match(t)
    ]
    assert any(
        t.startswith("Approved with Comments (recorded by COMPANY)") for t in texts
    )


# ------------------------------------------------------------------------------------------------ 3 and 6. the rule books not held


def _missing_books(run_id: str, *names: str) -> None:
    agent_review_schema.ensure_schema()
    with db.connect() as conn:
        for name in names:
            conn.execute(
                "INSERT INTO agent_review_missing_book (run_id, name, why) VALUES (?,?,?)",
                (run_id, name, "invented"),
            )


def _held_sheet(doc: str, *, checked: bool = True):
    data = (
        crs_completeness.file_or_refuse(doc, scope_all(), "team")
        if checked
        else crs_one.build_team(doc, scope_all())
    )
    ws = _book(data)[crs_one.HELD_SHEET]
    _head, rows = rows_after(ws, "Rule book")
    note = next(t for t in _texts(ws) if "rule book(s) not held" in t)
    return _head, rows, note


def test_the_books_rows_mark_and_the_books_only_the_scope_found_are_apart_counted_and_named_without_a_clause():
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    rc = _run(doc, recommended=None)
    _finding(doc, rc, "NON_COMPLIANT", origin="datasheet_check", standard_document_id=None, standard_clause="BOOK-77 4.1",
             standard_page=None)  # fmt: skip
    ai = ai_run(doc, [mk("R-1", "Query", None, why="x y")])
    # the review's scope: the same book with another clause, a book with a clause, a book without one
    _missing_books(ai, "BOOK-77 5", "BOOK-90 6.1", "BOOK-91")
    client = _client(doc, "doc_std")
    counts = points_of(client, doc)["counts"]["not_held"]
    head, rows, note = _held_sheet(doc)
    names = [r[0] for r in rows]
    assert sorted(names) == [
        "BOOK-77",
        "BOOK-90",
        "BOOK-91",
    ]  # each book once, never with its clause
    where = {r[0]: r[head.index(crs_one.HELD_SOURCE_COLUMN)] for r in rows}
    assert where["BOOK-77"] == crs_one.HELD_ON_ROWS.format(n=1)
    assert where["BOOK-90"] == where["BOOK-91"] == crs_one.HELD_SCOPE_ONLY
    assert names[0] == "BOOK-77"  # the books points mark come first
    assert note.startswith(
        "3 rule book(s) not held: 1 marked not held by 1 point(s) of this review; 2 found not held by the review's scope only"
    )
    # the page counts the same books, split the same way
    assert (
        (counts["total"], counts["on_rows"], counts["scope_only"])
        == (3, 1, 2)
        == (len(rows), 1, 2)
    )


def test_an_ai_reviews_own_note_row_marks_its_book_not_held(monkeypatch):
    monkeypatch.setattr(settings, "ai_review_calculator_enabled", True)
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai = ai_run(doc, [mk("R-1", "Query", None, why="x y")])
    _missing_books(ai, "BOOK-90 6.1")
    client = _client(doc, "doc_std")
    listing = points_of(client, doc)
    assert [
        p["name"]
        for p in listing["points"]
        if p["name"].startswith("Rule book not held")
    ] == ["Rule book not held: BOOK-90"]
    # built without the count check: the AI review's notes are not lines of the database (the calculator setting is off by default)
    _head, rows, note = _held_sheet(doc, checked=False)
    assert [r[0] for r in rows] == ["BOOK-90"] and rows[0][
        2
    ] == crs_one.HELD_ON_ROWS.format(n=1)
    assert listing["counts"]["not_held"]["on_rows"] == 1 and note.startswith(
        "1 rule book(s) not held: 1 marked"
    )


@pytest.mark.parametrize(
    ("reference", "book", "clause"),
    [
        ("BOOK-90 6.1", "BOOK-90", "6.1"),
        ("STD-A-001 11.9", "STD-A-001", "11.9"),
        ("XYZ 6100-2 5", "XYZ 6100-2", "5"),
        (
            "BOOK-90 (edition not recorded) cl. 5.2",
            "BOOK-90 (edition not recorded)",
            "5.2",
        ),
        ("BOOK-90 2017", "BOOK-90 2017", None),  # an edition year is never the clause
        ("BOOK-90 11th edition", "BOOK-90 11th edition", None),
        ("BOOK-90", "BOOK-90", None),
    ],
)
def test_a_reference_is_read_as_its_book_and_its_clause(reference, book, clause):
    assert review_points.book_and_clause(reference) == (book, clause)


def test_one_book_cited_with_two_clauses_is_one_book_not_held():
    got = review_points.books_not_held(
        ["BOOK-90 6.1", "BOOK-90 7"], [{"_book_missing": "BOOK-90 6.5"}], []
    )
    assert got == ["BOOK-90"]


# ------------------------------------------------------------------------------------------------ 4. silent rows


def _verified(monkeypatch):
    """The cited passage is on the cited page (the stored page text is not part of this invented world)."""
    monkeypatch.setattr(
        review_points_service, "_sides", lambda finding, scope: {"submittal": {"document": finding["document_id"], "page": 4, "verified": True}, "standard": {}}
    )  # fmt: skip


def _rows(data: bytes) -> list[dict]:
    wb = _book(data)
    out = []
    for sheet, first in (
        (crs_one.TEAM_SHEET, "Comment"),
        (crs_one.EVIDENCE_SHEET, "No"),
    ):
        head, rows = rows_after(wb[sheet], first)
        out += [
            {
                h: v
                for h, v in zip(head, r, strict=False)
                if isinstance(v, str) and h not in ("Full text", "Note")
            }
            for r in rows
        ]
    return out


@pytest.mark.parametrize("placeholder", ["___*___", "*", "TBA", "___ m3/h"])
def test_a_placeholder_quote_on_a_silent_rule_check_row_is_a_value_to_state_never_may_state_it(
    monkeypatch, placeholder
):
    _verified(monkeypatch)
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    rc = _run(doc, recommended=None)
    _finding(
        doc,
        rc,
        "MISSING_INFORMATION",
        contractor_evidence_text=placeholder,
        origin="datasheet_check",
    )
    _client(doc, "doc_std")
    rows = [
        r
        for r in _rows(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
        if "Left to be given" in str(r)
    ]
    assert len(rows) == 2, "the row on the sheet CRS and on the sheet Evidence"
    for r in rows:
        assert r["What the contractor must do"].startswith("Contractor to state")
        assert not [v for v in r.values() if "may state it" in v]
        assert r["Reason"] == review_points.actions.DEFERRED_REASON


@pytest.mark.parametrize("quote", ["Set pressure", "Set pressure: 12 barg"])
def test_a_silent_row_says_the_readers_sentence_once_and_no_cell_says_both_not_evidence_and_does_not_state(
    quote,
):
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    ai_run(doc, [silent_line("absent", opinion=False, paper_quote=quote)])
    _client(doc, "doc_std")
    data = crs_completeness.file_or_refuse(doc, scope_all(), "team")
    rows = [r for r in _rows(data) if "found on the page by code" in str(r)]
    assert len(rows) == 2
    for r in rows:
        assert sum(v.lower().count("the reader says") for v in r.values()) <= 1, r
        assert sum("does not state this value" in v for v in r.values()) == 1, r
        assert not [
            v
            for v in r.values()
            if "not evidence of a value" in v.lower()
            and "does not state this value" in v
        ]
    # the AI run's own file puts the paper and the reason in ONE cell: the reason said once there too
    from app import crs_ai_workbook as wb

    cell = wb.layout_comment(
        silent_line("absent", opinion=False, paper_quote=quote),
        *wb.status_of(silent_line("absent", opinion=False, paper_quote=quote)),
    )
    assert (
        cell.lower().count("does not state this value") == 1
        and "not evidence of a value" not in cell.lower()
    )


# ------------------------------------------------------------------------------------------------ 5. one open count


def test_pages_not_read_still_say_the_open_count_the_sheet_states(monkeypatch):
    doc, _rc, _ai, client = world_with_both()
    monkeypatch.setattr(review_points_service, "_unread_pages", lambda run, scope: [3, 4])
    listing = points_of(client, doc)
    left, of = listing["of"] - listing["decided"], listing["of"]
    assert left > 0
    proposal = listing["proposed_code"]
    assert proposal["undecided"] == left and proposal["so_far"]
    assert (
        proposal["line"]
        == f"Manual Review Required: 2 pages were not fully read (pages 3, 4). {left} of {of} points still to decide."  # W-H7: the sheets' words
    )
    texts = _texts(
        _book(crs_completeness.file_or_refuse(doc, scope_all(), "team")).worksheets[0]
    )
    assert proposal["line"] in texts and any(
        t.startswith(f"Decisions: {of - left} of {of} decided") for t in texts
    )
    assert review_points_service.undecided(doc, scope_all()) == (left, of)


def test_the_one_open_count_counts_every_point_without_a_decision_and_never_an_added_one():
    points = [{"rank": 4, "source": "rule_check", "decision": {"state": None}}, {"rank": 4, "source": "added", "decision": {"state": "keep"}},
              {"rank": 4, "source": "ai_review", "decision": {"state": "remove"}}, {"rank": 7, "source": "ai_review", "decision": {}}]  # fmt: skip
    assert len(review_code_proposal.still_open(points)) == 2
    got = review_code_proposal.propose(points, unread_pages=1)
    assert got["undecided"] == 2 and got["line"].endswith(
        "2 of 4 points still to decide."
    )


def test_the_online_search_found_for_a_book_with_its_clause_is_shown_beside_the_book_alone(
    monkeypatch,
):
    """The list names the book alone; the search stored the run's own name, clause and all: the same book is still found."""
    from app import standards_web_search as sws

    monkeypatch.setattr(settings, "standards_web_search_enabled", True)
    with db.connect() as conn:
        for sql in sws._STATEMENTS:
            conn.execute(sql)
        conn.execute(
            f"INSERT INTO {sws.TABLE} (run_id, name, outcome, title, searched_at) VALUES (?,?,?,?,?)",
            (
                "run-1",
                "BOOK-90 6.1",
                sws.FOUND,
                "An invented title",
                "2026-11-17T00:00:00Z",
            ),
        )
        got = sws.shown(conn, "run-1", ["BOOK-90"])
    assert got[0]["name"] == "BOOK-90" and got[0]["title"] == "An invented title"


# ------------------------------------------------------------------------------------------------ review R1 of PR #1867


def _rc_silent_row(monkeypatch, quote: str, **finding) -> list[dict]:
    """The rows of a silent rule-check point whose verified quote is `quote`, as built (sheet CRS and sheet Evidence)."""
    _verified(monkeypatch)
    doc = _submittal()
    _submittal("doc_std", "STD-A-001.pdf")
    rc = _run(doc, recommended=None)
    _finding(
        doc,
        rc,
        "MISSING_INFORMATION",
        contractor_evidence_text=quote,
        origin="datasheet_check",
        **finding,
    )
    _client(doc, "doc_std")
    rows = [
        r
        for r in _rows(crs_completeness.file_or_refuse(doc, scope_all(), "team"))
        if "found on the page by code" in str(r)
    ]
    assert len(rows) == 2, "the row on the sheet CRS and on the sheet Evidence"
    return rows


def _neutral(rows: list[dict]) -> None:
    for r in rows:
        assert r["What the contractor must do"].startswith("Engineer to check"), r
        assert r["Reason"] == review_points.actions.CONTRADICT_REASON
        assert not [
            v for v in r.values() if "Left to be given" in v or "placeholder" in v
        ]


@pytest.mark.parametrize(
    "quote",
    [
        "Set pressure | 10 barg | -",
        "Set pressure 10 barg | Back pressure | TBA",
        "Design pressure 10 barg; test pressure by contractor",
    ],
)
def test_a_quote_that_also_states_a_value_is_never_a_placeholder(monkeypatch, quote):
    """R1 (HIGH): a marker somewhere in the quote does not make the whole quote a placeholder: a figure or a value word is left."""
    assert not review_points.actions.quote_is_placeholder(
        quote, ["Set pressure"], value_field=True
    )
    _neutral(_rc_silent_row(monkeypatch, quote))


@pytest.mark.parametrize("quote", ["-", "--", "—"])
def test_a_dash_alone_is_ambiguous_and_the_engineer_checks(monkeypatch, quote):
    assert not review_points.actions.quote_is_placeholder(
        quote, ["Set pressure"], value_field=True
    )
    _neutral(_rc_silent_row(monkeypatch, quote))


def test_by_contractor_is_a_value_to_give_only_on_a_field_that_asks_for_a_value():
    q = review_points.actions.quote_is_placeholder
    assert q("Set pressure: By Contractor", ["Set pressure"], value_field=True)
    assert not q("Painting: By Contractor", ["Painting"], value_field=False)
    assert not q("Installation by Contractor", ["Installation"], value_field=False)
    assert q("Set pressure: TBA", ["Set pressure"]) and q(
        "___*___", ["Set pressure"]
    )  # a to-be-given marker needs no value rule


@pytest.mark.parametrize("asks_a_figure", [True, False])
def test_by_contractor_through_the_built_file_follows_what_the_rule_asks(
    monkeypatch, asks_a_figure
):
    rule = (
        {}
        if asks_a_figure
        else {"requirement_source_text": "Painting shall be done by the contractor."}
    )  # default: 6,900 kPa
    rows = _rc_silent_row(monkeypatch, "By Contractor", **rule)
    if not asks_a_figure:
        _neutral(rows)
        return
    for r in rows:
        assert r["What the contractor must do"].startswith("Contractor to state")


@pytest.mark.parametrize(
    ("reference", "book", "clause"),
    [
        ("ZZ-SPEC-001 Part 2", "ZZ-SPEC-001 Part 2", None),
        ("API 598 Table 5", "API 598 Table 5", None),
        ("API 650 Annex 5", "API 650 Annex 5", None),
        ("EN 10204 type 3.1", "EN 10204 type 3.1", None),
        ("ASME B16.5 Class 300", "ASME B16.5 Class 300", None),
        ("ASME B16.34-2020 6.1.2", "ASME B16.34-2020", "6.1.2"),
    ],
)
def test_a_part_table_annex_class_or_type_number_stays_in_the_book_name(
    reference, book, clause
):
    assert review_points.book_and_clause(reference) == (book, clause)


def test_two_parts_of_one_book_are_two_books_not_held():
    assert review_points.books_not_held(
        ["ZZ-SPEC-001 Part 2", "ZZ-SPEC-001 Part 3"], [], []
    ) == [
        "ZZ-SPEC-001 Part 2",
        "ZZ-SPEC-001 Part 3",
    ]


def test_the_listing_and_the_sign_gate_read_the_one_open_count(monkeypatch):
    """R1: the listing's "x of M decided" and the sign gate read `still_open` itself: a forged count shows on both."""
    doc, _rc, _ai, client = world_with_both()
    of = points_of(client, doc)["of"]
    monkeypatch.setattr(review_code_proposal, "still_open", lambda points: points[:1])
    listing = points_of(client, doc)
    assert (listing["decided"], listing["of"]) == (of - 1, of)
    assert review_points_service.undecided(doc, scope_all()) == (1, of)


def test_an_added_point_without_a_decision_is_kept_and_decided_on_the_sign_gate():
    doc, _rc, _ai, client = world_with_both()
    before = review_points_service.undecided(doc, scope_all())
    added = client.post(
        f"/api/reviews/papers/{doc}/points/add",
        json={"text": "Check the invented schedule.", "page": 2},
    )
    assert added.status_code == 200, added.text
    point = next(p for p in added.json()["points"] if p["source"] == "added")
    assert point["decision"]["state"] == "keep"
    assert review_points_service.undecided(doc, scope_all()) == (
        before[0],
        before[1] + 1,
    )


# ------------------------------------------------------------------------------------------------ review R2 of PR #1867: whole forms only

NEUTRAL_PROBES = [
    "Rate: A | TBA",
    "Pump type: HP | TBA",
    "Thickness: M *",
    "Grade: Steel *",
    "Set pressure | 10 barg | -",
    "Set pressure 10 barg | Back pressure | TBA",
    "Design pressure 10 barg; test pressure by contractor",
    "12.5 barg (final value to be confirmed)",
    "-10",
    "0",
    "N/A",
    "2-3",
    "-",
    "--",
    "—",
    "Painting: By Contractor",
]
LABELS = [
    "Rate",
    "Pump type",
    "Thickness",
    "Steel grade",
    "Set pressure",
    "Design pressure",
    "Painting",
]


@pytest.mark.parametrize("quote", NEUTRAL_PROBES)
def test_every_probe_that_is_not_one_whole_marker_form_is_neutral(quote):
    """A quote is a placeholder only when the WHOLE of it, after the field's own label, is one fixed marker form; nothing is dropped
    to reach one. "Painting: By Contractor" is neutral on a field that asks no value (a scope answer)."""
    actions = review_points.actions
    value_field = quote.startswith("Painting") is False
    assert not actions.quote_is_placeholder(quote, LABELS, value_field=value_field)
    row = actions.silent_row_words("", quote, LABELS, "", False, value_field)
    assert row.kind == actions.CONTRADICTS, (quote, row.kind)


#: Review R3 of PR #1867: a marker followed by a word that is a unit only on a field that asks for a value; on any other field (or
#: with a word that is no unit) the quote is not a deferral. The field's own label in the wrong order or with another word is not the
#: label alone ("Grade: Steel" for "Steel grade": "Steel" may be the value).
FALSE_DEFERRAL_PROBES = [
    ("Pump type: * HP", "Pump type"),
    ("Driver: TBA HP", "Driver"),
    ("Material: * CP", "Material"),
    ("Grade: * M", "Grade"),
    ("Thickness: * M", "Thickness"),
    ("Voltage: later kV", "Voltage"),
    ("Grade: Steel", "Steel grade"),
    ("Grade: Steel *", "Steel grade"),
    ("Steel grade Steel", "Steel grade"),
    ("Set pressure (barg)", "Set pressure"),
]


@pytest.mark.parametrize(("quote", "field"), FALSE_DEFERRAL_PROBES)
def test_a_marker_with_a_word_on_a_field_that_asks_no_value_and_a_label_out_of_order_are_neutral(quote, field):
    actions = review_points.actions
    row = actions.silent_row_words(field, quote, (), "", False, False)
    assert row.kind == actions.CONTRADICTS, (quote, row.kind)


@pytest.mark.parametrize(
    ("quote", "value_field", "kind"),
    [
        ("Rated flow: * m3/h", True, "deferred"),
        ("Rated flow: TBA (barg)", True, "deferred"),
        ("Rated flow: TBA 10", True, "contradicts"),
        ("Rated flow: TBA Steel", True, "contradicts"),
        ("Rated flow: * m3/h", False, "contradicts"),
        ("Rated flow: TBA", False, "deferred"),
        ("Rated flows", False, "looked"),
        ("RATED  FLOW:", False, "looked"),
    ],
)
def test_a_unit_after_a_marker_counts_only_on_a_value_field_and_only_when_it_is_a_unit(quote, value_field, kind):
    row = review_points.actions.silent_row_words("Rated flow", quote, (), "", False, value_field)
    assert row.kind == kind, (quote, row.kind)


@pytest.mark.parametrize(
    ("quote", "labels", "value_field"),
    [
        ("TBA", ["Set pressure"], False),
        ("Set pressure: TBA", ["Set pressure"], False),
        ("* m3/h", ["Rated flow"], True),
        ("___", ["Rated flow"], False),
        ("By Contractor", ["Set pressure"], True),
        ("Set pressure: By Contractor", ["Set pressure"], True),
    ],
)
def test_one_whole_marker_form_after_the_label_is_a_value_to_be_given(
    quote, labels, value_field
):
    assert review_points.actions.quote_is_placeholder(
        quote, labels, value_field=value_field
    )


def test_by_contractor_alone_on_a_field_that_asks_no_value_is_neutral():
    assert not review_points.actions.quote_is_placeholder(
        "By Contractor", ["Painting"], value_field=False
    )


@pytest.mark.parametrize(
    ("reference", "book", "clause"),
    [
        ("IEC 61882 Section 6.1", "IEC 61882", "6.1"),
        ("ZZ-SPEC-001 Sec. 7", "ZZ-SPEC-001", "7"),
        ("ASME Section VIII Div 1", "ASME Section VIII Div 1", None),
        ("API 520 Part 1 Sec.5.3", "API 520 Part 1", "5.3"),
        ("API 520 Part 1 Sec. 5.3", "API 520 Part 1", "5.3"),
    ],
)
def test_section_is_a_clause_prefix_and_a_section_with_no_number_stays_in_the_name(
    reference, book, clause
):
    assert review_points.book_and_clause(reference) == (book, clause)
