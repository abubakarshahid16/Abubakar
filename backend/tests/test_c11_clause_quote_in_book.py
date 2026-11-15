"""c11 (15 Nov 2026, audit V1 defect 3): a clause quote is "verified" only when code finds it in the rule book's OWN stored pages.
Invented books and rules; no network. Taking it from the stored requirement row is not a check."""

# ruff: noqa: F811
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from app import agent_review_absence as A  # noqa: F401
from app import agent_review_pass_guards as G
from app import agent_review_standards as stds
from app import agent_review_wording as W
from app import db
from app import review_points as rp
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of

QUOTE = "The coating shall be applied in two layers of equal depth."
FILL = "Invented filler sentence about the nameplate and the painting of the casing."


def _book(pages):
    return G.Book(pages)


# ---------------------------------------------------------------- the pure check


def test_a_quote_is_found_on_the_stated_page_and_the_answer_says_which():
    got = G.locate(QUOTE, _book({3: f"{FILL}\n{QUOTE}\n{FILL}", 4: FILL}), [3])
    assert (got.found, got.page, got.where) == (True, 3, G.WHERE_STATED)


def test_a_quote_on_another_page_comes_back_with_its_true_page():
    got = G.locate(QUOTE, _book({3: FILL, 7: QUOTE}), [3])
    assert (got.found, got.page, got.where) == (True, 7, G.WHERE_OTHER)
    got = G.locate(QUOTE, _book({3: FILL, 7: QUOTE}), [3, 7])  # the rule row's own page is a hint too
    assert (got.page, got.where) == (7, G.WHERE_OTHER)


def test_a_quote_that_runs_over_a_page_break_is_found_on_the_page_it_starts():
    got = G.locate("shall be applied in two layers of equal depth.", _book({3: "x shall be applied in two", 4: "layers of equal depth. y"}), [3])
    assert (got.found, got.page) == (True, 3)
    assert G.locate("shall be applied in two layers of equal depth.", _book({3: "x shall be applied in two", 9: "layers of equal depth. y"}), [3]).found is False


def test_a_word_split_by_a_hyphen_at_a_line_end_is_joined():
    got = G.locate(QUOTE, _book({2: "The coating shall be applied in two lay-\ners of equal depth."}), [2])
    assert (got.found, got.page) == (True, 2)


def test_a_quote_not_in_the_book_is_not_found_and_says_why():
    got = G.locate(QUOTE, _book({1: FILL, 2: FILL}), [1])
    assert (got.found, got.why) == (False, G.NOT_FOUND)
    assert G.locate(QUOTE, _book({}), [1]).why == G.NOT_HELD
    assert G.locate("two", _book({1: "two"}), [1]).why == G.TOO_SHORT
    assert G.locate("", _book({1: FILL}), [1]).why == G.NO_QUOTE


def test_the_stored_requirement_row_is_never_a_check():
    item = {"standard_document_id": "d", "clause_page": 1}
    book = {"d": _book({1: FILL})}
    ok, got = G.judge(book.get, item, QUOTE, "rule_quote", True)  # it stands in the row the reader was handed, not in the book
    assert ok is False and got.found is False
    ok, got = G.judge(book.get, item, QUOTE, "clause_span", True)  # the clause text cut from the book by code is the book's own
    assert ok is True and got.page == 1


# ---------------------------------------------------------------- the reader of the stored pages


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE pages (document_id TEXT, page_no INT, text TEXT)")
    conn.execute("CREATE TABLE page_ocr (document_id TEXT, page_no INT, text TEXT, error TEXT)")
    return conn


def test_a_scanned_book_is_read_from_its_recognised_text_when_its_page_text_is_empty():
    conn = _conn()
    conn.executemany("INSERT INTO pages VALUES ('b', ?, '')", [(1,), (2,)])
    conn.executemany("INSERT INTO page_ocr VALUES ('b', ?, ?, NULL)", [(1, FILL), (2, QUOTE)])
    conn.execute("INSERT INTO page_ocr VALUES ('b', 3, ?, 'failed')", (QUOTE,))  # a failed page is not text
    book = stds.read_book(conn, "b")
    assert sorted(book.pages) == [1, 2]
    assert G.locate(QUOTE, book, [1]).page == 2
    conn.execute("INSERT INTO pages VALUES ('c', 1, ?)", (QUOTE,))
    assert stds.read_book(conn, "c").pages == {1: QUOTE}  # the page text stands when it is there


def test_verify_is_the_one_call_book_id_quote_page_hint(w):
    got = stds.verify(s.STD, QUOTE, 1)
    assert (got.found, got.page, got.where) == (True, 1, G.WHERE_STATED)
    assert stds.verify(s.STD, "A sentence that no page of the invented book holds at all.", 1).found is False


# ---------------------------------------------------------------- a run: the line follows the book


def _set_std_page(text, page=1, extra=None):
    with db.connect() as conn:
        conn.execute("UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 1", (text, s.STD))
        for n, t in (extra or {}).items():
            conn.execute(
                "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)", (s.STD, n, t, len(t))
            )


def _stored(run_id, iid):
    return json.loads(lines_of(run_id)[iid]["line_json"])


def test_a_clause_quote_only_in_the_stored_requirement_is_not_verified_and_no_line_is_a_decision(w):
    _set_std_page(FILL)  # the rule books hold none of the rule sentences; the requirement row (the cache) still does
    run_id = run_review()
    for iid, row in lines_of(run_id).items():
        line = json.loads(row["line_json"])
        if line.get("clause_quote"):
            assert line["quotes_checked"]["clause"] is False and line["clause_book"]["found"] is False, iid
        assert row["verdict_class"] not in ("Proven by code", "AI verdict, two readers agree"), (iid, row["word"])


def test_a_clause_quote_found_in_the_book_keeps_the_line_and_names_the_page(w):
    run_id = run_review()
    line = _stored(run_id, "R-coat")
    assert line["quotes_checked"]["clause"] is True
    assert line["clause_book"]["found"] is True and line["clause_book"]["page"] == 1


def test_a_quote_on_another_page_of_the_book_is_shown_with_its_true_page(w):
    _set_std_page(FILL, extra={5: f"{FILL}\n{QUOTE}"})
    run_id = run_review()
    line = _stored(run_id, "R-coat")
    assert line["clause_book"] == {"found": True, "page": 5, "where": G.WHERE_OTHER, "why": None}
    assert line["quotes_checked"]["clause"] is True
    assert "page 5" in line_cell(line)
    note = rp._clause_note({**line, "clause_page": 1})
    assert note == rp.CLAUSE_CHECK_OTHER_PAGE.format(page=5, stated=1)


def line_cell(line):
    from app.agent_review_crs import clause_quote_cell

    return clause_quote_cell(line)


def test_the_screen_says_the_old_words_only_for_a_line_with_no_record_of_the_book_check():
    assert rp._clause_note({"clause_page": 2}) == rp.CLAUSE_CHECK
    got = rp._clause_note({"clause_page": 2, "clause_book": {"found": True, "page": 2, "where": G.WHERE_STATED}})
    assert got == rp.CLAUSE_CHECK_PAGE.format(page=2)


def test_a_proven_pass_or_fail_needs_a_clause_quote_verified_in_the_book():
    line = {"verdict": "Fail", "decided_by": "decided by code", "ai_verdict": "Fail", "compare": {"decided": True, "verdict": "does_not_meet"},
            "quotes_checked": {"paper": True, "clause": False, "clause_strong": False}}  # fmt: skip
    out = W.demote_unproven(line)
    assert out["verdict"] == "Query" and out["why"] == W.CLAUSE_NOT_IN_BOOK_WHY
    ok = {**line, "quotes_checked": {"paper": True, "clause": True, "clause_strong": True}}
    assert W.demote_unproven(ok)["verdict"] == "Fail"
    assert W.demote_unproven({**line, "quotes_checked": None})["verdict"] == "Fail"  # a line with no record of the check is not touched here


def test_the_second_readers_clause_quote_is_verified_in_the_book_too():
    from app.agent_review_request import ClauseCache
    from app.agent_review_two_reader_absence import AbsenceMixin

    cache = ClauseCache({"Q-1": {"text": QUOTE, "page": 1, "source": "rule_quote", "standard_document_id": "d", "clause": "4.4"}})
    item = {"item_id": "R-1", "standard_document_id": "d", "clause_page": 1, "rule_quote_ref": "Q-1", "clause_quote_ref": "Q-1"}
    answer = {"clause_quote": QUOTE, "paper_quote": None, "page": None}
    for text, want in ((FILL, False), (QUOTE, True)):
        me = SimpleNamespace(clauses=cache, books=SimpleNamespace(book=lambda _d, t=text: _book({1: t})))
        _paper_ok, clause_ok, strong = AbsenceMixin._checked(me, item, answer, {1: "x"})
        assert clause_ok is want
        assert strong is want or not want


# ---------------------------------------------------------------- earlier runs are judged again, once, audited


def test_an_earlier_line_whose_clause_quote_the_book_does_not_hold_is_judged_again_once_with_the_old_values_kept(w):
    from app import agent_review_schema as schema

    with db.connect() as conn:
        schema.ensure_schema(conn)
        base = {
            "item_id": "R-1", "source": "rule", "standard_document_id": s.STD, "standard": "INV-STD-100", "clause": "4.4", "clause_page": 1, "verdict": "Fail",
            "decided_by": "decided by code", "ai_verdict": "Fail", "reason_code": "met", "clause_quote": QUOTE, "clause_quote_from": "requirement",
            "quotes_checked": {"paper": True, "clause": True, "both": True, "clause_strong": True}, "paper_quote": "x" * 12,
            "compare": {"decided": True, "verdict": "does_not_meet"}, "model": "m1", "rule_tier": "ai_approved",
        }  # fmt: skip
        gone = {**base, "item_id": "R-2", "clause_quote": "A sentence that the invented rule book does not hold on any page of it."}
        for ln in (base, gone):
            conn.execute(
                f"INSERT INTO {schema.LINE_TABLE} (run_id, item_id, verdict_class, word, reason, line_json, decided_at) VALUES ('run-1', ?, ?, ?, '', ?, '2026-11-15T00:00:00Z')",
                (ln["item_id"], "Proven by code", "Fail", json.dumps(ln)),
            )
        conn.commit()
        schema.create_tables(conn)  # the audited upgrade runs it
        got = {r["item_id"]: r for r in conn.execute(f"SELECT * FROM {schema.LINE_TABLE} WHERE run_id = 'run-1'")}
        kept, fell = json.loads(got["R-1"]["line_json"]), json.loads(got["R-2"]["line_json"])
        assert kept["clause_book"]["found"] is True and (got["R-1"]["verdict_class"], got["R-1"]["word"]) == ("Proven by code", "Fail")
        assert fell["clause_book"]["found"] is False and fell["quotes_checked"]["clause"] is False
        assert got["R-2"]["verdict_class"] != "Proven by code" and fell["verdict"] == "Query"
        assert fell["clause_checked_before_c11"] is True and fell["class_before_c11"] == "Proven by code"
        assert fell["word_before_c11"] == "Fail" and fell["verdict_before_c11"] == "Fail" and fell["clause_quote"] == gone["clause_quote"]  # the old values are kept
        audit = conn.execute("SELECT detail FROM audit_events WHERE action = ?", (schema.REJUDGE_ACTION,)).fetchall()
        assert len(audit) == 1 and "not in the rule book: 1" in audit[0][0]
        snap = conn.execute(f"SELECT line_json FROM {schema.LINE_TABLE} ORDER BY item_id").fetchall()
        schema._rejudge_old_clause_quotes(conn)  # idempotent
        assert conn.execute(f"SELECT line_json FROM {schema.LINE_TABLE} ORDER BY item_id").fetchall() == snap
