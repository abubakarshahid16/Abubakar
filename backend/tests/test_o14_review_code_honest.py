"""Order 14, first-time-user test 15 (17 Nov 2026): no approving review code while points are still to decide, in every home; and the
CRS sheet "Rule books not held" counts every book a row marks "Book missing". Invented values only."""

from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from app import comparison, crs_one, review_code_proposal, review_points
from app.config import settings
from tests.test_b1_review_points import decide, points_of, world_with_both
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _run,
    _submittal,
    temp_db,
)
from tests.test_k4_one_crs import scope_all

APPROVING = (comparison.CODE_APPROVED, comparison.CODE_APPROVED_WITH_COMMENTS)


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)
    monkeypatch.setattr(settings, "review_code_resubmit_at_kept_mandatory_not_met", 0)


def pt(rank, state, *, shall=True, source="rule_check"):
    return {
        "rank": rank,
        "shall": shall,
        "source": source,
        "decision": {"state": state},
    }


# ------------------------------------------------------------------------------------------ R1: the one rule


def test_r1_an_approving_code_is_never_proposed_while_a_point_is_still_to_decide():
    """The pump's shape: 2 of 37 decided (one kept comment, one removed), 35 open; before: "So far: Approved with Comments"."""
    points = [pt(4, "keep"), pt(4, "remove")] + [pt(4, None) for _ in range(35)]
    got = review_code_proposal.propose(points)
    assert got["code"] is None
    assert (
        got["line"] == "No review code proposed yet: 35 of 37 points still to decide."
    )
    assert got["undecided"] == 35 and got["so_far"]
    assert not any(c in got["line"] or c in got["reason"] for c in APPROVING)
    # nothing kept as a comment and points open: Approved is not proposed either
    quiet = review_code_proposal.propose([pt(7, "keep"), pt(4, None)])
    assert quiet["code"] is None and quiet["line"].startswith(
        "No review code proposed yet: 1 of 2 points"
    )


def test_r1_an_open_proven_fail_is_named_and_a_kept_one_still_proposes_the_rejection():
    open_fail = review_code_proposal.propose([pt(4, "keep"), pt(1, None)])
    assert open_fail["code"] is None and open_fail["line"] == (
        "No review code proposed yet: 1 of 2 points still to decide; 1 is a code-proven Fail on a mandatory rule."
    )
    kept_fail = review_code_proposal.propose([pt(1, "keep"), pt(4, None), pt(4, None)])
    assert kept_fail["code"] == comparison.CODE_REJECTED
    assert (
        kept_fail["line"]
        == f"So far: {comparison.CODE_REJECTED}, 2 of 3 points still to decide"
    )


# ------------------------------------------------------------------------------------------ R3: all decided, unchanged


@pytest.mark.parametrize(
    "points, code",
    [
        ([pt(4, "keep"), pt(7, "keep")], comparison.CODE_APPROVED_WITH_COMMENTS),
        ([pt(7, "keep"), pt(4, "remove")], comparison.CODE_APPROVED),
        ([pt(1, "keep"), pt(4, "keep")], comparison.CODE_REJECTED),
        ([pt(1, "keep", shall=False)], comparison.CODE_APPROVED_WITH_COMMENTS),
    ],
)
def test_r3_with_every_point_decided_the_rule_proposes_as_before(points, code):
    got = review_code_proposal.propose(points)
    assert got["code"] == code and got["line"] == code and not got["so_far"]


def test_r3_pages_not_read_and_an_empty_finished_review_are_unchanged():
    assert (
        review_code_proposal.propose([pt(4, None)], unread_pages=2)["code"]
        == comparison.CODE_MANUAL
    )
    assert (
        review_code_proposal.propose([], reviews_ran=True)["code"]
        == comparison.CODE_APPROVED
    )


# ------------------------------------------------------------------------------------------ R2: every home


def _cells(data: bytes) -> dict[str, str]:
    ws = load_workbook(io.BytesIO(data)).worksheets[0]
    return {
        str(r[0]): str(r[2])
        for r in ws.iter_rows(min_row=1, max_row=30, values_only=True)
        if r[0] and len(r) > 2
    }


def _all_text(data: bytes) -> str:
    wb = load_workbook(io.BytesIO(data))
    return "\n".join(
        str(c)
        for ws in wb.worksheets
        for r in ws.iter_rows(values_only=True)
        for c in r
        if c is not None
    )


def test_r2_the_page_and_the_team_file_say_the_same_while_points_are_open_and_the_contractor_file_proposes_nothing():
    doc, _rc, _ai, client = world_with_both()
    listing = points_of(client, doc)
    comment = next(p for p in listing["points"] if p["rank"] != 1)
    assert decide(client, doc, comment["id"], "keep").status_code == 200
    listing = points_of(client, doc)
    left, of = listing["of"] - listing["decided"], listing["of"]
    assert left > 0
    line = listing["proposed_code"]["line"]
    assert listing["proposed_code"]["code"] is None
    assert line.startswith(
        f"No review code proposed yet: {left} of {of} points still to decide"
    )
    team = crs_one.build_team(doc, scope_all())
    assert (
        _cells(team)["Proposed review code:"] == line
    )  # sheet 1 takes the page's line, from the one place
    assert f"{listing['decided']} of {of} decided" in _all_text(
        team
    )  # the same count the sheet states
    contractor = crs_one.build_contractor(doc, scope_all())
    assert not any(c in _all_text(contractor) for c in APPROVING)


def test_r3_the_team_file_shows_the_code_once_every_point_is_decided():
    doc, _rc, _ai, client = world_with_both()
    for p in points_of(client, doc)["points"]:
        state = "remove" if p["rank"] == 1 else "keep"
        assert (
            decide(client, doc, p["id"], state, reason="invented reason").status_code
            == 200
        )
    listing = points_of(client, doc)
    assert listing["decided"] == listing["of"]
    assert listing["proposed_code"]["code"] == comparison.CODE_APPROVED_WITH_COMMENTS
    assert (
        _cells(crs_one.build_team(doc, scope_all()))["Proposed review code:"]
        == comparison.CODE_APPROVED_WITH_COMMENTS
    )


# ------------------------------------------------------------------------------------------ R4: books not held


def test_r4_books_not_held_is_the_run_record_and_every_row_marked_book_missing_each_once():
    rows = [
        {"_book_missing": "BOOK-77"},
        {"_book_missing": "book 77"},
        {"_book_missing": None},
        {"_book_missing": "BOOK-90"},
        {},
    ]
    assert review_points.books_not_held(["BOOK-12"], rows) == [
        "BOOK-12",
        "BOOK-77",
        "BOOK-90",
    ]
    assert review_points.books_not_held([], [{}, {"_book_missing": ""}]) == []


def test_r4_the_sheet_rule_books_not_held_counts_a_rule_check_row_whose_book_is_missing():
    doc = _submittal()
    rc = _run(doc, recommended=None)
    _finding(  # our checklist's check cites a book the library does not hold (no linked document, none of that name)
        doc,
        rc,
        "NON_COMPLIANT",
        origin="datasheet_check",
        standard_document_id=None,
        standard_clause="BOOK-77 4.1",
        standard_page=None,
    )
    client = _client(doc)
    listing = points_of(client, doc)
    missing = [
        p
        for p in listing["points"]
        if str(p.get("reason_words") or "").startswith(review_points.BOOK_MISSING)
    ]
    assert missing, "the invented world must hold a row marked Book missing"
    assert listing["counts"]["not_held"]["total"] == 1
    wb = load_workbook(io.BytesIO(crs_one.build_team(doc, scope_all())))
    held = wb[crs_one.HELD_SHEET]
    text = "\n".join(
        str(c) for r in held.iter_rows(values_only=True) for c in r if c is not None
    )
    assert "1 rule book(s) not held" in text and "BOOK-77" in text
