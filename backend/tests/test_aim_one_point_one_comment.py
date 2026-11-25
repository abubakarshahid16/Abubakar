"""One point, one comment (update 7, after the live datasheet: one point sent twice, and a card of an always-on item listing six
unrelated fields). Invented words only; no model, no call."""

from __future__ import annotations

import pytest

from app import aim_review_view as V
from app.aim_review.always import TOPIC as ALWAYS
from tests.test_g_asks import point


@pytest.fixture(autouse=True)
def _update_on(monkeypatch):
    """This file tests a part of an update that goes live switched off (`aim_review.updates`): switched on here."""
    from app.config import settings

    monkeypatch.setattr(settings, "aim_u7b_enabled", True)



def _lines(comments):
    return sorted(c["lines"] for c in comments)


def test_lines_of_one_item_in_different_editor_groups_each_join_their_own_group():
    pts = [
        point(1, field="Inlet head", page=2, item="C1", same_point_as=1),
        point(2, field="Inlet head margin", page=2, item="C2", same_point_as=1),
        point(
            3, field="Inlet head", page=2, item="G3", topic=ALWAYS, same_point_as=1
        ),  # the same point, an always-on item
        point(4, field="Gas content", page=3, item="G3", topic=ALWAYS, same_point_as=4),
        point(5, field="Gas content level", page=3, item="C5", same_point_as=4),
    ]
    comments, _ = V.comments_and_confirmations(pts)
    assert _lines(comments) == [
        [1, 2, 3],
        [4, 5],
    ]  # each point once; before: [1, 2], [3, 4], [5] (point 1 sent twice)


def test_an_always_on_items_places_are_separate_comments_without_an_editor_group():
    pts = [
        point(n, field=f, page=2, item="G3", topic=ALWAYS)
        for n, f in ((1, "Speed"), (2, "Flow"), (3, "Speed"))
    ]
    comments, _ = V.comments_and_confirmations(pts)
    assert _lines(comments) == [[1, 3], [2]]


def test_an_ordinary_items_lines_with_no_group_stay_one_comment_and_nothing_is_lost():
    pts = [
        point(1, field="Wall", page=2, item="C1"),
        point(2, field="Wall", page=5, item="C1"),
        point(3, field="Rating", item="C2"),
    ]
    comments, _ = V.comments_and_confirmations(pts)
    assert _lines(comments) == [[1, 2], [3]]
    assert sorted(n for c in comments for n in c["lines"]) == [1, 2, 3]


def test_two_lines_at_one_place_the_editor_kept_apart_are_never_one_comment():
    """The same field and page (same-place merge) or the same specific quote (same-finding merge) never joins two lines the
    editor put in different groups; each joins its own group. With no editor marks, the place merge is as before."""
    pts = [
        point(1, field="Casing", page=4, item="C1", same_point_as=1),
        point(2, field="Casing", page=4, item="C2", same_point_as=3),
        point(3, field="Bolting", page=6, item="C3", same_point_as=3),
    ]
    comments, _ = V.comments_and_confirmations(pts)
    assert _lines(comments) == [[1], [2, 3]]
    plain = [
        point(1, field="Casing", page=4, item="C1"),
        point(2, field="Casing", page=4, item="C2"),
    ]
    assert _lines(V.comments_and_confirmations(plain)[0]) == [[1, 2]]
