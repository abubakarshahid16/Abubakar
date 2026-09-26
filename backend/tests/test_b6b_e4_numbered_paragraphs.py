"""B6B E4: clause tracking for standards laid out as numbered paragraphs.

A real standard printed every clause as its number alone on a line with the
REQUIREMENT sentence beneath it ('6.2.1' / 'The unit shall be located
...'). The heading detector (rightly) refuses a sentence as a title, so the
document had no clause state and 25 chunks shared 2 labels - citations named
the wrong clause. E4: in a document whose titled headings the detector cannot
find (fewer than half its prose pages), a dotted clause number followed by a
sentence becomes the section - the number alone, no invented title. A
document with titled headings is chunked exactly as before.

Synthetic text only. Mutations M800-M802.
"""
from __future__ import annotations

from app import chunker as ch


_NOUNS = ["housing", "bearing", "coupling", "gasket", "impeller", "casing", "shaft",
          "seal", "flange", "nozzle", "baseplate", "guard", "lining", "vent", "drain",
          "sensor", "valve", "cover"]


def _page(p: int, prefix: str) -> str:
    """Three numbered paragraphs, every sentence distinct (no running lines)."""
    lines = []
    for k in (1, 2, 3):
        noun = _NOUNS[(p * 3 + k) % len(_NOUNS)]
        lines += [f"{prefix}.{p}.{k}",
                  f"The {noun} of unit {p} shall be inspected before shipment in case {k}.",
                  f"Records for the {noun} of unit {p} are kept by the supplier ({k})."]
    return "\n".join(lines)


#: Six pages of numbered paragraphs - no titled heading anywhere.
NUMBERED = [(p, _page(p, "4")) for p in range(1, 7)]


def _sections(pages):
    kinds = {p: "prose" for p, _ in pages}
    blocks, _ = ch.segment_document(pages, ch.detect_running_lines(pages), kinds)
    return [b.section for b in blocks if b.kind == "prose"]


def test_a_numbered_paragraph_document_gets_one_clause_per_paragraph():
    sections = _sections(NUMBERED)
    # EVERY clause, including the first on each page (top-of-page numbers
    # repeat as "#.#.#" and must not be stripped as a running header)
    assert set(sections) == {f"4.{p}.{k}" for p in range(1, 7) for k in (1, 2, 3)}, set(sections)


def test_the_clause_number_is_the_label_nothing_is_invented():
    assert all(s is None or ch._DOTTED_CLAUSE_ONLY.match(s) for s in _sections(NUMBERED))


def test_a_document_with_titled_headings_is_chunked_exactly_as_before():
    """Numbered paragraphs inside a titled document stay body text: the
    anchors are for documents with no other structure."""
    titles = ["Scope", "Materials", "Fabrication", "Inspection", "Testing", "Marking"]
    titled = [(p, f"5.{p} {titles[p - 1]}\n{_page(p, '5')}") for p in range(1, 7)]
    sections = set(_sections(titled))
    assert sections == {f"5.{p} {titles[p - 1]}" for p in range(1, 7)}, sections


def test_a_bare_integer_is_never_a_clause_anchor():
    """'12' alone above a sentence is a page number, not clause 12."""
    lines = ["12", "The widget housing shall be rated for duty at all times."]
    assert ch._numbered_paragraph(lines, 0) is None
    assert ch._numbered_paragraph(["4.2.1", *lines[1:]], 0) == "4.2.1"


def test_a_number_followed_by_a_fragment_is_not_an_anchor():
    """A value in a table ('2.5' / 'mm') is not a clause."""
    assert ch._numbered_paragraph(["2.5", "mm"], 0) is None
