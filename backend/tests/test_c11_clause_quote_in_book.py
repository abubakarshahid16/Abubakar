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
PAGE5 = "A sentence that only the fifth page of the invented rule book holds, word for word."
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
    got = G.locate(
        QUOTE, _book({3: FILL, 7: QUOTE}), [3, 7]
    )  # the rule row's own page is a hint too
    assert (got.page, got.where) == (7, G.WHERE_OTHER)


def test_a_quote_that_runs_over_a_page_break_is_found_on_the_page_it_starts():
    got = G.locate(
        "shall be applied in two layers of equal depth.",
        _book({3: "x shall be applied in two", 4: "layers of equal depth. y"}),
        [3],
    )
    assert (got.found, got.page) == (True, 3)
    assert (
        G.locate(
            "shall be applied in two layers of equal depth.",
            _book({3: "x shall be applied in two", 9: "layers of equal depth. y"}),
            [3],
        ).found
        is False
    )


def test_a_word_split_by_a_hyphen_at_a_line_end_is_joined():
    got = G.locate(
        QUOTE,
        _book({2: "The coating shall be applied in two lay-\ners of equal depth."}),
        [2],
    )
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
    ok, got = G.judge(
        book.get, item, QUOTE, "rule_quote", True
    )  # it stands in the row the reader was handed, not in the book
    assert ok is False and got.found is False
    ok, got = G.judge(
        book.get, item, QUOTE, "clause_span", True
    )  # the clause text cut from the book by code is the book's own
    assert (
        ok is True and got.where == G.WHERE_CUT and got.page is None
    )  # but its pages were NOT searched: no page is claimed
    ok, got = G.judge(
        book.get, {"clause_page": 4}, QUOTE, "clause_span", True
    )  # no book to search at all
    assert (ok, got.page, got.why) == (True, None, G.NOT_RESOLVABLE)


def test_a_short_quote_counts_on_the_stated_page_only():
    short = "two layers"  # 10 characters: searched on the stated page, never elsewhere
    assert (
        G.locate(short, _book({3: "xx two layers xx", 7: "two layers"}), [3]).page == 3
    )
    assert G.locate(short, _book({3: FILL, 7: "two layers"}), [3]).found is False


def test_the_page_of_a_scanned_book_is_marked_so():
    got = G.locate(QUOTE, G.Book({1: FILL, 2: QUOTE}, ocr=[2]), [2])
    assert got.scanned is True and got.to_json()["scanned"] is True
    assert "scanned" not in G.locate(QUOTE, _book({1: QUOTE}), [1]).to_json()


# ---------------------------------------------------------------- the reader of the stored pages


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE pages (document_id TEXT, page_no INT, text TEXT)")
    conn.execute(
        "CREATE TABLE page_ocr (document_id TEXT, page_no INT, text TEXT, error TEXT)"
    )
    return conn


def test_a_scanned_book_is_read_from_its_recognised_text_when_its_page_text_is_empty():
    conn = _conn()
    conn.executemany("INSERT INTO pages VALUES ('b', ?, '')", [(1,), (2,)])
    conn.executemany(
        "INSERT INTO page_ocr VALUES ('b', ?, ?, NULL)", [(1, FILL), (2, QUOTE)]
    )
    conn.execute(
        "INSERT INTO page_ocr VALUES ('b', 3, ?, 'failed')", (QUOTE,)
    )  # a failed page is not text
    book = stds.read_book(conn, "b")
    assert sorted(book.pages) == [1, 2]
    assert G.locate(QUOTE, book, [1]).page == 2
    conn.execute("INSERT INTO pages VALUES ('c', 1, ?)", (QUOTE,))
    assert stds.read_book(conn, "c").pages == {
        1: QUOTE
    }  # the page text stands when it is there


def test_verify_is_the_one_call_book_id_quote_page_hint(w):
    got = stds.verify(s.STD, QUOTE, 1)
    assert (got.found, got.page, got.where) == (True, 1, G.WHERE_STATED)
    assert (
        stds.verify(
            s.STD, "A sentence that no page of the invented book holds at all.", 1
        ).found
        is False
    )


# ---------------------------------------------------------------- a run: the line follows the book


def _set_std_page(text, page=1, extra=None):
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 1",
            (text, s.STD),
        )
        for n, t in (extra or {}).items():
            conn.execute(
                "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,?,?,?,0)",
                (s.STD, n, t, len(t)),
            )


def _stored(run_id, iid):
    return json.loads(lines_of(run_id)[iid]["line_json"])


def test_a_clause_quote_only_in_the_stored_requirement_is_not_verified_and_no_line_is_a_decision(
    w,
):
    _set_std_page(
        FILL
    )  # the rule books hold none of the rule sentences; the requirement row (the cache) still does
    run_id = run_review()
    for iid, row in lines_of(run_id).items():
        line = json.loads(row["line_json"])
        if line.get("clause_quote"):
            assert (
                line["quotes_checked"]["clause"] is False
                and line["clause_book"]["found"] is False
            ), iid
        assert row["verdict_class"] not in (
            "Proven by code",
            "AI verdict, two readers agree",
        ), (iid, row["word"])


def test_a_clause_quote_found_in_the_book_keeps_the_line_and_names_the_page(w):
    run_id = run_review()
    line = _stored(run_id, "R-coat")
    assert line["quotes_checked"]["clause"] is True
    assert line["clause_book"]["found"] is True and line["clause_book"]["page"] == 1


def test_a_quote_on_another_page_of_the_book_is_shown_with_its_true_page(w):
    _set_std_page(FILL, extra={5: f"{FILL}\n{QUOTE}"})
    run_id = run_review()
    line = _stored(run_id, "R-coat")
    assert line["clause_book"] == {
        "found": True,
        "page": 5,
        "where": G.WHERE_OTHER,
        "why": None,
    }
    assert line["quotes_checked"]["clause"] is True
    assert "page 5" in line_cell(line)
    note = rp._clause_note({**line, "clause_page": 1})
    assert note == rp.CLAUSE_CHECK_OTHER_PAGE.format(page=5, stated=1)


def line_cell(line):
    from app.agent_review_crs import clause_quote_cell

    return clause_quote_cell(line)


def test_the_screen_says_the_old_words_only_for_a_line_with_no_record_of_the_book_check():
    assert rp._clause_note({"clause_page": 2}) == rp.CLAUSE_CHECK
    got = rp._clause_note(
        {
            "clause_page": 2,
            "clause_book": {"found": True, "page": 2, "where": G.WHERE_STATED},
        }
    )
    assert got == rp.CLAUSE_CHECK_PAGE.format(page=2)


def test_a_proven_pass_or_fail_needs_a_clause_quote_verified_in_the_book():
    line = {"verdict": "Fail", "decided_by": "decided by code", "ai_verdict": "Fail", "compare": {"decided": True, "verdict": "does_not_meet"},
            "quotes_checked": {"paper": True, "clause": False, "clause_strong": False}}  # fmt: skip
    out = W.demote_unproven(line)
    assert out["verdict"] == "Query" and out["why"] == W.CLAUSE_NOT_IN_BOOK_WHY
    ok = {
        **line,
        "quotes_checked": {"paper": True, "clause": True, "clause_strong": True},
    }
    assert W.demote_unproven(ok)["verdict"] == "Fail"
    assert (
        W.demote_unproven({**line, "quotes_checked": None})["verdict"] == "Fail"
    )  # a line with no record of the check is not touched here


def test_the_second_readers_clause_quote_is_verified_in_the_book_too():
    from app.agent_review_request import ClauseCache
    from app.agent_review_two_reader_absence import AbsenceMixin

    cache = ClauseCache(
        {
            "Q-1": {
                "text": QUOTE,
                "page": 1,
                "source": "rule_quote",
                "standard_document_id": "d",
                "clause": "4.4",
            }
        }
    )
    item = {
        "item_id": "R-1",
        "standard_document_id": "d",
        "clause_page": 1,
        "rule_quote_ref": "Q-1",
        "clause_quote_ref": "Q-1",
    }
    answer = {"clause_quote": QUOTE, "paper_quote": None, "page": None}
    for text, want in ((FILL, False), (QUOTE, True)):
        me = SimpleNamespace(
            clauses=cache, books=SimpleNamespace(book=lambda _d, t=text: _book({1: t}))
        )
        _paper_ok, clause_ok, strong = AbsenceMixin._checked(me, item, answer, {1: "x"})
        assert clause_ok is want
        assert strong is want or not want


# ---------------------------------------------------------------- earlier runs are judged again, once, audited


def test_the_upgrade_writes_only_c11s_own_falls_never_lets_a_class_rise_and_counts_truly(
    w,
):
    from app import agent_review_schema as schema

    with db.connect() as conn:
        schema.ensure_schema(conn)
        base = {
            "item_id": "R-1", "source": "rule", "standard": "INV-STD-100", "standard_document_id": s.STD, "clause": "4.4",
            "clause_page": 1, "verdict": "Fail", "decided_by": "decided by code", "ai_verdict": "Fail", "reason_code": "met",
            "clause_quote": QUOTE, "clause_quote_from": "requirement", "paper_quote": "x" * 12, "model": "m1",
            "quotes_checked": {"paper": True, "clause": True, "both": True, "clause_strong": True},
            "compare": {"decided": True, "verdict": "does_not_meet"}, "rule_tier": "ai_approved",
        }  # fmt: skip
        kept = {**base, "item_id": "R-1"}  # the quote IS in the book
        gone = {
            **base,
            "item_id": "R-2",
            "clause_quote": "A sentence that the invented rule book does not hold on any page of it.",
        }
        stale = {
            **base,
            "item_id": "R-3",
            "verdict": "Pass",
            "ai_verdict": "Pass",
            "decided_by": "decided by code",
            "compare": {"decided": True, "verdict": "meets"},
        }  # a stored class that disagrees with its json; the quote is in the book
        rise = {
            **gone,
            "item_id": "R-4",
            "verdict": "Query",
            "ai_verdict": "Fail",
            "decided_by": "engineer",
            "compare": None,
        }  # stored lower than it would derive
        paged = {
            **base,
            "item_id": "R-5",
            "clause_page": 1,
            "clause_quote": PAGE5,
        }  # the quote is in the book, on page 5, not on the cited page 1
        stored = [(paged, "Proven by code", "Fail"), (kept, "Proven by code", "Fail"), (gone, "Proven by code", "Fail"), (stale, "AI opinion, engineer to confirm", "AI thinks: met"),
                  (rise, "Not reviewed", "Not reviewed")]  # fmt: skip
        for ln, cls, word in stored:
            conn.execute(
                f"INSERT INTO {schema.LINE_TABLE} (run_id, item_id, verdict_class, word, reason, line_json, decided_at) VALUES ('run-1', ?, ?, ?, '', ?, '2026-11-15T00:00:00Z')",
                (ln["item_id"], cls, word, json.dumps(ln)),
            )
        conn.execute(
            "DELETE FROM audit_events WHERE action = ?", (schema.REJUDGE_ACTION,)
        )  # the empty table's own pass left a marker: this DB is an earlier one
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?, 5, ?, 80, 0)",
            (s.STD, FILL + "\n" + PAGE5),
        )
        conn.commit()
        before = {
            r["item_id"]: tuple(r)
            for r in conn.execute(
                f"SELECT item_id, verdict_class, word, reason, line_json FROM {schema.LINE_TABLE}"
            )
        }
        schema.create_tables(conn)  # the audited upgrade runs it
        after = {
            r["item_id"]: tuple(r)
            for r in conn.execute(
                f"SELECT item_id, verdict_class, word, reason, line_json FROM {schema.LINE_TABLE}"
            )
        }
        assert (
            after["R-1"] == before["R-1"] and after["R-3"] == before["R-3"]
        )  # a verified clause quote: byte for byte
        assert after["R-4"] == before["R-4"]  # a class never rises
        old, new = json.loads(before["R-5"][4]), json.loads(after["R-5"][4])
        assert (
            after["R-5"][:4] == before["R-5"][:4]
        )  # class, word and reason: byte for byte
        assert {k for k in set(old) | set(new) if old.get(k) != new.get(k)} == {
            "clause_book",
            "clause_page_before_c11",
        }
        assert (
            new["verdict"] == old["verdict"]
            and new["decided_by"] == old["decided_by"]
            and new["clause_page"] == 1
        )
        assert (
            new["clause_book"]
            == {"found": True, "page": 5, "where": G.WHERE_OTHER, "why": None}
            and new["clause_page_before_c11"] == 1
        )
        fell = json.loads(after["R-2"][4])
        assert (
            after["R-2"][1] != "Proven by code"
            and fell["verdict"] == "Query"
            and fell["clause_book"]["found"] is False
        )
        assert (
            fell["quotes_checked"]["clause"] is False
            and fell["clause_checked_before_c11"] is True
        )
        assert (
            fell["class_before_c11"],
            fell["word_before_c11"],
            fell["verdict_before_c11"],
        ) == ("Proven by code", "Fail", "Fail")
        assert (
            fell["decided_by_before_c11"] == "decided by code"
            and fell["clause_quote"] == gone["clause_quote"]
        )
        audit = conn.execute(
            "SELECT detail FROM audit_events WHERE action = ?", (schema.REJUDGE_ACTION,)
        ).fetchall()
        assert (
            len(audit) == 1
            and "lines changed: 1; true page recorded: 1" in audit[0][0]
            and "left as stored (a class would rise): 1" in audit[0][0]
        )
        assert (
            "Proven by code / Fail ->" in audit[0][0]
            and "class changes: none" not in audit[0][0]
        )
        schema.create_tables(conn)  # once: the audit row is the marker
        assert {
            r["item_id"]: tuple(r)
            for r in conn.execute(
                f"SELECT item_id, verdict_class, word, reason, line_json FROM {schema.LINE_TABLE}"
            )
        } == after


def test_the_screen_and_the_crs_say_what_was_searched_and_where_it_was_found():
    from app.agent_review_crs import clause_quote_cell

    book = {"found": True, "page": 5, "where": G.WHERE_OTHER, "why": None}
    line = {
        "clause_quote": QUOTE,
        "standard": "INV-STD",
        "clause": "4.4",
        "clause_page": 1,
        "clause_book": book,
    }
    assert "page 5 (the rule cites page 1)" in clause_quote_cell(line)
    same = {**line, "clause_page": 5}
    assert "page 5" in clause_quote_cell(
        same
    ) and "the rule cites" not in clause_quote_cell(same)
    cut = {
        **line,
        "clause_book": {
            "found": True,
            "page": None,
            "where": G.WHERE_CUT,
            "why": G.NOT_RESOLVABLE,
        },
    }
    assert (
        "page 1" in clause_quote_cell(cut)
        and rp._clause_note(cut) == rp.CLAUSE_CHECK_CUT
    )  # never "found ... on page"
    assert rp._clause_note({**line, "clause_book": {**book, "scanned": True}}).endswith(
        rp.CLAUSE_SCANNED
    )
