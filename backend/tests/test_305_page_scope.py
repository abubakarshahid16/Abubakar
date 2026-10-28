"""Order 305.3: where a page sits in a standard, and whether a stored sentence is whole. Invented text only, in the
shapes of the cases the planner's hand check found (appendix, special-construction part, worked example,
fragment, range boundary)."""

from __future__ import annotations

import pytest

from app import page_scope as ps


def _pages(*texts):
    return {i + 1: t for i, t in enumerate(texts)}


def test_a_standard_with_no_region_heading_is_main_body_throughout():
    tags = ps.tag_pages(
        _pages(
            "1 Scope\nThis standard covers valves.",
            "5 Sizing\nThe set pressure shall be stated.",
        )
    )
    assert {t["scope"] for t in tags.values()} == {ps.MAIN}
    assert not any(t["example"] for t in tags.values())


def test_a_mandatory_appendix_heading_marks_its_page_and_the_pages_after_it():
    tags = ps.tag_pages(
        _pages(
            "6 Installation\nValves shall be installed upright.",
            "MANDATORY APPENDIX 9\nJACKETED VESSELS\nThe pressure shall not exceed 5 bar.",
            "Further text of the appendix with no heading on this page.",
        )
    )
    assert tags[1]["scope"] == ps.MAIN
    assert tags[2]["scope"] == ps.MANDATORY and tags[2]["region"] == "Appendix 9"
    assert tags[3]["scope"] == ps.MANDATORY and tags[3]["region"] == "Appendix 9"


@pytest.mark.parametrize(
    "heading, scope",
    [
        ("NONMANDATORY APPENDIX A", ps.NONMANDATORY),
        ("Non-mandatory Appendix B", ps.NONMANDATORY),
        ("Annex C (informative)", ps.NONMANDATORY),
        ("Annex D (normative)", ps.MANDATORY),
        ("Appendix E", ps.APPENDIX),
    ],
)
def test_the_kind_of_appendix_is_read_from_its_own_words(heading, scope):
    assert ps.tag_pages(_pages(f"{heading}\nSome text here"))[1]["scope"] == scope


def test_a_sentence_that_mentions_an_appendix_is_not_a_heading():
    tags = ps.tag_pages(
        _pages("Appendix 9 shall be used when the vessel is jacketed, as stated here.")
    )
    assert tags[1]["scope"] == ps.MAIN


def test_a_part_whose_title_restricts_it_is_a_special_part_and_a_general_part_is_main_body():
    tags = ps.tag_pages(
        _pages(
            "PART UG GENERAL REQUIREMENTS FOR ALL METHODS OF CONSTRUCTION AND ALL MATERIALS\nText.",
            "PART UHT REQUIREMENTS FOR VESSELS MADE OF FERRITIC STEELS WITH ENHANCED PROPERTIES\nText.",
            "A later page of the same part.",
        )
    )
    assert tags[1]["scope"] == ps.MAIN
    assert tags[2]["scope"] == ps.SPECIAL and tags[2]["region"] == "Part UHT"
    assert tags[3]["scope"] == ps.SPECIAL


def test_a_part_with_no_readable_title_is_never_main_body():
    assert ps.tag_pages(_pages("PART UXX\n"))[1]["scope"] == ps.PART_UNKNOWN


def test_a_worked_example_flags_its_page_until_a_numbered_heading_closes_it():
    tags = ps.tag_pages(
        _pages(
            "5 Sizing\nText.\nExample 1: gas relief\nA vessel at 10 bar is relieved.",
            "More of the calculation on this page.",
            "6 Installation\nText.",
        )
    )
    assert tags[1]["example"] and tags[2]["example"] and not tags[3]["example"]


def test_a_page_with_main_body_text_before_a_heading_is_the_stricter_scope_and_a_boundary():
    tags = ps.tag_pages(
        _pages(
            "5 Sizing\nThe set pressure shall be stated.\nANNEX A (normative)\nBody of the annex."
        )
    )
    assert tags[1]["scope"] == ps.MANDATORY and tags[1]["boundary"]


@pytest.mark.parametrize(
    "text, reason",
    [
        ("shall not exceed 10 bar at any time in service.", "starts_mid_sentence"),
        ("and the set pressure shall not exceed 10 bar.", "starts_mid_sentence"),
        ("10 bar maximum.", "no_subject_before_limit"),
        ("The set pressure shall not exceed 10 bar and the", "cut_mid_clause"),
        ("Max 5 bar.", "too_short"),
    ],
)
def test_a_fragment_names_why(text, reason):
    assert reason in ps.fragment_reasons(text)


def test_a_whole_sentence_is_not_a_fragment():
    assert (
        ps.fragment_reasons(
            "The set pressure shall not exceed 10 bar at the inlet flange."
        )
        == []
    )


@pytest.mark.parametrize(
    "text, limit",
    [
        ("For vessels from 1000 kPa to 3000 kPa the accumulation is 10 %.", "1000"),
        ("For vessels from 1000 kPa to 3000 kPa the accumulation is 10 %.", "3000"),
        ("Between 15 and 70 bar the valve shall be of type B.", "70"),
        ("Vessels over 1000 and up to 3000 kPa need a second valve.", "1000"),
        ("Pressures of 10-50 bar are covered.", "50"),
    ],
)
def test_either_end_of_a_range_is_a_range_boundary(text, limit):
    assert ps.range_boundary(text, limit)


@pytest.mark.parametrize(
    "text, limit",
    [
        ("The set pressure shall not exceed 10 bar.", "10"),
        (
            "The accumulation shall not exceed 10 % of the set pressure; the set pressure is 1000 kPa.",
            "10",
        ),
        ("The valve shall lift at 3000 kPa.", "3000"),
    ],
)
def test_a_plain_ceiling_is_not_a_range_boundary(text, limit):
    assert not ps.range_boundary(text, limit)


def test_a_page_that_leaves_a_special_part_for_a_general_one_keeps_the_stricter_scope():
    tags = ps.tag_pages(
        _pages(
            "PART UHT REQUIREMENTS FOR VESSELS MADE OF FERRITIC STEELS\nText of the special part.\n"
            "PART UG GENERAL REQUIREMENTS FOR ALL MATERIALS\nText of the general part."
        )
    )
    assert tags[1]["scope"] == ps.SPECIAL and tags[1]["region"] == "Part UHT"


@pytest.mark.parametrize(
    "text",
    [
        "For vessels in gas service the set pressure shall not exceed 10 bar.",
        "Where the fluid is a liquid the accumulation shall not exceed 10 % of the set pressure.",
        "In fire cases the accumulation shall not exceed 21 % of the set pressure.",
    ],
)
def test_a_sentence_that_opens_with_for_where_or_in_is_whole(text):
    assert ps.fragment_reasons(text) == []


@pytest.mark.parametrize(
    "text, limit",
    [
        ("Valves rated to ISO 15156-3 shall have a set pressure of 3 bar.", "3"),
        ("See SAES-J-600 section 8-3 for the set pressure of 5 bar.", "3"),
    ],
)
def test_a_dash_between_figures_without_a_unit_is_a_code_not_a_range(text, limit):
    assert not ps.range_boundary(text, limit)


@pytest.mark.parametrize(
    "text, limit",
    [
        ("Pressures of 10-50 bar are covered.", "10"),
        ("Pressures of 10 bar - 50 bar are covered.", "50"),
    ],
)
def test_a_dash_between_figures_with_a_unit_is_a_range(text, limit):
    assert ps.range_boundary(text, limit)
