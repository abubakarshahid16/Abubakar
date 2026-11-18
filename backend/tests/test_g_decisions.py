# ruff: noqa: F811
"""The engineer's decision on each comment of a general review (accept / edit / reject), append-only. Invented papers only."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import access, db
from app import aim_review_sheet as S
from app.main import app
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, _sheet, client, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


@pytest.fixture
def world(temp_db):
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run()


URL = f"/api/reviews/papers/{PAPER}/general/decision"


def _decide(c, n=1, state="accept", **extra):
    return c.post(URL, json={"run_id": RUN, "comment": n, "state": state, **extra})


def _page(c):
    r = c.get(f"/api/reviews/papers/{PAPER}/general?run_id={RUN}")
    assert r.status_code == 200, r.text
    return r.json()


def _rows():
    with db.connect() as conn:
        return conn.execute(
            "SELECT * FROM aim_comment_decisions ORDER BY decided_at, rowid"
        ).fetchall()


def test_an_undecided_comment_says_so_on_the_page(world):
    page = _page(client(PAPER, BOOK))
    assert page["comments"] and all(c["decision"] is None for c in page["comments"])


def test_accept_records_who_and_when_and_the_page_shows_it(world):
    c = client(PAPER, BOOK)
    r = _decide(c, 1, "accept")
    assert r.status_code == 200, r.text
    d = _page(c)["comments"][0]["decision"]
    assert (
        d["state"] == "accept"
        and d["words"] == "Accepted"
        and d["by"] == "eng"
        and d["revisions"] == 1
        and d["at"]
    )
    assert _page(c)["comments"][1]["decision"] is None  # another comment is untouched


def test_edit_needs_text_and_keeps_the_original(world):
    c = client(PAPER, BOOK)
    assert _decide(c, 1, "edit").status_code == 422
    assert _decide(c, 1, "edit", text="  Engineer's own words.  ").status_code == 200
    first = _page(c)["comments"][0]
    assert (
        first["decision"]["text"] == "Engineer's own words."
        and first["decision"]["original"] == first["we_ask"]
    )


def test_reject_needs_a_one_line_reason(world):
    c = client(PAPER, BOOK)
    assert _decide(c, 1, "reject").status_code == 422
    assert _decide(c, 1, "reject", reason="short").status_code == 422
    assert (
        _decide(c, 1, "reject", reason="The paper states it on page 3.").status_code
        == 200
    )
    assert (
        _page(c)["comments"][0]["decision"]["reason"]
        == "The paper states it on page 3."
    )


def test_decisions_are_append_only_and_the_latest_wins(world):
    c = client(PAPER, BOOK)
    _decide(c, 1, "accept")
    _decide(c, 1, "reject", reason="Not a real problem on this valve.")
    d = _page(c)["comments"][0]["decision"]
    assert d["state"] == "reject" and d["revisions"] == 2
    assert [r["state"] for r in _rows()] == ["accept", "reject"]  # both rows stay


def test_the_audit_holds_words_and_ids_never_the_engineers_text(world):
    c = client(PAPER, BOOK)
    _decide(c, 1, "edit", text="A private engineering remark.")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT action, detail FROM audit_events WHERE action = 'general_comment_decided'"
        ).fetchall()
    assert len(rows) == 1 and "private engineering remark" not in rows[0]["detail"]
    assert json.loads(rows[0]["detail"])["state"] == "edit"


def test_an_unknown_comment_is_a_404_and_writes_nothing(world):
    c = client(PAPER, BOOK)
    assert _decide(c, 999).status_code == 404
    assert (
        _decide(c, 1, part="confirmation").status_code == 404
    )  # this run has no confirmation 1
    assert _rows() == []


def test_only_a_signed_in_user_who_may_read_the_paper_can_decide(world):
    assert (
        _decide(client(BOOK), 1).status_code == 404
    )  # may not read the paper: indistinguishable from none
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({PAPER}), unrestricted=True
    )
    assert _decide(TestClient(app), 1).status_code == 401  # nobody to name
    assert _rows() == []


def test_a_decision_made_on_a_comment_that_is_no_longer_there_is_not_carried_to_another(
    world,
):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO aim_comment_decisions (id, run_id, paper_document_id, comment_key, part, state, decided_by, decided_at)"
            " VALUES ('x', ?, ?, '98,99', 'comment', 'accept', 'eng', '2026-11-18T10:00:00+00:00')",
            (RUN, PAPER),
        )
    assert all(c["decision"] is None for c in _page(client(PAPER, BOOK))["comments"])


def test_the_excel_engineer_decision_column_is_filled_from_the_decision(world):
    c = client(PAPER, BOOK)
    _decide(c, 1, "reject", reason="The paper states it on page 3.")
    wb = _sheet(c.get(f"/api/reviews/papers/{PAPER}/general/sheet?run_id={RUN}"))
    at = S.COMMENT_HEADERS.index("Engineer decision")
    rows = [
        r
        for r in wb[S.COMMENTS].iter_rows(min_row=S.HEADER_ROW + 1, values_only=True)
        if r[0] is not None
    ]
    assert rows[0][at].startswith("Rejected by eng, ") and rows[0][at].endswith(
        "The paper states it on page 3."
    )
    assert rows[1][at] is None  # undecided: empty, never "pending"
