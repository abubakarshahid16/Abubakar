"""The clause locator of a technical query's evidence passage (lead-4, 26 Nov 2026, goal G6: a clause number on every passage). Invented
page text only."""

from __future__ import annotations

from app.technical_query_match import heading_above, last_heading, locator_for


def test_a_clause_number_alone_on_its_line_takes_its_title_from_the_next_line():
    page = "Invented Contract Part\n4.2.1\nInvented Cooling Water\nThe invented header shall be designed for 12 bar."
    assert (
        heading_above(page, "The invented header shall be designed for 12 bar.")
        == "4.2.1 Invented Cooling Water"
    )
    page2 = "1.\nScope Of Invented Work\nThe invented contractor shall supply the invented pumps."
    assert (
        heading_above(page2, "The invented contractor shall supply the invented pumps.")
        == "1 Scope Of Invented Work"
    )


def test_a_passage_that_opens_with_its_own_clause_is_located_at_that_clause_not_the_one_before():
    page = "7.13 Invented Earlier Clause\nInvented earlier words.\n8.1 Invented Own Clause\nThe invented own clause words."
    assert (
        heading_above(page, "8.1 Invented Own Clause The invented own clause words.")
        == "8.1 Invented Own Clause"
    )


def test_a_heading_inside_the_start_of_the_passage_is_used_when_none_stands_above_it():
    page = "Invented page header\nSome invented lead-in text.\n3.4 Invented Clause\nThe invented clause words."
    assert (
        heading_above(
            page,
            "Some invented lead-in text. 3.4 Invented Clause The invented clause words.",
        )
        == "3.4 Invented Clause"
    )


def test_a_table_of_numbers_is_not_a_heading():
    table = "1.2.3\n4.5\n% of invented total\nA\n( A $ )"
    assert last_heading(table) is None


def test_the_last_heading_of_the_page_before_still_serves_a_passage_with_none_on_its_page():
    earlier = "5.6\nInvented Testing\nInvented words."
    assert (
        locator_for(
            "Invented words without any heading.",
            earlier,
            "Invented words without any heading.",
        )
        == "5.6 Invented Testing"
    )
