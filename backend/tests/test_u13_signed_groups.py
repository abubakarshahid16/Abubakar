# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""A signed review keeps the comments it was signed with (G7 audit, lead-4, 26 Nov 2026): on live, a later update regrouped a
signed review's lines, and its page showed signed comments split into undecided ones beside a sign-off that still stood. Here a
"later update" is simulated by a grouping that joins two signed comments: the signed review still shows its signed comments with
their decisions; an unsigned review takes today's grouping. Invented papers and values only (`test_aim_sheet_rule`'s run)."""

from __future__ import annotations

import pytest

from app import aim_review_signed_groups, aim_review_view
from app.aim_review_decisions import key_of
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import CODE, client

BASE = f"/api/reviews/papers/{PAPER}/general"
UNSIGNED = "run-invented-unsigned"


@pytest.fixture
def signed(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(RUN)
    make_run(UNSIGNED, created="2026-11-19T10:00:00Z")
    c = client(PAPER, BOOK)
    page = c.get(f"{BASE}?run_id={RUN}").json()
    assert c.post(f"{BASE}/accept-rest", json={"run_id": RUN}).status_code == 200
    assert (
        c.post(f"{BASE}/signoff", json={"run_id": RUN, "review_code": CODE}).status_code
        == 200
    )
    return c, [key_of(cm) for cm in page["comments"]]


def _contractor(c):
    r = c.get(f"{BASE}/sheet", params={"run_id": RUN, "copy": "contractor"})
    assert r.status_code == 200
    return r.content


def _a_later_update_that_joins_two_comments(monkeypatch):
    """Today's grouping joins the first two comments into one (as an update that merges more would)."""
    real = aim_review_view.comments_and_confirmations

    def joined(points):
        comments, confirmations = real(points)
        if len(comments) < 2:
            return comments, confirmations
        by_n = {p["n"]: p for p in points}
        first, second, *rest = comments
        lines = sorted(
            [
                *(first.get("lines") or [first["n"]]),
                *(second.get("lines") or [second["n"]]),
            ]
        )
        return [
            aim_review_view._same_point([by_n[n] for n in lines]),
            *rest,
        ], confirmations

    monkeypatch.setattr(aim_review_view, "comments_and_confirmations", joined)


def test_a_signed_review_keeps_its_signed_comments_after_a_regrouping(
    signed, monkeypatch
):
    c, signed_keys = signed
    assert len(signed_keys) >= 2
    issued = _contractor(c)
    _a_later_update_that_joins_two_comments(monkeypatch)
    page = c.get(f"{BASE}?run_id={RUN}").json()
    assert [
        key_of(cm) for cm in page["comments"]
    ] == signed_keys  # the comments it was signed with
    assert all(cm["decision"] for cm in page["comments"])  # each with its decision
    assert (
        page["signoff"]["state"] == "signed" and page["signoff"]["undecided_count"] == 0
    )
    assert (
        c.get(f"{BASE}/sheet", params={"run_id": RUN}).status_code == 200
    )  # the team file is still complete
    assert _contractor(c) == issued  # the contractor copy, byte for byte


def test_an_unsigned_review_takes_todays_grouping(signed, monkeypatch):
    c, signed_keys = signed
    _a_later_update_that_joins_two_comments(monkeypatch)
    page = c.get(f"{BASE}?run_id={UNSIGNED}").json()
    assert (
        len(page["comments"]) == len(signed_keys) - 1
    )  # joined, as today's code groups it


def test_a_signed_group_with_a_line_no_longer_sent_is_not_rebuilt(signed, monkeypatch):
    """Never guessed: a signed group whose lines are not all still sent keeps today's grouping for its lines."""
    from app import aim_review

    c, signed_keys = signed
    first = [int(n) for n in signed_keys[0].split(",")]
    real = aim_review.sendable
    monkeypatch.setattr(
        aim_review, "sendable", lambda p: real(p) and p["n"] not in first
    )
    page = c.get(f"{BASE}?run_id={RUN}").json()
    assert signed_keys[0] not in [key_of(cm) for cm in page["comments"]]


def test_without_a_sign_off_the_grouping_is_exactly_todays(temp_db, monkeypatch):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(UNSIGNED)
    from app import aim_review_store, db

    with db.connect() as conn:
        run = aim_review_store.run(conn, UNSIGNED)
        rows = aim_review_store.lines(conn, UNSIGNED)
        points = [aim_review_view.line_view(r, i, False) for i, r in enumerate(rows, 1)]
        assert aim_review_signed_groups.groups(
            conn, run, points
        ) == aim_review_view.comments_and_confirmations(points)
