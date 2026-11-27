# ruff: noqa: F811 - the fixtures are imported by name and taken as arguments
"""A rough draft from the local model never leaves as if it were a finished review (lead-5, 27 Nov 2026: a local review with 9
WRONG of 23 comments sat on live beside Claude ones). Its team file is given only with the engineer's explicit OK
(`rough_draft_ok`, which the page asks for first); a signed rough draft and a Claude review download as before. Invented values."""

from __future__ import annotations

import json

import pytest

from app import aim_review_store, db
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import CODE, client

BASE = f"/api/reviews/papers/{PAPER}/general"
LOCAL_CALLS = [
    {
        "step": "aim_judge",
        "model": "invented-local-model",
        "engine": "local",
        "usd": 0.0,
        "ok": True,
        "code": None,
    }
]


def _make(local: bool) -> None:
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(RUN)
    if local:
        with db.connect() as conn:
            conn.execute(
                f"UPDATE {aim_review_store.RUNS} SET calls_json = ? WHERE run_id = ?",
                (json.dumps(LOCAL_CALLS), RUN),
            )


def _sheet(c, **params):
    return c.get(f"{BASE}/sheet", params={"run_id": RUN, **params})


@pytest.fixture
def local_world(temp_db):
    _make(local=True)
    return client(PAPER, BOOK)


@pytest.fixture
def claude_world(temp_db):
    _make(local=False)
    return client(PAPER, BOOK)


def test_an_unsigned_rough_draft_needs_the_engineers_ok(local_world):
    r = _sheet(local_world)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "confirm_required"
    assert "rough draft by the AI on this computer" in r.json()["detail"]["message"]
    ok = _sheet(local_world, rough_draft_ok="true")
    assert (
        ok.status_code == 200 and ok.content[:2] == b"PK"
    )  # the same file, once the engineer says they will check it


def test_a_claude_review_downloads_as_before(claude_world):
    assert _sheet(claude_world).status_code == 200


def test_a_signed_rough_draft_is_the_engineers_and_downloads_without_a_question(
    local_world,
):
    page = local_world.get(f"{BASE}?run_id={RUN}").json()
    for cm in page["comments"] + (
        page.get("confirmations") or []
    ):  # a rough draft is decided one by one (no "Accept the rest")
        r = local_world.post(
            f"{BASE}/decision",
            json={"run_id": RUN, "comment": cm["n"], "state": "accept"},
        )
        assert r.status_code == 200, r.text
    assert (
        local_world.post(
            f"{BASE}/signoff", json={"run_id": RUN, "review_code": CODE}
        ).status_code
        == 200
    )
    assert _sheet(local_world).status_code == 200
