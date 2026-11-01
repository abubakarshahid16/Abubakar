"""Pins two guards that survived mutation: procedure_text.verdict's quote-on-page check and
clause_review.verify_quote's ellipsis / word / figure rules. Invented text only (rule 3)."""

from __future__ import annotations

from app import clause_review, procedure_text

REQ = {
    "source_text": "The hazop chair shall be independent of the design team members."
}
PAGES = [
    (3, "Roles. The chair is appointed by the Safety Department. A scribe records.")
]


def test_verdict_refuses_quote_not_on_stated_page(monkeypatch):
    # find_passage is faked to return a quote that is NOT on page 3: code must not vouch for it.
    monkeypatch.setattr(
        procedure_text,
        "find_passage",
        lambda text, pages: {
            "page": 3,
            "quote": "The chair is wholly independent of design.",
        },
    )
    row = procedure_text.verdict(REQ, PAGES)
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert row["rationale"].startswith(procedure_text.NOT_FOUND)
    assert not row["rationale"].startswith(procedure_text.FOUND)
    assert "wholly independent" not in row["rationale"]


def test_verdict_accepts_quote_on_page(monkeypatch):
    monkeypatch.setattr(
        procedure_text,
        "find_passage",
        lambda text, pages: {
            "page": 3,
            "quote": "The chair is appointed by the Safety Department.",
        },
    )
    row = procedure_text.verdict(REQ, PAGES)
    assert row["rationale"].startswith(procedure_text.FOUND)


PAGE = "The HAZOP chair is appointed by the Safety Department and has not worked on the design."


def test_verify_quote_refuses_ellipsis():
    assert not clause_review.verify_quote(
        "The HAZOP chair is appointed ... Safety Department", PAGE
    )
    assert not clause_review.verify_quote(
        "The HAZOP chair is appointed… Safety Department", PAGE
    )


def test_verify_quote_accepts_verbatim_five_words():
    assert clause_review.verify_quote("the hazop chair is appointed by", PAGE)


def test_verify_quote_refuses_ellipsis_even_if_substring_would_match():
    page = (
        "The HAZOP chair is appointed by the Safety Department ... and has not worked."
    )
    assert not clause_review.verify_quote(
        "The HAZOP chair is appointed by the Safety Department ...", page
    )


def test_verify_quote_refuses_figures():
    page = "Items 1234 5678 9012 3456 7890 1111 are listed."
    assert not clause_review.verify_quote("1234 5678 9012 3456 7890 1111", page)


def test_verify_quote_refuses_too_short_and_absent():
    assert not clause_review.verify_quote("HAZOP chair is appointed", PAGE)
    assert not clause_review.verify_quote("The chair is selected by the board", PAGE)
