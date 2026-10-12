"""No heading line is kept nowhere.

A heading's words live in its chunks' `section`, not their text, so a heading
with nothing under it - a chapter title followed straight by its first
subclause - produced no chunk at all. Measured on the owner's corpus
(2026-09-29, counts only): ~200 heading lines in 150 of 282 documents were in
no chunk and no exclusion. Now such a heading is carried into the next
block's text; a contents page keeps its lines as text; a heading with a body
is unchanged.
"""
from __future__ import annotations

from app import chunker as C


def _chunks(*pages: list[str]):
    pp = [(i + 1, "\n".join(p)) for i, p in enumerate(pages)]
    kinds = {p: C.classify_page(t, p, len(pp)) for p, t in pp}
    running = C.detect_running_lines(pp)
    blocks, _ = C.segment_document(pp, running, kinds)
    return C.build_chunks(blocks, C.document_vocabulary(pp))


CHAPTER = [
    "8", "Thermally sprayed metallic coatings",
    "8.1", "General",
    "Relevant requirements provided in this standard are applicable for",
    "thermally sprayed metallic coatings as described in the clauses below.",
    "8.2", "Coating materials",
    "The materials for metal spraying shall be in accordance with the following",
    "list and every batch shall be marked with its composition and number.",
]


def test_a_heading_with_nothing_under_it_reaches_a_chunk():
    chunks = _chunks(CHAPTER)
    text = " ".join(c.text for c in chunks)
    assert "Thermally sprayed metallic coatings" in text
    carrier = next(c for c in chunks if "Thermally sprayed metallic coatings" in c.text)
    # carried into the first subclause's text, and that chunk keeps ITS section
    assert carrier.section == "8.1 General"


def test_no_title_only_passage_is_made():
    """A title alone answers nothing; measured, one took a retrieval slot."""
    for c in _chunks(CHAPTER):
        assert c.text.strip() != "8 Thermally sprayed metallic coatings"


def test_a_run_of_bodiless_headings_is_all_carried():
    page = ["12", "Special functions", "12.1", "Series solutions",
            "12.2", "Bessel functions",
            "12.2.1", "Definition",
            "The functions defined here are solutions of the equation given in the",
            "previous clause and are tabulated in the annex for the usual orders."]
    text = " ".join(c.text for c in _chunks(page))
    for title in ("Special functions", "Series solutions", "Bessel functions"):
        assert title in text, title


def test_a_heading_at_the_very_end_is_kept_as_its_own_block():
    page = CHAPTER + ["9", "Painting"]
    chunks = _chunks(page)
    last = next(c for c in chunks if "Painting" in c.text)
    assert (last.page_start, last.section) == (1, "9 Painting")


def test_a_heading_with_a_body_is_not_duplicated_into_text():
    """Unchanged behaviour: the section field carries it, as before."""
    chunks = _chunks(CHAPTER)
    coating = [c for c in chunks if c.section == "8.2 Coating materials"]
    assert coating and all("Coating materials" not in c.text for c in coating)


def test_every_chunk_is_under_its_own_chapter_not_the_previous_one():
    page2 = ["9", "Painting", "9.1", "Surface preparation",
             "All surfaces shall be blast cleaned before any coat is applied and",
             "the profile shall be measured and recorded for every surface area."]
    chunks = _chunks(CHAPTER, page2)
    painting = next(c for c in chunks if "Painting" in c.text)
    assert painting.section == "9.1 Surface preparation"


def test_heading_lines_on_a_contents_page_stay_as_text(monkeypatch):
    """A contents page sets no heading state; its heading-shaped lines used to
    be consumed and kept nowhere (backlog item 3). Forced for the second page
    only, because what makes a page a contents page is is_contents_page's own
    business; the first page makes the clause numbers real ones."""
    real = C.is_contents_page
    monkeypatch.setattr(C, "is_contents_page",
                        lambda lines: "CONTENTS" in lines or real(lines))
    contents = ["CONTENTS", "8.1 General", "8.2 Coating materials",
                "The list above gives the clauses of this chapter in their order."]
    chunks = _chunks(CHAPTER, contents)
    page2 = " ".join(c.text for c in chunks if c.page_start <= 2 <= c.page_end)
    assert "8.1 General" in page2 and "8.2 Coating materials" in page2
