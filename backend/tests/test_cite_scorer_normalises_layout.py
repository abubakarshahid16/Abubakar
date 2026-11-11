# -*- coding: utf-8 -*-
"""The review scorer's citation check reads a quote as the PDF's text layer may
have written it: a ligature glyph and a word broken by a line-break hyphen are
layout, not wording. A real mismatch still fails. Invented sentences only."""
from __future__ import annotations

import pytest

from tools import review_score as rs

FI = "ﬁ"           # the single "fi" ligature glyph
FL = "ﬂ"           # the single "fl" ligature glyph


def _f(text, clause=None):
    return {"requirement_text": text, "clause": clause}


def test_a_ligature_in_the_page_does_not_break_the_citation():
    page = f"The {FI}re-water pump shall have a {FL}ange rating of Class 300."
    assert rs.citation_valid(_f("The fire-water pump shall have a flange rating of Class 300."), page) is True


def test_a_word_split_by_a_line_break_hyphen_does_not_break_the_citation():
    page = "The pump shall be hydrostatically test-\ned at 1.5 times the design pressure."
    assert rs.citation_valid(_f("The pump shall be hydrostatically tested at 1.5 times the design pressure."), page) is True


def test_a_real_hyphenated_word_still_matches():
    page = "A high-\nspeed coupling shall be fitted."
    assert rs.citation_valid(_f("A high-speed coupling shall be fitted."), page) is True
    assert rs.citation_valid(_f("A highspeed coupling shall be fitted."), page) is True


@pytest.mark.parametrize("quote", [
    "The pump shall be hydrostatically tested at 2.0 times the design pressure.",     # another number
    "The pump shall not be tested.",                                                    # other words
])
def test_a_different_sentence_still_fails(quote):
    page = "The pump shall be hydrostatically test-\ned at 1.5 times the design pressure."
    assert rs.citation_valid(_f(quote), page) is False


def test_the_clause_is_still_required_and_a_missing_page_is_not_checked():
    page = "4.2 The pump shall be hydrostatically tested."
    assert rs.citation_valid(_f("The pump shall be hydrostatically tested.", "4.2"), page) is True
    assert rs.citation_valid(_f("The pump shall be hydrostatically tested.", "9.9"), page) is False
    assert rs.citation_valid(_f("anything"), None) is None
