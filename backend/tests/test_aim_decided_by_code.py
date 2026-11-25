"""The planner's measure (19 Nov 2026): the share of a review's points that code decided, always as a count with its
denominator, on the results page and on the first sheet of the CRS. Invented values only."""

from __future__ import annotations

from app import aim_review_card
from app import aim_review_view as V
from app.aim_review_store import FAIL_BY_CODE, PASS_BY_CODE
from tests.test_aim_sheet_rule import (  # noqa: F401 - fixture
    BOOK,
    PAPER,
    _sheet,
    client,
    world,
)
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


def test_only_codes_own_verdicts_count_and_the_count_has_its_denominator():
    points = [{"shown_label": FAIL_BY_CODE}, {"shown_label": PASS_BY_CODE}, {"shown_label": "Question"},
              {"shown_label": "AI opinion"}, {"shown_label": "AI opinion: met"}]  # fmt: skip
    got = aim_review_card.decided_by_code(points, V.BOUNDARY)
    assert got["count"] == 2 and got["of"] == 5
    assert (
        got["sentence"].startswith("2 of 5 points decided by code")
        and "the other 3" in got["sentence"]
    )
    assert "%" not in got["sentence"] and V.BOUNDARY in got["sentence"]


def test_a_review_with_no_points_has_no_measure_never_zero_of_zero():
    assert aim_review_card.decided_by_code([], V.BOUNDARY) is None


def test_the_page_and_the_first_sheet_state_the_same_sentence(world):  # noqa: F811 - the fixture
    page = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    said = page["counts"]["decided_by_code"]
    assert said["of"] == page["counts"]["points"] and said["sentence"]
    wb = _sheet(client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet"))
    rows = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r and r[0]}
    assert rows["Decided by code"] == said["sentence"]
