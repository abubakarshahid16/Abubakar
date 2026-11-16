"""Order 14 lane D: the two line-reading deferral finders (`agent_review_request.deferred_mark`, the reviewer's; and
`agent_review_absence.deferred_mark`, the absence proof's) see the "*" vendor-to-fill mark on the field's own line, and
not a footnote star after a stated value. Invented lines only."""

from __future__ import annotations

from app import agent_review_absence as absence
from app import agent_review_request as request

PAGES = {
    1: "GENERAL DATA\nSERVICE  COOLING WATER",
    2: "COUPLING MAKE        ______*________\nMOTOR OUTPUT  250 kW  *\nSEAL CHAMBER PRESSURE  * barg",
}


class _Pages:
    def page(self, doc, n):
        return PAGES.get(n) if doc == "paper" else None


def test_the_absence_finder_sees_a_star_blank_and_a_star_before_a_unit():
    assert absence.deferred_mark("coupling make", PAGES) == 2
    assert absence.deferred_mark("seal chamber pressure", PAGES) == 2


def test_the_reviewer_finder_sees_a_star_blank():
    assert request.deferred_mark("coupling make", _Pages(), "paper", 2) == 2


def test_a_footnote_star_after_a_stated_value_is_no_deferral():
    assert absence.deferred_mark("motor output", PAGES) is None
    assert request.deferred_mark("motor output", _Pages(), "paper", 2) is None


def test_a_field_with_no_mark_is_no_deferral():
    assert absence.deferred_mark("service", PAGES) is None
