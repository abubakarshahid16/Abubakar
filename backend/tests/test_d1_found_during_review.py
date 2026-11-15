"""The points listing says how many rule books the paper's reviews found only while they ran and did not send (D1; R50e-3):
the union over the rule check and the AI review, each book once, through `assemble`."""

# ruff: noqa: F811
from __future__ import annotations

from app import agent_review_rules, db, review_shown
from tests.test_b1_review_points import ai_run, on, points_of, world_with_both  # noqa: F401 - fixture
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


def _book(conn, doc_id):
    conn.execute(
        "INSERT OR IGNORE INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
        " VALUES (?,?,?,1,?,'ready',1,'t')",
        (doc_id, f"{doc_id}.pdf", doc_id * 3, f"{doc_id}.pdf"),
    )


def test_the_listing_counts_the_union_of_the_books_both_runs_held_each_once(temp_db):
    doc, rc, ai, client = world_with_both()
    with db.connect() as conn, conn:
        for b in ("bookA", "bookB", "bookC"):
            _book(conn, b)
        # the rule check applied A and C; the list shown before the start named neither
        for n, b in enumerate(("bookA", "bookC")):
            conn.execute(
                "INSERT INTO review_applicable_standards (id, review_run_id, standard_document_id, selection_reason, selection_method,"
                " included, created_at) VALUES (?, ?, ?, 'x', 'scope', 1, 't')",
                (f"s{n}", rc, b),
            )
        review_shown.record_in(conn, rc, [doc, "doc_std"], "t")
        # the AI review dropped B and C (C again: counted once)
        review_shown.record_in(conn, ai, [doc, "doc_std"], "t")
        for key, b in (("k1", "bookB"), ("k2", "bookC")):
            conn.execute(
                "INSERT INTO agent_review_rule (run_id, rule_key, asked, left_out_reason, rule_book, standard_document_id)"
                " VALUES (?, ?, 0, ?, 'X', ?)",
                (ai, key, agent_review_rules.REASON_WORDS[agent_review_rules.NOT_ON_LIST], b),
            )
    assert points_of(client, doc)["found_during_review"] == 3  # A, B, C: C once, not the larger of 2 and 2


def test_the_listing_says_zero_when_no_book_was_held(temp_db):
    doc, rc, ai, client = world_with_both()
    assert points_of(client, doc)["found_during_review"] == 0
