"""Order 14 lane C: a code paragraph id alone on its line ("UG-150", "44-2") with a capitals title on the next line is a
heading, and its clause is the id. Before CHUNKER_VERSION 12 such a code was filed under stray table figures, so every
rule read from it carried a figure ("7.16") as its clause. Invented text only."""

from __future__ import annotations

from app import chunker as ch
from app import standards

FILLER = "The requirements of this part apply to the item described here and are met as stated."


def _page(*heads: tuple[str, str]) -> str:
    lines = ["7.16 NPS 10 (DN 250)", "1.0 2.0 3.0 4.0", FILLER]
    for number, title in heads:
        lines += [number, title, FILLER, FILLER]
    return "\n".join(lines)


def _sections(text: str) -> list[str | None]:
    blocks, _ = ch.segment_document([(1, text)], set())
    return [b.section for b in blocks]


def test_code_paragraph_ids_alone_with_a_capitals_title_are_headings():
    secs = _sections(
        _page(
            ("ZX-150", "GENERAL REQUIREMENTS"),
            ("ZX-151", "RESPONSIBILITIES"),
            ("12-1", "SCOPE"),
            ("12-2", "GENERAL REQUIREMENTS"),
        )
    )
    assert "ZX-150 GENERAL REQUIREMENTS" in secs and "ZX-151 RESPONSIBILITIES" in secs
    assert "12-1 SCOPE" in secs and "12-2 GENERAL REQUIREMENTS" in secs
    assert standards.clause_number("ZX-150 GENERAL REQUIREMENTS") == "ZX-150"
    assert standards.clause_number("12-2 GENERAL REQUIREMENTS") == "12-2"


def test_a_lone_id_a_sentence_a_grade_list_and_a_page_range_are_not_headings():
    text = "\n".join(
        [
            "QQ-7",
            "GENERAL REQUIREMENTS",
            FILLER,  # a series with ONE paragraph: a tag, not numbering
            "ZX-160",
            "The joint shall be examined as stated.",
            FILLER,  # a sentence, not a capitals title
            "SA-516",
            "WCA, WCB, WCC",
            FILLER,
            "SA-517",
            "WPL, WPB",
            FILLER,
            "SA-518",
            "B21/B22/B24V",
            FILLER,
            "ZX-120 \u2013 ZX-152",
            FILLER,  # a running page-range head
            "ZX-153(a) applies to the item.",
            FILLER,  # a cross-reference
        ]
    )
    secs = _sections(text)
    assert not any(
        s
        and s.split(" ", 1)[0]
        in {"QQ-7", "ZX-160", "SA-516", "SA-517", "SA-518", "ZX-120", "ZX-153(a)"}
        for s in secs
    )


def test_dotted_clauses_read_as_before():
    secs = _sections(
        "\n".join(["4.6", "Steel materials", FILLER, "4.7", "Coating", FILLER])
    )
    assert "4.6 Steel materials" in secs and "4.7 Coating" in secs
    assert standards.clause_number("4.6 Steel materials") == "4.6"
    assert (
        standards.clause_number("Rt") is None and standards.clause_number(None) is None
    )


def test_the_chunker_version_moved_so_stored_chunks_read_as_stale():
    assert ch.CHUNKER_VERSION == "12"
