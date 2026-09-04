"""Clause headings, footer removal, heading boundaries and designator ranking.

Engineers cite CLAUSES, not pages. An answer citing "page 8" is close to
useless to a specification reviewer; "Clause 4.5 Coating materials" is what
they would write in a report. Every one of these tests exists because a real
petroleum standard exercised a layout two textbooks never did.
"""

import pytest

from app import keyword, search
from app.chunker import (
    _split_line_heading,
    detect_running_lines,
    looks_like_heading,
    segment_document,
    strip_running_lines,
)

# ------------------------------------------------------------ FIX 1 headings

SINGLE_LINE_HEADINGS = [
    ("4.5 Coating materials", "4.5 Coating materials"),
    ("5.3.2 Qualification of personnel", "5.3.2 Qualification of personnel"),
    ("1.2.1 Self-Driving Vehicles", "1.2.1 Self-Driving Vehicles"),
    ("A.4 Coating system no. 4", "A.4 Coating system no. 4"),
    ("A.5.1 Coating system no. 5A", "A.5.1 Coating system no. 5A"),
]

NOT_HEADINGS = [
    "330 Hudson Street, NY, NY 10013",          # publisher address
    "0 K(s, t) f(t) dt",                        # integral
    "3 L/min",                                  # figure annotation
    "9.3.2 Protecting Personal Data 475",       # contents line
    "1 Acceptance criteria are considered acceptable",   # footnote
    "15 Proper use of mutex(es) to avoid races",         # rubric row
    "01 Baseline the system",                   # numbered list item
    "1 (a) Cosine integral",                    # equation label
]


@pytest.mark.parametrize("line,expected", SINGLE_LINE_HEADINGS)
def test_numbered_and_annex_clauses_are_headings(line, expected):
    assert looks_like_heading(line) == expected


@pytest.mark.parametrize("line", NOT_HEADINGS)
def test_things_that_merely_start_with_a_number_are_not_headings(line):
    assert looks_like_heading(line) is None


SPLIT_LINE = [
    (["4.6 ", "Steel materials "], "4.6 Steel materials"),
    (["4.7 ", "Shop primer "], "4.7 Shop primer"),
    (
        ["A.1 ", "Coating system no. 1 (shall be pre-qualified) "],
        "A.1 Coating system no. 1 (shall be pre-qualified)",
    ),
]


@pytest.mark.parametrize("lines,expected", SPLIT_LINE)
def test_a_clause_number_alone_takes_its_title_from_the_next_line(lines, expected):
    """NORSOK, and most engineering specifications, lay headings out as the
    clause number on one line and the title on the next. Requiring both on one
    line is why every chunk in such a document had section: null."""
    head, consumed = _split_line_heading([line.strip() for line in lines], 0)
    assert head == expected
    assert consumed == 2


def test_a_numbered_list_item_does_not_swallow_the_sentence_after_it():
    lines = ["1.", "This sentence is ordinary body text that runs on for a good while."]
    assert _split_line_heading(lines, 0) == (None, 1)


def test_a_heading_persists_across_pages_until_the_next_one():
    pages = [
        (10, "4.6 \nSteel materials \nSteel subject to surface preparation shall comply."),
        (11, "Further requirements continue here with no new heading of their own."),
    ]
    blocks, _ = segment_document(pages, running=set())
    assert blocks
    assert all(b.section == "4.6 Steel materials" for b in blocks)


# -------------------------------------------------------------- FIX 2 footer


def test_a_page_footer_below_the_header_block_is_still_stripped():
    """NORSOK stacks four lines of furniture and the page number is the fourth.
    A three-line window caught the first three and left "Page 6 of 20"
    prepended to the text of nearly every chunk."""
    words = (
        "coating primer topcoat epoxy zinc galvanising blasting roughness "
        "adhesion thickness inspection holiday salt chloride humidity"
    ).split()

    def page(n: int) -> str:
        # A realistic page: four lines of furniture, then a body whose lines
        # genuinely differ from page to page. Templated body lines would be
        # correctly detected as running lines and stripped, which would make
        # the test prove the opposite of what it intends.
        body = "\n".join(
            f"Requirement {n}.{i} concerns {words[(n * 7 + i * 3) % len(words)]} "
            f"and {words[(n * 3 + i * 5) % len(words)]} during application."
            for i in range(14)
        )
        return (
            "NORSOK standard M-501 \nRev. 5, June 2004 \nNORSOK standard \n"
            f"Page {n} of 20 \n{body}"
        )

    pages = [(n, page(n)) for n in range(1, 21)]
    running = detect_running_lines(pages)
    assert any("page # of #" in r for r in running), f"footer not detected: {running}"

    cleaned, removed = strip_running_lines(pages[7][1], running)
    assert removed >= 4
    assert "Page 8 of 20" not in cleaned
    assert "Requirement 8.0 concerns" in cleaned


# ---------------------------------------------------- FIX 3 heading boundary


def test_a_heading_is_never_split_from_the_block_it_introduces():
    """One annex chunk began mid-heading at "5A (shall be pre-qualified)"
    because the token ceiling fell inside the title."""
    from app.chunker import Block, _enforce_ceiling, count_tokens
    from app.config import settings

    heading = "A.5.1 Coating system no. 5A (shall be pre-qualified)"
    body = " ".join(f"cell{i}" for i in range(900))
    block = Block("prose", heading + "\n" + body, 18, 18, heading)
    block.tokens = count_tokens(block.text)
    assert block.tokens > settings.chunk_max_tokens, "fixture must exceed the ceiling"

    pieces = _enforce_ceiling([block])
    assert len(pieces) > 1
    assert pieces[0].text.startswith("A.5.1 Coating system no. 5A"), (
        f"heading was split: {pieces[0].text[:60]!r}"
    )


# ----------------------------------------------------- FIX 4 designators


DESIGNATORS = [
    ("NDFT for coating system no. 1", "system 1"),
    ("what does coating system 3B require", "system 3B"),
    ("requirements for type 2 surfaces", "type 2"),
    ("class 300 flange rating", "class 300"),
]


@pytest.mark.parametrize("question,expected", DESIGNATORS)
def test_designators_are_extracted(question, expected):
    """These are not code-shaped, so the identifier pattern misses them - and
    missing one is worse than missing a code, because the passage retrieved is
    about a DIFFERENT system and reads perfectly plausible."""
    assert expected in keyword.find_designators(question)


def test_designator_spellings_are_all_matched():
    variants = keyword.designator_variants("system 1")
    assert "system 1" in variants
    assert "system no. 1" in variants
    assert "system number 1" in variants


def test_a_designator_is_required_in_the_match_expression():
    expr = keyword.build_match_query("NDFT for coating system no. 1")
    assert '"system no. 1"' in expr
    assert " AND " in expr


def test_the_heading_decides_which_designator_a_passage_is_about():
    """Annex A.4's body genuinely says "Coating system no. 1 may be used on
    other deck areas", so body matching alone cannot tell A.1 from A.4. The
    clause heading is the authoritative scope."""
    a1 = search.Candidate(
        chunk_id="a1", document_id="d", filename="spec.pdf",
        section="A.1 Coating system no. 1 (shall be pre-qualified)",
        page_start=17, page_end=17,
        text="Cleanliness ISO 8501-1 Sa 2 1/2. NDFT 60 um.",
        rrf=0.020,
    )
    a4 = search.Candidate(
        chunk_id="a4", document_id="d", filename="spec.pdf",
        section="A.4 Coating system no. 4 (shall be pre-qualified)",
        page_start=19, page_end=19,
        # a real cross-reference to system 1 in the body
        text="Coating system no. 1 may be used on other deck areas. NDFT 100 um.",
        rrf=0.030,   # deliberately the better retrieval score
    )
    pool = [a1, a4]
    search.apply_identifier_boost("NDFT for coating system no. 1", pool)
    search._apply_conflict_penalty(pool)

    assert a4.conflicts == ["system 4"], f"conflict not detected: {a4.conflicts}"
    assert not a1.conflicts
    assert a1.score > a4.score, (
        "the passage headed 'system no. 4' outranked the one headed 'system no. 1' "
        "- system 4's figures would be quoted as system 1's"
    )


def test_a_passage_with_no_designator_in_its_heading_is_not_penalised():
    c = search.Candidate(
        chunk_id="c", document_id="d", filename="spec.pdf",
        section="4.5 Coating materials", page_start=8, page_end=8,
        text="Applicable coating systems are tabulated in Annex A.", rrf=0.02,
    )
    search.apply_identifier_boost("NDFT for coating system no. 1", [c])
    search._apply_conflict_penalty([c])
    assert c.conflicts == []
    assert c.penalty == 0.0
