# ruff: noqa: F811 - the fixture is imported by name and taken as an argument
"""THE LEARNER v1 (planner 26 Nov 2026 16:03): a comment an engineer rejected on an earlier review of the same kind of paper, on
the same rule (standard, clause, field), is not raised again as new. It moves to the team-only "Rejected before" section with
"rejected before on <date>, reason: <the engineer's words>"; it never disappears, it is never sent, and every count still adds
up. Off by default: with the switch off every review is exactly as before. Invented papers, books and values only."""

from __future__ import annotations

import pytest

from app import (
    aim_review_contractor,
    aim_review_learner,
    aim_review_sheet,
    aim_review_store,
    aim_review_view,
    db,
)
from app.config import settings
from tests.test_aim_sheet_rule import BOOK, PAPER, _doc, _sheet, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import client

EARLIER, LATER = "run-invented-earlier", "run-invented-later"
REASON = "The datasheet answers it on page 3; not a finding."
BASE = f"/api/reviews/papers/{PAPER}/general"


def _two_reviews(reject: bool = True) -> None:
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(EARLIER, created="2026-11-20T10:00:00Z")
    make_run(LATER, created="2026-11-26T10:00:00Z")
    if reject:
        c = client(PAPER, BOOK)
        first = c.get(f"{BASE}?run_id={EARLIER}").json()["comments"][0]["n"]
        r = c.post(
            f"{BASE}/decision",
            json={
                "run_id": EARLIER,
                "comment": first,
                "state": "reject",
                "reason": REASON,
            },
        )
        assert r.status_code == 200, r.text


def _view(run_id: str) -> dict:
    with db.connect() as conn:
        return aim_review_view.build(conn, aim_review_store.run(conn, run_id))


def test_with_the_switch_off_nothing_moves(temp_db):
    _two_reviews()
    view = _view(LATER)
    assert view["rejected_before"] == [] and view["counts"]["comments"] == len(
        view["comments"]
    )


def test_a_comment_rejected_before_on_the_same_rule_moves_with_its_note_and_is_never_lost(
    temp_db, monkeypatch
):
    _two_reviews()
    off = _view(LATER)
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", True)
    on = _view(LATER)
    assert len(on["rejected_before"]) == 1
    moved = on["rejected_before"][0]
    day = moved["rejected_before"]["day"]
    assert (
        len(day) == 10
        and moved["rejected_before"]["note"]
        == f"rejected before on {day}, reason: {REASON}"
    )
    # never lost: the comments raised plus the comments moved are the comments there were
    assert len(on["comments"]) + len(on["rejected_before"]) == len(off["comments"])
    assert on["counts"]["comments"] == len(on["comments"])
    assert (
        on["counts"]["points"] == off["counts"]["points"]
    )  # every point stays on All points


def test_the_earlier_review_itself_is_unchanged_and_a_later_decision_keeps_the_comment(
    temp_db, monkeypatch
):
    _two_reviews()
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", True)
    assert _view(EARLIER)["rejected_before"] == []  # nothing earlier than it
    c = client(PAPER, BOOK)
    first = c.get(f"{BASE}?run_id={LATER}").json()
    assert len(first["rejected_before"]) == 1
    n = first["rejected_before"][0]["n"]
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", False)
    r = c.post(
        f"{BASE}/decision", json={"run_id": LATER, "comment": n, "state": "accept"}
    )
    assert r.status_code == 200, r.text
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", True)
    assert (
        _view(LATER)["rejected_before"] == []
    )  # this review's engineer decided it: it stays a comment


def test_a_rejection_that_was_later_reversed_or_on_another_kind_teaches_nothing(
    temp_db, monkeypatch
):
    _two_reviews()
    c = client(PAPER, BOOK)
    first = c.get(f"{BASE}?run_id={EARLIER}").json()["comments"][0]["n"]
    assert (
        c.post(
            f"{BASE}/decision",
            json={"run_id": EARLIER, "comment": first, "state": "accept"},
        ).status_code
        == 200
    )
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", True)
    assert (
        _view(LATER)["rejected_before"] == []
    )  # the latest decision there is no rejection
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET identity_json = ? WHERE run_id = ?",
            ('{"kind": "procedure"}', EARLIER),
        )
    assert _view(LATER)["rejected_before"] == []


def test_the_team_file_has_the_rejected_before_sheet_and_the_contractor_counts_still_add_up(
    temp_db, monkeypatch
):
    _two_reviews()
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", True)
    view = _view(LATER)
    sheets = _sheet(client(PAPER, BOOK).get(f"{BASE}/sheet?run_id={LATER}"))
    assert aim_review_sheet.REJECTED_BEFORE in sheets.sheetnames
    text = "\n".join(
        str(v)
        for r in sheets[aim_review_sheet.REJECTED_BEFORE].iter_rows(values_only=True)
        for v in r
        if v
    )
    assert REASON in text
    counts = aim_review_contractor.counts_of(view)
    assert counts["in_file"] + counts["not_issued"] == counts["points"]
    assert counts["reasons"].get(aim_review_contractor.REASON_REJECTED_BEFORE) == len(
        view["rejected_before"][0].get("lines") or [view["rejected_before"][0]["n"]]
    )


@pytest.mark.parametrize(
    "comment, key",
    [
        (
            {"standard": "STD-X", "clause": "4.1", "field": "Invented field 1"},
            ("std-x", "4.1", "invented field 1"),
        ),
        (
            {"standard": "STD-X", "clause": "", "field": "F"},
            None,
        ),  # no clause: no rule to match
        ({"standard": "", "clause": "4.1", "field": "F"}, None),
    ],
)
def test_the_rule_is_the_standard_the_clause_and_the_field(comment, key):
    assert aim_review_learner.rule_key(comment) == key


def test_a_rejection_on_a_paper_the_viewer_may_not_read_is_never_used_for_that_viewer(
    temp_db, monkeypatch
):
    """Rule 5: the reason of a rejection on another paper could carry that paper's words; a viewer who may not read it never
    gets it (the grants narrow, never widen)."""
    from app import access, aim_review_decisions

    other = "doc-invented-other"
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    _doc(other, "invented-other.pdf")
    make_run(EARLIER, created="2026-11-20T10:00:00Z", paper=other)
    make_run(LATER, created="2026-11-26T10:00:00Z")
    with db.connect() as conn:
        old = aim_review_view.build(conn, aim_review_store.run(conn, EARLIER))
        aim_review_decisions.record(
            conn, EARLIER, other, old["comments"][0], "comment", aim_review_decisions.REJECT,
            actor="u1", text=None, reason=REASON,
        )  # fmt: skip
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", True)
    reader = access.AccessScope(
        user_id="eng",
        allowed_document_ids=frozenset({PAPER, BOOK}),
        capabilities=frozenset(),
    )
    with db.connect() as conn:
        run = aim_review_store.run(conn, LATER)
        assert aim_review_view.build(conn, run, reader)["rejected_before"] == []
        assert (
            len(aim_review_view.build(conn, run)["rejected_before"]) == 1
        )  # the whole library (no viewer)


def test_a_moved_comment_leaves_the_summary_tiles(temp_db, monkeypatch):
    _two_reviews()
    off = _view(LATER)
    monkeypatch.setattr(settings, "learner_rejected_before_enabled", True)
    on = _view(LATER)
    moved_severity = on["rejected_before"][0]["severity"]
    assert (
        on["counts"]["by_severity"][moved_severity]
        == off["counts"]["by_severity"][moved_severity] - 1
    )
    assert (
        sum(on["counts"]["by_severity"].values())
        == sum(off["counts"]["by_severity"].values()) - 1
    )
