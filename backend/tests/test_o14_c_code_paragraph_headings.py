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


# ---- R89 probes: a false open must not end a clause early --------------------------------------------------------------

HEADS = ["ZX-150", "GENERAL REQUIREMENTS", FILLER, "ZX-151", "RESPONSIBILITIES", FILLER]


def _secs_after(*lines: str) -> list[str | None]:
    return _sections("\n".join([*HEADS, *lines, FILLER]))


def test_a_cross_reference_wrapped_onto_its_own_line_opens_nothing():
    secs = _secs_after(
        "The weld shall be examined as required by",
        "ZX-153",
        "GENERAL REQUIREMENTS FOR WELDS",
    )
    assert not any(s and s.startswith("ZX-153") for s in secs)


def test_notes_under_an_id_open_nothing():
    secs = _secs_after("ZX-152", "NOTES", "ZX-152", "GENERAL NOTE")
    assert not any(s and s.startswith("ZX-152") for s in secs)


def test_a_list_of_ids_with_one_word_names_opens_nothing():
    secs = _secs_after(
        "Materials listed below.",
        "SA-105",
        "FORGINGS",
        "SA-106",
        "PIPE",
        "SA-516",
        "PLATE",
    )
    assert not any(s and s.startswith("SA-") for s in secs)


def test_a_real_code_paragraph_still_opens_after_a_sentence_and_after_a_capitals_title():
    secs = _sections(
        "\n".join(
            [
                "MANDATORY APPENDIX 12",
                "PRESSURE VESSELS",
                "12-1",
                "SCOPE",
                FILLER,
                "12-2",
                "GENERAL REQUIREMENTS",
                FILLER,
            ]
        )
    )
    assert "12-1 SCOPE" in secs and "12-2 GENERAL REQUIREMENTS" in secs


def test_a_code_paragraph_starts_its_own_heading_chain():
    """R89: the chain reset. A code paragraph nests under no dotted figure read before it."""
    paths: dict = {}
    text = "\n".join(["4.2", "Pipes larger than 2 inch", FILLER, *HEADS])
    ch.segment_document([(1, text)], set(), None, paths)
    assert paths["ZX-150 GENERAL REQUIREMENTS"] == "ZX-150 GENERAL REQUIREMENTS"


def test_known_limit_a_datasheet_tag_line_series_reads_as_headings():
    """KNOWN LIMIT (listed for the owner): tags alone on a line with a capitals line under them, two or more of one
    series, after a finished sentence, read as code paragraphs. Only a re-chunk of such a datasheet would show it."""
    secs = _sections(
        "\n".join(
            [
                "Tags are listed below.",
                "XQ-1",
                "INLET FLANGE",
                FILLER,
                "XQ-2",
                "OUTLET FLANGE",
                FILLER,
            ]
        )
    )
    assert "XQ-1 INLET FLANGE" in secs
