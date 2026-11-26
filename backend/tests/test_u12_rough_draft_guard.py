# ruff: noqa: F811 - the fixture is imported by name and taken as an argument
"""A local rough draft is never treated as the review of a file (lead-4's walk of the live app, 26 Nov 2026).

1. THE FACE of a file on the Reviews list and the dashboard is its newest SIGNED review, else its newest review on Claude, else its
   newest review; a newer local draft never hides the Claude review, and every row names its engine.
2. NO BULK ACCEPT on a review made on the local model: the page offers none and the server refuses it, writing nothing; each comment is
   decided one by one, and the sign-off record says it was made from a rough draft (the page, the audit's counts and the team file).
Invented papers, books and values only (`test_aim_sheet_rule`'s run)."""

from __future__ import annotations

import json

from app import aim_review_face, aim_review_gate, aim_review_runs, aim_review_store, db
from app import aim_review_signoff as SO
from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _doc, _sheet, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import CODE, _rows, client

LOCAL_RUN = "run-invented-local"
LATER = "2026-11-26T08:00:00Z"
BASE = f"/api/reviews/papers/{PAPER}/general"


def _make_local(run_id: str = LOCAL_RUN, created: str = LATER) -> None:
    make_run(run_id, created=created)
    calls = [
        {
            "step": "aim_judge",
            "model": "invented-local:9b",
            "engine": "local",
            "usd": 0,
            "ok": True,
            "code": None,
        }
    ]
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET calls_json = ? WHERE run_id = ?",
            (json.dumps(calls), run_id),
        )


def _world() -> None:
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")


def _entries(newest_only: bool = False) -> list[dict]:
    with db.connect() as conn:
        return aim_review_runs.entries(
            conn, frozenset({PAPER, BOOK}), newest_only=newest_only
        )


def test_a_newer_local_draft_does_not_hide_the_claude_review_and_each_row_names_its_engine(
    temp_db,
):
    _world()
    make_run(RUN)  # Claude, 18 Nov
    _make_local()  # local, 26 Nov: newer
    rows = {e["review_run_id"]: e for e in _entries()}
    assert rows[RUN]["face"] is True and rows[LOCAL_RUN]["face"] is False
    assert rows[RUN]["engine_words"] == "Claude"
    assert (
        rows[LOCAL_RUN]["engine"] == "local"
        and aim_review_gate.LOCAL_ROUGH_DRAFT in rows[LOCAL_RUN]["engine_words"]
    )
    assert [e["review_run_id"] for e in _entries(newest_only=True)] == [
        RUN
    ]  # the dashboard's newest = the face
    listed = client(PAPER, BOOK).get("/api/reviews/runs").json()["runs"]
    assert {r["review_run_id"]: r.get("face") for r in listed}.get(RUN) is True


def test_the_face_rule_signed_then_claude_then_newest():
    def row(run_id, created, engine, signoff=None):
        return {"review_run_id": run_id, "submittal_document_id": "p", "created_at": created, "engine": engine,
                "general_signoff": signoff}  # fmt: skip

    claude_old = row("c1", "2026-11-01", "claude", aim_review_face.SIGNED)
    claude_new = row("c2", "2026-11-10", "claude")
    local_new = row("l1", "2026-11-20", "local")
    assert aim_review_face.face_ids([claude_old, claude_new, local_new]) == {
        "c1"
    }  # signed wins
    assert aim_review_face.face_ids([claude_new, local_new]) == {
        "c2"
    }  # else the newest on Claude
    assert aim_review_face.face_ids([local_new]) == {"l1"}  # else the newest
    changed = row("c3", "2026-11-25", "claude", aim_review_face.CHANGED)
    assert aim_review_face.face_ids([claude_new, changed, local_new]) == {
        "c3"
    }  # changed since sign-off: not signed


def test_a_local_draft_offers_no_bulk_accept_and_the_server_refuses_one_writing_nothing(
    temp_db,
):
    _world()
    _make_local()
    c = client(PAPER, BOOK)
    page = c.get(f"{BASE}?run_id={LOCAL_RUN}").json()
    assert page["signoff"]["bulk_accept"] is False
    assert page["signoff"]["rough_draft_words"] == SO.ROUGH_DRAFT_NO_BULK
    r = c.post(f"{BASE}/accept-rest", json={"run_id": LOCAL_RUN})
    assert (
        r.status_code == 409 and r.json()["detail"]["message"] == SO.ROUGH_DRAFT_NO_BULK
    )
    assert _rows("aim_comment_decisions") == []


def test_a_claude_review_keeps_its_bulk_accept(temp_db):
    _world()
    make_run(RUN)
    c = client(PAPER, BOOK)
    page = c.get(f"{BASE}?run_id={RUN}").json()
    assert (
        page["signoff"]["bulk_accept"] is True
        and page["signoff"]["rough_draft_words"] is None
    )
    assert c.post(f"{BASE}/accept-rest", json={"run_id": RUN}).status_code == 200


def test_a_sign_off_of_a_local_draft_decided_one_by_one_says_it_was_made_from_a_rough_draft(
    temp_db,
):
    _world()
    _make_local()
    c = client(PAPER, BOOK)
    page = c.get(f"{BASE}?run_id={LOCAL_RUN}").json()
    for comment in page["comments"]:
        r = c.post(
            f"{BASE}/decision",
            json={"run_id": LOCAL_RUN, "comment": comment["n"], "state": "accept"},
        )
        assert r.status_code == 200, r.text
    for item in page.get("confirmations") or []:
        r = c.post(
            f"{BASE}/decision",
            json={"run_id": LOCAL_RUN, "confirmation": item["n"], "state": "accept"},
        )
        assert r.status_code == 200, r.text
    r = c.post(f"{BASE}/signoff", json={"run_id": LOCAL_RUN, "review_code": CODE})
    assert r.status_code == 200, r.text
    assert r.json()["signoff"]["signed"]["rough_draft"] == SO.ROUGH_DRAFT_SIGNED
    (row,) = _rows("aim_signoffs")
    assert json.loads(row["counts_json"])["rough_draft"] is True
    summary = _sheet(c.get(f"{BASE}/sheet?run_id={LOCAL_RUN}"))["Summary"]
    text = "\n".join(
        str(v) for r in summary.iter_rows(values_only=True) for v in r if v
    )
    assert SO.ROUGH_DRAFT_SIGNED in text  # the team file's Sign-off row
