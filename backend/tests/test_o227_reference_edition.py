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
