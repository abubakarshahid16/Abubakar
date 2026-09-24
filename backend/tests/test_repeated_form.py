"""A form repeated on every page is not a title block.

THE DEFECT, MEASURED ON A REAL DOCUMENT. `EF1975-DAS-I-06` is a KOC pressure
safety valve datasheet: five pages, one valve per page, the SAME FORM each
time. Every real field - `Set pressure`, `Relieving temperature`, `Density at
relieving temper.` - therefore appears on all five pages, and the furniture
rule, which stripped any label appearing on three or more pages, classified
the whole form as a header.

The sheet extracted **zero facts from 162 rows that carry a value**. The same
document had yielded 37 facts before the furniture rule existed, so this was a
regression introduced by a later fix, on a document the project had already
measured.

WHAT SEPARATES THE TWO, AND IT TOOK TWO CONDITIONS. Distinctness alone was
not enough: the drum sheet's title block `AL KHAFJI ONSHORE FACILITY` is empty
on six of the eight pages it appears on and catches a stray neighbouring
fragment on the other two - `D` on page 5, `2003` on page 7. That is two
distinct non-empty answers, so a distinctness test promotes the title block to
a field and `2003` becomes a fact, which is the junk this rule exists to stop.

A form field is ANSWERED. So a repeating label is a FIELD only when BOTH:

  1. two or more distinct non-empty answers, and
  2. non-empty on MORE THAN HALF the pages it appears on.

`AL KHAFJI ONSHORE FACILITY` fails the second at 2 of 8. `Set pressure`
passes both at 3 distinct answers over 4 of 4 pages.

MEASURED ON BOTH REAL SHEETS BEFORE THESE FIXTURES WERE WRITTEN:

  drum  48 facts, unchanged, and the `al khafji onshore facility` row dead.
  PSV   0 -> 35 facts, and all 25 `By Contractor` blank-marked facts survive -
        their answers differ per valve, so condition 1 is satisfied and no
        blank-marker exemption is needed.

Two PSV fields are lost to the rule and both are accounted for:
`separable flange material` reads `NA` on all four valves (one distinct
answer, condition 1), and `mole wt of relieved fluid` is paired with a value
on only two of the four pages (condition 2). Both are the accepted cost, not
a surprise.

Mutations: M174-M179, `python scripts/mutation_check.py --phase 13`.
"""

from __future__ import annotations

import pytest

from app import datasheets


TITLE_BLOCK = ("DOCUMENT NO.", "EF1975-DAS-I-06")
FOOTER = ("Company General Use", "")


def _repeated_form(pages: int = 5) -> dict[int, list[tuple[str, str]]]:
    """A page per valve: same labels, different answers, same title block."""
    return {
        page: [
            TITLE_BLOCK,
            FOOTER,
            ("Set pressure", f"{300 + page * 10} psig"),
            ("Relieving temperature", f"{200 + page}ºC"),
            ("Lifting lever", "Required"),
        ]
        for page in range(1, pages + 1)
    }


# ----------------------------------------------- the form must survive

def test_a_repeated_form_with_per_page_values_is_not_furniture():
    """THE REGRESSION, AS A TEST. Five pages, one form, five valves."""
    furniture = datasheets.furniture_labels(_repeated_form())

    assert "set pressure" not in furniture, (
        "the form field was stripped as a header - this is the defect that "
        "took EF1975-DAS-I-06 from 37 facts to zero")
    assert "relieving temperature" not in furniture


def test_the_title_block_on_the_same_pages_is_still_stripped():
    """THE OTHER HALF, and it must hold in the same fixture: the rule has to
    tell a header from a field IN ONE DOCUMENT, not in two different ones."""
    furniture = datasheets.furniture_labels(_repeated_form())

    assert "document no" in furniture, "the title block came back as a field"
    assert "company general use" in furniture, "an empty footer is furniture"


def test_two_distinct_answers_are_enough_to_make_it_a_field():
    """THE BOUNDARY. Four pages agree and the fifth does not; that is a form
    somebody filled in identically four times, not a header."""
    pages = {p: [("Set pressure", "340 psig")] for p in range(1, 5)}
    pages[5] = [("Set pressure", "145 psig")]

    assert "set pressure" not in datasheets.furniture_labels(pages)


def test_a_field_with_one_answer_throughout_is_still_stripped():
    """THE RESIDUAL, ASSERTED RATHER THAN HOPED FOR.

    `Lifting lever: Required` is a real field on all five valves and this rule
    cannot tell it from a footer. Stated as a test so the limitation is a
    known quantity and changing it is a deliberate act, not a surprise.

    On the real PSV sheet this costs `separable flange material` (`NA` on all
    four valves, 4 facts) and, through condition 2, `mole wt of relieved
    fluid` (paired with a value on only two of four pages, 2 facts). 35 facts
    survive. The cost is named in docs/cold-evaluation-psv-2026-09-19.md.
    """
    assert "lifting lever" in datasheets.furniture_labels(_repeated_form())


def test_a_label_on_too_few_pages_is_never_furniture():
    """The page threshold still applies: two pages is a multi-section sheet,
    not a header. Same value both times, so only the count can save it."""
    pages = {1: [("Design pressure", "3.5 bar")],
             2: [("Design pressure", "3.5 bar")]}

    assert datasheets.furniture_labels(pages) == set()


def test_case_and_spacing_are_spelling_not_a_different_answer():
    """"340 PSIG" and "340  psig" are one answer written twice. Treating them
    as two would let any title block whose case wobbles survive as a field."""
    pages = {1: [("Document no", "EF1975")],
             2: [("Document no", "ef1975")],
             3: [("Document no", "EF1975 ")]}

    assert "document no" in datasheets.furniture_labels(pages)


# --------------------------------- condition 2: mostly empty is a header

def test_a_mostly_empty_label_with_stray_values_is_furniture():
    """THE DRUM SHEET'S TITLE BLOCK, AS THE EXTRACTOR ACTUALLY SEES IT.

    `AL KHAFJI ONSHORE FACILITY` on 8 pages: empty on 6, and on two of them
    the extractor catches a neighbouring cell - `D` and `2003`. Two distinct
    non-empty answers, so condition 1 alone calls it a field and `2003`
    becomes a numeric fact on page 7. Condition 2 is what kills it: answered
    on 2 of 8 pages is not a form somebody filled in.
    """
    pages = {p: [("AL KHAFJI ONSHORE FACILITY", "")] for p in range(1, 9)}
    pages[5] = [("AL KHAFJI ONSHORE FACILITY", "D")]
    pages[7] = [("AL KHAFJI ONSHORE FACILITY", "2003")]

    furniture = datasheets.furniture_labels(pages)

    assert "al khafji onshore facility" in furniture, (
        "the title block was promoted to a field by its own stray fragments")


#: #179: an ANSWER is a value a fact could be made of (`states_a_value`), so
#: the boundary tests below answer in quantities. They used the letters
#: "a", "b", "c", which no longer count as answers - see the next test.
def test_answered_on_exactly_half_the_pages_is_still_furniture():
    """THE BOUNDARY, and it is MORE than half. Half a form is not a form -
    and an off-by-one here is the difference between a title block that is
    stripped and one that files a fact."""
    pages = {1: [("Somewhere", "1 bar")], 2: [("Somewhere", "2 bar")],
             3: [("Somewhere", "")], 4: [("Somewhere", "")]}

    assert "somewhere" in datasheets.furniture_labels(pages)


def test_answered_on_more_than_half_is_a_field():
    """The guard on the boundary above: one more answered page and the same
    label is a field, so the test is standing where the comparison decides."""
    pages = {1: [("Somewhere", "1 bar")], 2: [("Somewhere", "2 bar")],
             3: [("Somewhere", "3 bar")], 4: [("Somewhere", "")]}

    assert "somewhere" not in datasheets.furniture_labels(pages)


def test_a_title_block_fragment_is_not_an_answer():
    """#179, MEASURED ON THE REAL VESSEL SHEET after its page title stopped
    being appended to the title-block labels: the site-name row now carries
    the same label on every page, beside the word `OF` (from "SHEET n OF
    11") on four pages, a stray `D` on one and a stray `2003` on another.
    Counting `OF` as an answer made that "answered on most pages, several
    distinct answers" - a field - and `2003` became a numeric fact.
    `OF` states nothing a fact could hold, so it is not an answer."""
    pages = {p: [("SITE NAME FACILITY", "")] for p in range(1, 10)}
    for p in (3, 4, 5, 6):
        pages[p] = [("SITE NAME FACILITY", "OF")]
    pages[7] = [("SITE NAME FACILITY", "2003")]

    assert "site name facility" in datasheets.furniture_labels(pages), (
        "a title-block row was promoted to a field by the word OF")


def test_both_conditions_are_required_not_either():
    """Each condition alone lets one of the two real failures through."""
    # Answered everywhere, one answer: a header with constant text.
    constant = {p: [("Plant no", "2003")] for p in range(1, 5)}
    assert "plant no" in datasheets.furniture_labels(constant)
    # Many answers, mostly empty: a header catching its neighbours.
    sparse = {p: [("Sht no", "")] for p in range(1, 9)}
    sparse[1] = [("Sht no", "1")]
    sparse[2] = [("Sht no", "2")]
    assert "sht no" in datasheets.furniture_labels(sparse)


# ------------------------------- a blank marker is an answer, not an empty

def test_by_contractor_fields_survive_when_their_answers_differ():
    """THE CASE THAT COULD HAVE BROKEN THE SHEET, CHECKED AGAINST REAL DATA.

    25 of the PSV sheet's 35 facts are `By Contractor` blanks - the vendor has
    not filled them in yet, and recording them is how the review reports
    MISSING_INFORMATION rather than inventing a breach. A field reading
    exactly `By Contractor` on every page would have one distinct answer and
    would die under condition 1.

    On the real sheet none does: each carries a purchaser value beside the
    marker - `340 psig (By Contractor, as per Code)` against `145 psig By
    Contractor, as per Code` - so the answers differ per valve. Measured
    before this fixture was written; if it ever stops being true the rule
    needs a blank-marker exemption and this test is where that shows up.
    """
    pages = {
        1: [("Set pressure", "340 psig (By Contractor, as per Code)")],
        2: [("Set pressure", "340 psig (By Contractor, as per Code)")],
        3: [("Set pressure", "130 psig By Contractor, as per")],
        4: [("Set pressure", "145 psig By Contractor, as per Code")],
    }

    assert "set pressure" not in datasheets.furniture_labels(pages)


def test_an_identical_by_contractor_answer_everywhere_is_the_known_residual():
    """STATED SO THE LIMIT IS KNOWN, not discovered later on a live sheet.

    If a field ever does read exactly `By Contractor` on every page, this rule
    strips it. No such field exists on either real sheet today. This is the
    same residual as `Lifting lever`, and it is the trigger for adding a
    blank-marker exemption if a future sheet has one.
    """
    pages = {p: [("Orifice designation", "By Contractor")] for p in range(1, 5)}

    assert "orifice designation" in datasheets.furniture_labels(pages)


# ------------------------------------------------- the drum sheet's shape

def test_a_single_equipment_sheet_still_strips_its_header():
    """THE TUNED SHEET'S SHAPE, which must not regress: different fields on
    each page, one header across all of them."""
    pages = {
        1: [("Vessel data sheet", "Rev 0"), ("Internal design pressure", "3.5 bar")],
        2: [("Vessel data sheet", "Rev 0"), ("Shell thickness", "12 mm")],
        3: [("Vessel data sheet", "Rev 0"), ("Skirt height", "300 mm")],
    }

    furniture = datasheets.furniture_labels(pages)

    assert furniture == {"vessel data sheet"}
    for field in ("internal design pressure", "shell thickness", "skirt height"):
        assert field not in furniture


# ================================================== the diagnostic

def test_a_page_with_no_pairs_says_exactly_that():
    assert datasheets._unparsed_reason([], {}) == (
        "no label-value pairs recovered from this page")


def test_a_page_whose_pairs_were_filtered_names_the_filters():
    """THE MESSAGE THAT SENT A READER TO THE WRONG HALF OF THE PIPELINE.

    Five pages of EF1975-DAS-I-06 reported "no label-value pairs recovered"
    while 190 pairs per page had been recovered and discarded. One sentence
    covered both a scanned page with no text and a rule that was too strict,
    and those want opposite responses.
    """
    reason = datasheets._unparsed_reason(
        [("a", "1")] * 190,
        {"value gate": 120, "duplicate": 50, "furniture": 20})

    assert "190 label-value pairs were recovered" in reason
    assert "120 by value gate" in reason
    assert "50 by duplicate" in reason
    assert "20 by furniture" in reason
    assert "no label-value pairs recovered" not in reason, (
        "the page reported the one failure it did NOT have")


def test_the_counts_are_ordered_by_size_so_the_cause_reads_first():
    reason = datasheets._unparsed_reason(
        [("a", "1")] * 10, {"furniture": 9, "duplicate": 1})

    assert reason.index("9 by furniture") < reason.index("1 by duplicate")


def test_a_page_that_recovered_pairs_never_claims_it_recovered_none():
    """The guard as a property rather than an example: whatever the counts,
    a page with pairs must not print the empty-page sentence."""
    for dropped in ({"furniture": 3}, {"value gate": 3}, {}):
        reason = datasheets._unparsed_reason([("a", "1")] * 3, dropped)
        assert "no label-value pairs recovered" not in reason
