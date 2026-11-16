"""Order 14, 16 Nov 2026 night: an AI "not met" of the rule check is firm only with a clause AND a rule-book quote that code found in
the stored book (honesty rule 4, gates G1 and G5). Without them it is a question for the engineer, and its words are never shown as
the book's. Invented data."""

from __future__ import annotations

from app import review_points as rp

CTX = {"run_id": "r", "paper_document_id": "p", "readable": frozenset({"p", "doc-book"}), "_library": []}  # fmt: skip
ROW = {"row_kind": "ai_engineering_check", "finding_id": "f1", "page_section": "p.3 - Back pressure", "comment": "Value looks low.",
       "standard_reference": "BOOK-9.pdf", "priority": "3"}  # fmt: skip
VERIFIED = {"submittal": {"verified": True}, "standard": {"verified": True}}


def _finding(clause: str = "") -> dict:
    return {"standard_document_id": "doc-book", "standard_clause": clause, "requirement_source_text": "The limit shall be 10 %.",
            "requirement": "The limit shall be 10 %.", "contractor_evidence_text": "12 %"}  # fmt: skip


def test_an_ai_not_met_with_no_clause_is_a_question_with_no_book_words():
    p = rp.rule_point(dict(ROW), CTX, _finding(""), VERIFIED, proof=(True, True))
    assert p["rank"] == 4 and p["tile"] == "questions" and p["firm"] is None
    assert p["rule_text"] is None and p["clause_quote"] is None


def test_an_ai_not_met_whose_book_quote_was_not_found_is_a_question():
    unverified = {"submittal": {"verified": True}, "standard": {"verified": False}}
    p = rp.rule_point(dict(ROW), CTX, _finding("5.3.4"), unverified, proof=(True, True))
    assert p["rank"] == 4 and p["rule_text"] is None


def test_an_ai_not_met_with_a_clause_and_a_found_quote_stays_not_met_one_reader():
    p = rp.rule_point(dict(ROW), CTX, _finding("5.3.4"), VERIFIED, proof=(True, True))
    assert p["rank"] == 3 and p["firm"] == "one reader" and p["clause_quote"]


def test_a_clause_review_not_met_without_a_found_quote_is_a_question_but_keeps_its_stored_book_text():
    row = {**ROW, "row_kind": "clause_review"}
    unverified = {"submittal": {"verified": True}, "standard": {"verified": False}}
    p = rp.rule_point(row, CTX, _finding("5.3.4"), unverified, proof=(True, True))
    assert p["rank"] == 4 and p["rule_text"] == "The limit shall be 10 %."  # the library's stored text, shown labelled, not hidden
