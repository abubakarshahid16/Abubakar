# ruff: noqa: F811
"""The learner (#1912): an engineer's accept / edit / reject is remembered by rule and paper kind and used by the next review of
the same kind; behind its switch, OFF. Invented papers, rules and words only."""

from __future__ import annotations

import json
import sqlite3
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app import aim_review_learner as LR
from app import aim_review_store, db
from app.config import settings
from tests.test_aim_sheet_rule import BOOK, PAPER, _doc, make_run
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_g_signoff import client

EARLIER, LATER, OTHER_KIND = "gen_run_earlier", "gen_run_later", "gen_run_contract"
BASE = f"/api/reviews/papers/{PAPER}/general"
EDITED = "Invented engineer wording: state the invented value on the invented sheet."


@pytest.fixture
def world(temp_db, monkeypatch):
    monkeypatch.setattr(settings, "aim_review_learner_enabled", True)
    _doc(PAPER, "invented-paper.pdf")
    _doc(BOOK, "invented-book.pdf")
    make_run(EARLIER, created="2026-11-18T10:00:00Z")
    make_run(LATER, created="2026-11-19T10:00:00Z")
    make_run(OTHER_KIND, created="2026-11-19T11:00:00Z")
    with db.connect() as conn:
        conn.execute(f"UPDATE {aim_review_store.RUNS} SET identity_json = ? WHERE run_id = ?",
                     (json.dumps({"kind": "contract"}), OTHER_KIND))  # fmt: skip
        conn.commit()


def _decide(c, run, n, state, **kw):
    r = c.post(
        f"{BASE}/decision", json={"run_id": run, "comment": n, "state": state, **kw}
    )
    assert r.status_code == 200, r.text


def _page(c, run):
    r = c.get(f"{BASE}?run_id={run}")
    assert r.status_code == 200, r.text
    return {x["n"]: x for x in r.json()["comments"]}


def _team_notes(c, run) -> dict[int, str]:
    r = c.get(f"{BASE}/sheet?run_id={run}")
    assert r.status_code == 200, r.text
    ws = load_workbook(BytesIO(r.content))["Comments"]
    rows = list(ws.iter_rows(values_only=True))
    head = next(i for i, row in enumerate(rows) if "Team note (AI process)" in row)
    cols = rows[head]
    return {
        i: row[cols.index("Team note (AI process)")] or ""
        for i, row in enumerate(rows[head + 1 :], 1)
        if any(row)
    }


def test_a_comment_rejected_before_on_the_same_rule_and_kind_is_still_raised_with_a_team_note_only(
    world,
):
    c = client(PAPER, BOOK)
    _decide(
        c,
        EARLIER,
        1,
        "reject",
        reason="invented reason: the rule does not cover this field",
    )
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {LR.TABLE}")]
    assert [(r["rule_key"], r["paper_kind"], r["state"], r["run_id"]) for r in rows] == [
        (f"book:{BOOK}#4.1", "datasheet", "reject", EARLIER)]  # fmt: skip
    assert not {"text", "reason", "comment"} & set(
        rows[0]
    )  # ids only: the reason stays in the decisions table
    later = _page(c, LATER)
    assert set(later) == {1, 3, 5}  # never dropped
    with db.connect() as conn:
        decided = conn.execute(
            "SELECT decided_at FROM aim_comment_decisions"
        ).fetchone()[0]
    assert later[1]["learned"]["rejected_before"] == {
        "role": "an engineer",
        "on": decided[:10],
        "rules": 1,
    }
    assert (
        later[1]["comment"] == "invented comment 1"
        and "Rejected before" not in later[1]["we_ask"]
    )
    notes = _team_notes(c, LATER)
    assert any(
        n.startswith("Rejected before by an engineer on ") for n in notes.values()
    )
    assert sum("Rejected before" in n for n in notes.values()) == 1
    assert (
        "learned" not in _page(c, OTHER_KIND)[1]
    )  # another kind of paper: not the same rule use
    assert (
        "learned" not in _page(c, EARLIER)[1]
    )  # its own review shows its own decision, not a memory of it


def test_edited_wording_is_reused_for_the_same_rules_and_kind_and_a_later_decision_wins(
    world,
):
    c = client(PAPER, BOOK)
    _decide(c, EARLIER, 3, "edit", text=EDITED)
    later = _page(c, LATER)[3]
    assert (
        later["we_ask"] == EDITED == later["comment"] and later.get("decision") is None
    )  # still undecided in this review
    note = next(n for n in _team_notes(c, LATER).values() if "Wording reused" in n)
    assert 'The AI\'s own words: "invented comment 3"' in note
    _decide(
        c, EARLIER, 3, "accept"
    )  # the engineer accepted the AI's words after all: the edit no longer stands
    assert (
        "learned" not in _page(c, LATER)[3]
        and _page(c, LATER)[3]["we_ask"] == "invented comment 3"
    )


def test_a_comment_already_decided_in_this_review_is_left_as_decided(world):
    c = client(PAPER, BOOK)
    _decide(
        c,
        EARLIER,
        1,
        "reject",
        reason="invented reason: the rule does not cover this field",
    )
    _decide(c, LATER, 1, "accept")
    assert "learned" not in _page(c, LATER)[1]


def test_edited_words_are_never_reused_for_a_viewer_who_may_not_open_the_book(world):
    _decide(client(PAPER, BOOK), EARLIER, 3, "edit", text=EDITED)
    assert (
        "learned" not in _page(client(PAPER), LATER)[3]
    )  # the edit may hold the book's words


def test_switch_off_stores_nothing_and_changes_no_sheet_and_a_backfill_learns_later(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "aim_review_learner_enabled", False)
    c = client(PAPER, BOOK)
    _decide(
        c,
        EARLIER,
        1,
        "reject",
        reason="invented reason: the rule does not cover this field",
    )
    with db.connect() as conn:
        assert not LR._has(conn)
    assert "learned" not in _page(c, LATER)[1]
    monkeypatch.setattr(settings, "aim_review_learner_enabled", True)
    with db.connect() as conn:
        assert LR.backfill(conn) == 1 and LR.backfill(conn) == 0  # idempotent
    assert "rejected_before" in _page(c, LATER)[1]["learned"]


def test_learned_rows_are_never_changed_or_deleted(world):
    _decide(client(PAPER, BOOK), EARLIER, 1, "accept")
    with db.connect() as conn:
        for sql in (
            f"UPDATE {LR.TABLE} SET state = 'reject'",
            f"DELETE FROM {LR.TABLE}",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)


def test_a_rules_key_is_its_book_and_clause_else_its_named_book_else_its_checklist_item():
    assert (
        LR.rule_key({"book_document_id": "b1", "clause": " 4.2 "}, "k") == "book:b1#4.2"
    )
    assert (
        LR.rule_key({"standard": "Invented Std", "clause": "7"}, "k")
        == "named:invented std#7"
    )
    assert (
        LR.rule_key(
            {"standard": LR.HIDDEN_BOOK_WORDS, "clause": "7", "item_id": "C01"}, "k"
        )
        == "item:k#C01"
    )
    assert LR.rule_key({"item_id": "C01"}, None) is None


def test_an_edit_is_never_put_on_another_check_of_the_same_rule_or_across_a_rebuilt_checklist(
    world,
):
    """Replay of 26 Nov on a stored pump review: one rule judges several fields; 2 edits were first put on 4 comments."""
    from tests.test_aim_sheet_rule import LINES

    moved = [
        dict(ln, item_id="C33") if ln["item_id"] == "C03" else ln for ln in LINES
    ]  # another check of the same clause
    make_run("gen_run_other_field", moved, created="2026-11-20T10:00:00Z")
    c = client(PAPER, BOOK)
    _decide(c, EARLIER, 3, "edit", text=EDITED)
    assert _page(c, LATER)[3]["we_ask"] == EDITED  # the same rule on the same field
    assert (
        "learned" not in _page(c, "gen_run_other_field")[3]
    )  # the same rule, another check: the AI's words stay
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET checklist_sha256 = 'sha-rebuilt' WHERE run_id = ?",
            (LATER,),
        )
        conn.commit()
    assert (
        "learned" not in _page(c, LATER)[3]
    )  # a rebuilt checklist: item ids mean other checks
