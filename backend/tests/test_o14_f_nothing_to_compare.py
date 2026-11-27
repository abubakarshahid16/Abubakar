"""R5 (H's one-real-file pass, 27 Nov 2026): three counts of 0 compare nothing. A general review that stopped before reading its paper
had 0 points, 0 database lines and 0 file rows, and the completeness check said "all three agree": a pass with nothing measured
(REVIEW.md: "0 == 0 is not a pass"). Now it says "nothing to compare", the file is not given out, and the run cannot be signed off.
Invented documents and values only."""

from __future__ import annotations

import json

import pytest

from app import access, aim_review_completeness, aim_review_signoff, aim_review_store, aim_review_view, db
from app.crs_completeness import Incomplete
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, client, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture (a fresh database per test)

EMPTY_PAPER = "doc_inv_empty"
EMPTY_RUN = "gen_run_empty"


@pytest.fixture
def two_papers(temp_db):  # noqa: F811
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    _doc(EMPTY_PAPER, "invented-empty.pdf")
    make_run()  # a normal finished run: 6 points
    make_run(EMPTY_RUN, [], status="stopped", paper=EMPTY_PAPER)  # stopped before reading: 0 points


def test_zero_points_is_nothing_to_compare_not_all_three_agree(two_papers):
    page = client(EMPTY_PAPER, BOOK).get(f"/api/reviews/papers/{EMPTY_PAPER}/general").json()["completeness"]
    assert (page["page"], page["database"], page["file_rows"]) == (0, 0, 0)
    assert page["ok"] is False and page["nothing_to_compare"] is True
    assert page["sentence"] == aim_review_completeness.NOTHING_TO_COMPARE
    assert "agree" not in page["sentence"]


def test_zero_points_gives_no_file(two_papers):
    r = client(EMPTY_PAPER, BOOK).get(f"/api/reviews/papers/{EMPTY_PAPER}/general/sheet")
    assert r.status_code == 409
    assert r.json()["detail"]["message"] == aim_review_completeness.NOTHING_TO_COMPARE
    with pytest.raises(Incomplete):
        aim_review_completeness.file_or_refuse(EMPTY_RUN, access.unrestricted_scope())


def test_a_normal_run_still_agrees(two_papers):
    page = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()["completeness"]
    assert page["ok"] is True and page["nothing_to_compare"] is False and page["sentence"] is None
    assert (page["page"], page["database"], page["file_rows"]) == (6, 6, 6)


def test_the_stored_check_says_nothing_to_compare(two_papers):
    rep = aim_review_completeness.record_after_run(EMPTY_RUN)
    assert rep["ok"] is False and rep["nothing_to_compare"] is True
    stored = json.loads(aim_review_store.run(db.connect(), EMPTY_RUN)["completeness_json"])
    assert stored["nothing_to_compare"] is True and stored["sentence"] == aim_review_completeness.NOTHING_TO_COMPARE


@pytest.mark.parametrize("status", ["stopped", "done"])
def test_an_empty_review_cannot_be_signed_off(temp_db, status):  # noqa: F811
    """Stopped: refused for stopping. Finished with 0 points: refused by the completeness check (nothing to compare)."""
    _doc(EMPTY_PAPER, "invented-empty.pdf")
    make_run(EMPTY_RUN, [], status=status, paper=EMPTY_PAPER)
    conn = db.connect()
    run = dict(aim_review_store.run(conn, EMPTY_RUN))
    view = aim_review_view.build(conn, run, access.unrestricted_scope())
    with pytest.raises(aim_review_signoff.Refused) as e:
        aim_review_signoff.sign(conn, run, view, "eng", "Approved")
    said = str(e.value)
    assert ("stopped early" in said) if status == "stopped" else (said == aim_review_completeness.NOTHING_TO_COMPARE)
    assert RUN != EMPTY_RUN
