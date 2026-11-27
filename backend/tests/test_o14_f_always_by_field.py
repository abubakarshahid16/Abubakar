# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""One comment per field for the ALWAYS-ON items (F, 27 Nov 2026). A fresh reader marked a live pump comment WRONG: it was titled
one field and carried five other, unrelated missing entries, because the always-on item G3 ("entries the paper leaves blank") made
ONE comment of all its findings. The one-point-one-comment fix existed behind AIM_U7B_ENABLED (off); its view part is now its own
way-back switch, ON. A review not signed yet keeps every group an engineer has already decided, so no regrouping takes a decision
off its comment. Invented papers, fields and values only."""

from __future__ import annotations

import pytest

from app.aim_review_decisions import key_of
from app.config import settings
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, _line, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import client

BASE = f"/api/reviews/papers/{PAPER}/general"
ALWAYS = "always checked"


def _g3(i: int, field: str, page: int) -> dict:
    return _line(i, "Question", "Question", item_id="G3", topic=ALWAYS, field=field, page=page, quote=f"{field}: (blank)",
                 comment=f"The paper leaves {field} blank.", source="not from a held standard", standard="", clause="")  # fmt: skip


LINES = [
    _line(1, "Not met", "Fail, compared by code"),
    _g3(2, "Invented entry alpha", 3),
    _g3(3, "Invented entry beta", 4),
    _g3(4, "Invented entry gamma", 5),
]


@pytest.fixture
def world(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(RUN, LINES)
    return client(PAPER, BOOK)


def _page(c) -> dict:
    r = c.get(f"{BASE}?run_id={RUN}")
    assert r.status_code == 200
    return r.json()


def _g_comments(page: dict) -> list[dict]:
    return [cm for cm in page["comments"] + (page.get("confirmations") or []) if cm.get("item_id") == "G3"]


def test_the_switch_is_on_by_default():
    from app.config import Settings

    assert Settings.model_fields["aim_always_by_field_enabled"].default is True


def test_each_always_on_finding_is_its_own_comment_and_off_is_one_comment(world, monkeypatch):
    monkeypatch.setattr(settings, "aim_always_by_field_enabled", True)
    on = _page(world)
    assert sorted(len(cm["lines"]) for cm in _g_comments(on)) == [1, 1, 1]
    monkeypatch.setattr(settings, "aim_always_by_field_enabled", False)
    off = _page(world)
    assert [len(cm["lines"]) for cm in _g_comments(off)] == [3]  # the way back: as before
    # the same points either way: only how they are grouped into comments changes
    assert len(on["points"]) == len(off["points"]) == len(LINES)


def test_the_file_agrees_with_the_page_with_the_switch_on(world, monkeypatch):
    monkeypatch.setattr(settings, "aim_always_by_field_enabled", True)
    page = _page(world)
    r = world.get(f"{BASE}/sheet", params={"run_id": RUN})
    assert r.status_code == 200  # completeness (page = database = file rows) holds, or the download is refused
    assert page["completeness"]["ok"] is True


def test_a_decided_comment_keeps_its_lines_on_a_review_not_signed_yet(world, monkeypatch):
    """The engineer decided the joined G3 comment before the regrouping; after it, that comment is still there with its lines, and
    the undecided points of the review take today's grouping."""
    monkeypatch.setattr(settings, "aim_always_by_field_enabled", False)
    joined = _g_comments(_page(world))[0]
    assert world.post(f"{BASE}/decision", json={"run_id": RUN, "comment": joined["n"], "state": "accept"}).status_code == 200
    monkeypatch.setattr(settings, "aim_always_by_field_enabled", True)
    after = _page(world)
    assert key_of(joined) in [key_of(cm) for cm in after["comments"] + (after.get("confirmations") or [])]
    assert after["completeness"]["ok"] is True
