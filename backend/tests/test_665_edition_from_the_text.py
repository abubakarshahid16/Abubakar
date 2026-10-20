"""#665: Compare reads a standard's edition from the document's own first
pages, with the file name only as the fallback, says where it came from, and
never merges a title page and a file name that disagree.

Invented names and text only.
"""
from __future__ import annotations

import pytest

from app import chat_comparison, standard_ids

QUESTION = "Compare ASME B16.5 and ASME B16.47 on the flange size range"


# --------------------------------------------------- reading the stated edition

@pytest.mark.parametrize("text, year", [
    ("ASME B16.5-2020\nPipe Flanges and Flanged Fittings\n2020 Edition", "2020"),
    ("Pipe Flanges\nEdition 2017\nApproved by the committee", "2017"),
    ("Edition: 2013", "2013"),
    ("This 2020 Edition supersedes the 2017 Edition.", "2020"),
    ("Revision of ASME B16.5-2017 edition. 2020 Edition", "2020"),
])
def test_the_edition_the_text_states(text, year):
    assert standard_ids.edition_in_text(text) == year


@pytest.mark.parametrize("text", [
    "Issued 12 March 2020. Table 2019 lists sizes.",     # a year with no "edition" beside it
    "Supersedes the 2017 Edition.",                       # only the replaced edition
    "",
])
def test_no_stated_edition_is_none_never_a_guess(text):
    assert standard_ids.edition_in_text(text) is None


# ---------------------------------------------------- the issue's three cases

def _sides(documents, front):
    sides, missing = chat_comparison.resolve_sides(QUESTION, documents, front.get)
    return {name: sorted(ids) for name, ids in sides}, missing


def test_the_title_page_names_the_edition_the_file_name_does_not():
    """Two copies of B16.5, editions only on their title pages: two sides,
    each saying the edition came from the title page."""
    documents = {"a": "ASME B16.5.pdf", "b": "ASME B16.5 copy.pdf", "c": "ASME B16.47.pdf"}
    front = {"a": "Pipe Flanges\n2020 Edition", "b": "Pipe Flanges\n2013 Edition"}
    sides, missing = _sides(documents, front)
    assert missing == []
    assert sides["ASME B16.5 (2013, from the title page)"] == ["b"]
    assert sides["ASME B16.5 (2020, from the title page)"] == ["a"]


def test_a_title_page_and_a_file_name_that_disagree_are_shown_disagreeing():
    documents = {"a": "ASME B16.5-2013.pdf", "c": "ASME B16.47.pdf"}
    front = {"a": "Pipe Flanges\n2020 Edition"}
    sides, _missing = _sides(documents, front)
    assert "ASME B16.5 (2020, from the title page; the file name says 2013)" in sides


def test_no_year_anywhere_is_edition_not_stated():
    """Beside two editions, a copy with no year in its words or its name is
    its own side, "edition not stated"; the file-name year says so too."""
    documents = {"a": "ASME B16.5.pdf", "b": "ASME B16.5-2020.pdf",
                 "d": "ASME B16.5 copy.pdf", "c": "ASME B16.47.pdf"}
    sides, _missing = _sides(documents, {"d": "Pipe Flanges\n2013 Edition"})
    assert sides["ASME B16.5 (edition not stated)"] == ["a"]
    assert sides["ASME B16.5 (2020, from the file name)"] == ["b"]
    assert sides["ASME B16.5 (2013, from the title page)"] == ["d"]


def test_one_edition_and_no_disagreement_keeps_the_plain_name():
    documents = {"a": "ASME B16.5-2020.pdf", "c": "ASME B16.47.pdf"}
    sides, _missing = _sides(documents, {"a": "2020 Edition"})
    assert "ASME B16.5" in sides


def test_front_text_is_empty_for_a_document_the_caller_may_not_read():
    assert chat_comparison.front_text("doc_secret", frozenset({"doc_other"})) == ""
