"""Order 227 item 1: every CRS Standard Reference says which copy of the standard it cites.

"SAES-G-005 (2023) cl. 4.3.5 (p.15)": standard, edition, clause, page. The edition is the one
the library knows (stored on the finding, or printed in the standard's own name); none known says
"edition not recorded", never a guess; a name that already carries its year is not given it
twice. Invented standards only.
"""

from __future__ import annotations

import pytest

from app import crs_machine_words as mw
from app import crs_mapping, crs_reference
from tests.test_139_crs_one_per_field import _f


def _ref(name, **over):
    finding = {
        "standard_name": name,
        "standard_clause": "4.3.5",
        "standard_page": 15,
        **over,
    }
    return crs_mapping._standard_reference(finding)


def test_a_stored_edition_is_printed_between_the_standard_and_its_clause():
    assert (
        _ref("SAES-G-005.pdf", standard_edition="2023")
        == "SAES-G-005 (2023) cl. 4.3.5 (p.15)"
    )


def test_an_edition_printed_in_the_standards_own_name_is_found_not_repeated():
    assert _ref("ASME-B16.5-2020.pdf") == "ASME-B16.5-2020 cl. 4.3.5 (p.15)"


def test_a_standard_with_no_known_edition_says_so_and_never_guesses():
    assert (
        _ref("SAES-G-005.pdf") == "SAES-G-005 (edition not recorded) cl. 4.3.5 (p.15)"
    )
    # a number is not an edition: five digits, a dotted part, a pressure class
    for name in ("API 12345.pdf", "ASME B16.47.pdf", "ISO 9001.pdf"):
        assert f"({crs_reference.NOT_RECORDED})" in _ref(name), name


def test_an_edition_on_the_finding_wins_over_a_year_in_the_name():
    assert "(2024)" in _ref("SAES-G-005-2019.pdf", standard_edition="2024")


@pytest.mark.parametrize("edition", ["", None, "   "])
def test_an_empty_stored_edition_falls_back_to_the_name_then_to_not_recorded(edition):
    assert "(edition not recorded)" in _ref("SAES-G-005.pdf", standard_edition=edition)
    assert _ref("SAES-G-005-2023.pdf", standard_edition=edition).startswith(
        "SAES-G-005-2023 cl."
    )


def test_a_table_number_clause_keeps_the_edition_and_the_page():
    ref = _ref("SAES-G-005.pdf", standard_edition="2023", clause_identified=False)
    assert ref.startswith("SAES-G-005 (2023)") and "(p.15)" in ref
    assert "4.3.5" not in ref


def test_the_edition_reaches_the_row_and_the_comment_lead():
    [row] = crs_mapping.build_crs_rows(
        [
            _f(
                "e1",
                "4.3",
                compliance_status="NON_COMPLIANT",
                crs_is_blank=False,
                contractor_evidence_text="1.5 mm",
                standard_edition="2023",
            )
        ],
        [],
        "sheet.pdf",
    )
    assert row["standard_reference"] == "STD-100 (2023) cl. 4.3 (p.4)"
    assert row["comment"].startswith("STD-100 (2023) cl. 4.3 (p.4): ")


def test_the_phrase_is_not_the_program_talking_to_the_contractor():
    ref = _ref("SAES-G-005.pdf")
    assert mw.find_machine_words(ref) == []


@pytest.mark.parametrize(
    "name",
    ["ISO 2014.pdf", "NFPA 2001.pdf", "IEC 2000.pdf", "BS 1992.pdf", "ISO_2014.pdf"],
)
def test_a_standards_own_number_is_not_its_edition(name):
    """Cloud's review of #1307: a four-digit standard NUMBER printed as a year is a fact
    the sheet never stated (rule 4); it must read 'edition not recorded'."""
    assert crs_reference.edition_of(name) is None
    assert "(edition not recorded)" in _ref(name)


@pytest.mark.parametrize(
    "name, edition",
    [
        ("API 650 2020 Addendum 1 2021.pdf", "2020"),
        ("API-650-2020-Add-1-2021.pdf", "2020"),
        ("EN 1092-1 2018+A1 2020.pdf", "2018"),
        ("API 653 2018 Amendment 2.pdf", "2018"),
        ("NFPA 2001 2018 Edition.pdf", "2018"),
        ("ISO 9001:2015.pdf", "2015"),
        ("ASME-B16.5-2020.pdf", "2020"),
    ],
)
def test_an_addendum_or_amendment_year_is_not_the_edition(name, edition):
    assert crs_reference.edition_of(name) == edition


def test_an_addendum_alone_gives_no_edition():
    assert crs_reference.edition_of("API 650 Addendum 1 2021.pdf") is None


def test_the_year_must_be_a_whole_number_in_the_name_to_count_as_printed_there():
    """'2023' inside '20230' is not the name carrying its year: the edition is still shown."""
    assert "(2023)" in _ref("SAES-G-20230.pdf", standard_edition="2023")


def test_the_ai_wording_lock_keeps_the_edition_and_refuses_a_changed_one():
    from app import crs_wording

    row = {
        "row_kind": "non_compliant",
        "comment": (
            "SAES-G-005 (2023) cl. 4.3.5 (p.15): requires noise level not more than 85 dB(A). "
            "Datasheet p.3, Noise level states 92. Contractor to revise Noise level to meet the "
            "requirement, or submit a deviation request with justification for Company approval."
        ),
        "crs_row_key": "k1",
        "standard_reference": "SAES-G-005 (2023) cl. 4.3.5 (p.15)",
        "page_section": "p.3 - Noise level",
    }
    good = (
        "Per SAES-G-005 (2023) cl. 4.3.5, the noise level is required to be not more than "
        "85 dB(A); the datasheet (p.3) states 92. Please revise the noise level to meet the "
        "requirement, or submit a deviation request with justification for Company approval."
    )
    assert crs_wording.lock(good, row) is None
    assert (
        crs_wording.lock(good.replace("(2023)", "(2019)"), row)
        == crs_wording.NUMBER_CHANGED
    )
