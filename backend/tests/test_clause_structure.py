"""The clause structure of a standard (`clause_structure`, read by `StandardText.spans`): numbered clauses written like body text are found from the book's own evidence, and
nothing that only LOOKS like a clause number cuts a clause (the false-cut shapes of R74c). Invented books; no database, no model.

What each group guards: the real fault (a clause written like a sentence opens and closes nothing: the clause before it ran to the end of the book); every false-cut shape
(wrapped cross-reference, cross-reference at a line start, page header or footer with a later section number, decimal ratio, decimal and a word, date, number inside a sentence,
list item, "7.5 mm", table row, contents entry with dot leaders, with a page number, and with neither); the chain (a missed clause breaks it, only a titled heading restarts it);
`span_certain` (False = "boundary not certain": today's text is kept)."""

from __future__ import annotations

import pytest

from app import clause_structure as cs
from app import subject_scope as ss

NUM = ("number", "7.1.2.3")


def book(*pages: str) -> ss.StandardText:
    return ss.StandardText([(i + 1, t) for i, t in enumerate(pages)])


def span_text(t: ss.StandardText, clause=NUM) -> str:
    start, _soft, end = t.spans(clause)[0]
    return "\n".join(
        ln for ln, off in zip(t.lines, t.offsets, strict=False) if start <= off < end
    )


PREFIX = "7.1.2.1 Corrosion Allowance Basis\nThe basis is stated here.\n7.1.2.2 Minimum Allowance\nThe minimum is stated here.\n"
LIMIT = "7.1.2.3 The maximum C.A. shall be 3.2 mm.\nIf the service is sour a higher value may be agreed.\n"


def with_tail(tail: str) -> ss.StandardText:
    return book(PREFIX + LIMIT + tail)


def test_the_real_fault_a_clause_written_like_a_sentence_closes_the_clause_before_it():
    t = with_tail(
        "7.1.2.4 A corrosion allowance is not required for the internals.\n7.1.2.5 A second statement follows here.\n7.1.3 Pressure Tests\nSomething else.\n"
    )
    body = span_text(t)
    assert "higher value" in body and "not required" not in body
    assert t.span_certain(NUM) is True
    assert t.spans(("number", "7.1.2.4")) and "second statement" not in span_text(
        t, ("number", "7.1.2.4")
    )
    assert sorted(t.body_heads.values()) == [
        ("number", "7.1.2.4"),
        ("number", "7.1.2.5"),
    ]


def test_a_clause_with_no_closing_clause_is_boundary_not_certain_and_runs_on_as_today():
    t = with_tail("The text goes on and on.\n")
    assert t.span_certain(NUM) is False
    assert t.span_certain(("number", "9.9.9")) is None


@pytest.mark.parametrize(
    "inside",
    [
        "as required by\n7.2 of this standard, unless the service is sour.",  # a wrapped cross-reference
        "7.4 applies where the service is sour and 6 mm is permitted.",  # a cross-reference at a line start
        "8.1 Pressure Vessels\nUnless the service is sour, in which case 6 mm applies.",  # a header with a later section number
        "9.4 Page 12\nwhere the owner agrees otherwise.",  # a footer
        "7.5 times the stated value where the service is sour.",  # a decimal ratio
        "8.0 maximum where the service is sour.",  # a decimal and a word
        "12.05 November revision: unless the owner agrees.",  # a date
        "measured as in\n7.3 Annex B, and 6 mm where the service is sour.",  # a number and a capital word inside a sentence
        "1. Where the service is sour, 6 mm applies.\n2. For piping, 4 mm applies.",  # a list
        "(a) Where the service is sour, 6 mm applies.",
        "7.5 mm applies for piping.",  # a value with a unit
        "7.1.2.4\n12 mm 14 mm",  # a number alone, a table row after it
        "7.1.2.4 Corrosion allowance .......... 23",  # a contents entry with dot leaders
        "7.1.2.4 Corrosion allowance 23",  # a contents entry with a page number
    ],
)
def test_what_only_looks_like_a_clause_number_never_ends_a_clause(inside):
    t = with_tail(inside + "\nThe condition after it matters.\n")
    assert "The condition after it matters" in span_text(t)
    assert not any(h[1] == "7.1.2.4" for h in t.body_heads.values())


def test_a_wrapped_line_that_starts_with_the_next_number_is_not_a_clause_when_the_line_before_does_not_end_a_sentence():
    t = with_tail(
        "see also\n7.1.2.4 A corrosion allowance of the shell.\nThe condition after it matters.\n"
    )
    assert "The condition after it matters" in span_text(t) and not t.body_heads


def test_a_contents_page_never_opens_or_closes_a_clause():
    contents = "Contents\n7.1.2.3 Maximum Allowance ........ 12\n7.1.2.4 A corrosion allowance ........ 13\n7.1.3 Pressure Tests ........ 14\n7.1.4 Tests ........ 15\n7.1.5 More ........ 16\n"
    t = book(contents, PREFIX + LIMIT + "The text goes on.\n")
    assert not t.body_heads
    assert "higher value" in span_text(t)


def test_a_contents_entry_with_neither_leaders_nor_a_number_does_not_open_a_clause_the_line_before_is_no_sentence():
    t = book(
        "Contents\nScope\n7.1.2.4 A corrosion allowance basis\n7.1.2.5 A second basis\n",
        PREFIX + LIMIT + "The text goes on.\n",
    )
    assert not t.body_heads


def test_a_sub_clause_written_like_a_sentence_is_part_of_its_clause_and_a_titled_heading_restarts_the_chain():
    t = with_tail(
        "7.1.2.3.1 A sub-clause statement is here.\nMore of the sub-clause.\n7.1.2.4 A next clause statement is here.\n7.1.3 Pressure Tests\nText.\n"
    )
    assert "sub-clause statement" in span_text(t) and "next clause" not in span_text(t)
    assert ("number", "7.1.2.3.1") in t.body_heads.values()


def test_a_missed_clause_breaks_the_chain_and_only_a_titled_heading_restarts_it():
    # 7.1.2.4 starts with a lower-case word: not accepted; 7.1.2.5 is then no successor: not accepted either (no resync on a body-text number)
    t = with_tail(
        "7.1.2.4 the first statement starts in lower case.\n7.1.2.5 A statement after the missed one.\n7.1.3 Pressure Tests\nText.\n7.1.3.1 A child statement here.\n"
    )
    ids = sorted(h[1] for h in t.body_heads.values())
    assert "7.1.2.4" not in ids and "7.1.2.5" not in ids
    assert "7.1.3.1" in ids  # the titled heading 7.1.3 restarted the sequence
    assert t.body.rejected["starts with a lower-case word"] == 1
    assert (
        t.body.rejected[
            "well-formed but not the next clause (after a break, or a stray number)"
        ]
        >= 1
    )


def test_a_clause_number_alone_on_its_line_with_a_sentence_after_it_is_a_clause():
    t = with_tail(
        "7.1.2.4\nA corrosion allowance is not required for the internals.\n7.1.2.5\nA second statement follows here.\n"
    )
    assert [h[1] for h in sorted(t.body_heads.values())] == ["7.1.2.4", "7.1.2.5"]
    assert "not required" not in span_text(t)


def test_a_number_alone_whose_next_line_is_lower_case_or_a_number_is_not_a_clause():
    t = with_tail("7.1.2.4\nand the text continues in lower case.\nMore text here.\n")
    assert not t.body_heads and "More text here" in span_text(t)
    t = with_tail("7.1.2.4\n3.2\nMore text here.\n")
    assert not t.body_heads


def test_a_running_header_that_carries_a_section_number_is_no_clause():
    pages = [
        f"7.1.2.4 Corrosion Allowance Header\n{PREFIX if i == 0 else ''}{LIMIT if i == 0 else 'Page text continues here.'}\n"
        for i in range(4)
    ]
    t = book(*pages)
    assert not t.body_heads and "higher value" in span_text(t)


def test_a_bare_titled_heading_with_two_components_ends_a_clause_when_the_line_before_ends_a_sentence_and_a_page_number_does_not():
    t = with_tail("Some text ends here.\n7.1.3\nPressure Tests\nSomething else.\n")
    assert t.span_certain(NUM) is True and "Something else" not in span_text(t)
    t = with_tail(
        "Some text ends here\n8\nThe next page starts here.\n"
    )  # a page number: one component, no sentence before it
    assert t.span_certain(NUM) is False


def test_the_immediate_successor_is_the_first_child_the_next_sibling_or_the_next_of_an_ancestor():
    last = (7, 1, 2, 3)
    assert cs.immediate_successor((7, 1, 2, 3, 1), last) and cs.immediate_successor(
        (7, 1, 2, 4), last
    )
    assert (
        cs.immediate_successor((7, 1, 3), last)
        and cs.immediate_successor((7, 2), last)
        and cs.immediate_successor((8,), last)
    )
    assert (
        not cs.immediate_successor((7, 1, 2, 5), last)
        and not cs.immediate_successor((7, 1, 4), last)
        and not cs.immediate_successor((7, 1, 2, 3), last)
    )
    assert not cs.immediate_successor((1, 1), last) and not cs.immediate_successor(
        (7, 1, 2, 3, 2), last
    )


def test_a_one_component_number_never_ends_a_clause_for_certain_it_may_be_a_table_row():
    t = book(
        "4.1 Pressure\nThe design pressure shall be stated.\n5 Carbon steel flanges\nThe flange class shall be stated.\n4.2 Temperature\nText here.\n"
    )
    assert t.span_certain(("number", "4.1")) is True  # 4.2 ends it, not the "5" row
    assert "flange class" in span_text(t, ("number", "4.1"))


def test_a_well_formed_line_that_is_not_the_next_clause_is_not_a_clause():
    t = with_tail(
        "9.9.9 A statement that stands on a line of its own.\nThe condition after it matters.\n"
    )
    assert not t.body_heads and "The condition after it matters" in span_text(t)


@pytest.mark.parametrize(
    "word",
    [
        "Of the shell this statement applies.",
        "To be agreed with the owner.",
        "Or higher where agreed here.",
        "Pa is the unit used here.",
    ],
)
def test_a_reference_unit_or_date_word_after_the_number_is_not_the_start_of_a_clause(
    word,
):
    t = with_tail(f"7.1.2.4 {word}\nThe condition after it matters.\n")
    assert not t.body_heads and "The condition after it matters" in span_text(t)


def test_a_table_row_that_ends_in_a_figure_is_not_a_clause():
    t = with_tail("7.1.2.4 Carbon steel 12\nThe condition after it matters.\n")
    assert not t.body_heads and "The condition after it matters" in span_text(t)


def test_the_lines_of_a_contents_page_are_not_clauses_even_when_each_follows_a_sentence():
    contents = (
        "Contents.\n7.1.1 Scope Statement ........ 3\n7.1.2 Limits ........ 4\n7.1.3 Tests ........ 5\n7.1.4 More ........ 6\n7.1.5 Last ........ 7\n"
        "Notes are listed here.\n7.1.2.4 A corrosion allowance statement\n"
    )
    t = book(
        PREFIX + LIMIT + "The text goes on.\n", contents
    )  # the sequence is open (7.1.2.3) when the contents page starts: only the contents test can stop the line
    assert not t.body_heads


def test_a_bare_page_number_sets_no_soft_end_either():
    t = with_tail("Some text ends here\n8\nThe next page starts here.\n")
    start, soft, end = t.spans(NUM)[0]
    assert soft == end  # nothing closes the clause, not even softly
