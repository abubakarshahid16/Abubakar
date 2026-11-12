"""The book-by-book table of the Rules used page: which held rule books were candidates and which were not.

Invented data only. MUTATION PROOF (by hand): drop the `may_read` filter and the hidden-book test fails; show the
selection's free-text reason instead of the fixed words and the no-reason-text test fails; count a considered-only
book as in_review and the in/out test fails.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import agent_review_book_table as bt


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT);
        CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT);
        CREATE TABLE review_applicable_standards (
            id TEXT PRIMARY KEY, review_run_id TEXT, standard_document_id TEXT, selection_reason TEXT,
            selection_method TEXT, included INTEGER);
        CREATE TABLE agent_review_rule (run_id TEXT, rule_key TEXT, asked INTEGER, left_out_reason TEXT,
            standard_document_id TEXT);
        """
    )
    c.executemany(
        "INSERT INTO documents VALUES (?, ?)",
        [
            ("b1", "INV-A.pdf"),
            ("b2", "INV-B.pdf"),
            ("b3", "INV-C.pdf"),
            ("b4", "INV-SECRET.pdf"),
        ],
    )
    c.executemany(
        "INSERT INTO standard_requirements VALUES (?, ?)",
        [
            (f"r{i}", d)
            for i, d in enumerate(["b1"] * 5 + ["b2"] * 2 + ["b3"] * 7 + ["b4"] * 3)
        ],
    )
    c.executemany(
        "INSERT INTO review_applicable_standards VALUES (?, 'run', ?, ?, ?, ?)",
        [
            ("s1", "b1", "PAPER QUOTE THAT MUST NOT SHOW", "referenced", 1),
            ("s2", "b2", "x", "governing_standard", 1),
            ("s3", "b3", "x", "semantic", 0),
            ("s4", "b4", "x", "scope", 1),
        ],
    )
    c.executemany(
        "INSERT INTO agent_review_rule VALUES ('run', ?, ?, ?, ?)",
        [
            ("k1", 1, None, "b1"),
            ("k2", 1, None, "b1"),
            ("k3", 0, "needs a human", "b1"),
            ("k4", 0, "needs another paper", "b2"),
            ("k5", 0, "needs another paper", "b2"),
            ("k6", 1, None, "b4"),
        ],
    )
    return c


def test_in_and_out_books_with_counts_and_fixed_method_words(conn):
    got = bt.build(conn, "run", lambda d: d != "b4")
    rows = {r["rule_book"]: r for r in got["books"]}
    assert rows["INV-A"] == {
        "rule_book": "INV-A",
        "in_review": True,
        "method": "named in the paper",
        "stored_rules": 5,
        "asked": 2,
        "left_out": {"needs a human": 1},
    }
    assert (
        rows["INV-B"]["left_out"] == {"needs another paper": 2}
        and rows["INV-B"]["asked"] == 0
    )
    assert rows["INV-C"]["in_review"] is False and rows["INV-C"]["stored_rules"] == 7
    assert rows["INV-C"]["method"].startswith("similar text only")
    assert [r["in_review"] for r in got["books"]] == [
        True,
        True,
        False,
    ]  # candidates first
    assert got["note"] is None


def test_a_book_the_viewer_may_not_read_is_counted_never_named(conn):
    got = bt.build(conn, "run", lambda d: d != "b4")
    assert got["hidden_books"] == 1
    assert "INV-SECRET" not in repr(got) and "b4" not in repr(got)
    assert bt.build(conn, "run", lambda _d: True)["hidden_books"] == 0


def test_the_selections_free_text_reason_is_never_shown(conn):
    assert "PAPER QUOTE" not in repr(bt.build(conn, "run", lambda _d: True))


def test_without_a_stored_selection_the_books_come_from_the_rules_and_a_note_says_so(
    conn,
):
    got = bt.build(conn, "other-run", lambda _d: True)
    assert got["books"] == [] and got["note"] is None
    conn.execute("INSERT INTO agent_review_rule VALUES ('r2', 'k', 1, NULL, 'b2')")
    got = bt.build(conn, "r2", lambda _d: True)
    assert (
        got["books"][0]["method"] == bt.PER_RULE
        and got["books"][0]["in_review"] is True
    )
    assert got["note"] == bt.NO_SELECTION_NOTE


def test_a_method_not_in_the_list_reads_not_recorded(conn):
    conn.execute(
        "UPDATE review_applicable_standards SET selection_method = 'brand_new' WHERE id = 's1'"
    )
    rows = {r["rule_book"]: r for r in bt.build(conn, "run", lambda _d: True)["books"]}
    assert rows["INV-A"]["method"] == bt.NOT_RECORDED


def test_no_table_for_the_selection_is_an_empty_table_not_an_error(conn):
    conn.execute("DROP TABLE review_applicable_standards")
    assert bt.build(conn, "run", lambda _d: True)["books"][0]["method"] == bt.PER_RULE
