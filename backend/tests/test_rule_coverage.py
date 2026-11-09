"""Coverage of numeric requirement sentences by compiled rules (Lane 1 b). Every text here is INVENTED."""

from __future__ import annotations

from app import rule_coverage as rc

PAGE = (
    "4.1 Sizing\n"
    "The inlet pipe shall be at least 50 mm in diameter.\n"
    "The vent shall be at least 15 m from any ignition source.\n"
    "The vendor shall paint the valve.\n"
    "Valves must be tested at 10 bar.\n"
    "Refer to clause 4.2 and table 7 for details.\n"
)


def rules(*quotes, page=1):
    return [{"page": page, "quote": q} for q in quotes]


def test_numeric_requirement_sentences_need_an_obligation_word_and_a_figure_with_a_unit():
    result = rc.numeric_clause_coverage({1: PAGE}, [])
    assert (
        result["numeric"] == 3 and result["covered"] == 0 and result["uncovered"] == 3
    )
    assert not rc.is_numeric_requirement(
        "The vendor shall paint the valve in 2 coats."
    )  # 2 coats: no unit of the table
    assert not rc.is_numeric_requirement(
        "The pipe is 50 mm in diameter."
    )  # no obligation
    assert rc.is_numeric_requirement("The pipe is required to be 50 mm in diameter.")


def test_a_sentence_a_rule_quotes_is_covered_and_the_others_are_not():
    result = rc.numeric_clause_coverage(
        {1: PAGE}, rules("The inlet pipe shall be at least 50 mm in diameter.")
    )
    assert (result["numeric"], result["covered"], result["uncovered"]) == (3, 1, 2)
    open_ones = [i for i in result["items"] if not i["covered"]]
    assert all(
        i["page"] == 1 and i["clause"] == "4.1" and i["offset"] is not None
        for i in open_ones
    )


def test_a_quote_that_is_part_of_a_sentence_covers_it_and_whitespace_does_not_matter():
    result = rc.numeric_clause_coverage(
        {1: PAGE}, rules("at least  15 m\nfrom any ignition source")
    )
    assert result["covered"] == 1


def test_a_rule_on_another_page_covers_nothing_here():
    result = rc.numeric_clause_coverage(
        {1: PAGE, 2: "Filler text."},
        rules("The inlet pipe shall be at least 50 mm in diameter.", page=2),
    )
    assert result["covered"] == 0 and result["uncovered"] == 3


def test_a_page_without_figures_has_nothing_to_cover():
    assert (
        rc.numeric_clause_coverage({1: "Widgets shall be painted."}, [])["numeric"] == 0
    )
