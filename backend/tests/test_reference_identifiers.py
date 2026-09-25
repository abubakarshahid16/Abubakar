"""Which strings are a citation, and which library filename means which number.

TWO DIFFERENT JOBS WITH DIFFERENT TOLERANCES, and keeping them apart is the
point of this file.

A CITATION is a claim about which document governs a submittal. It is read out
of running prose, where every loose alternative costs a false reference that an
engineer then goes looking for. So the citation pattern is strict: a complete
identifier or nothing.

A LIBRARY FILENAME is a name somebody typed once, carrying revision notes,
dates and draft markers. Reading a number out of it can be forgiving, because
the only thing at stake is whether a document already in the library can be
recognised as itself.

That asymmetry is why `SAES-B-14` is padded to SAES-B-014 in the FILENAME
parser and is deliberately absent from the CITATION pattern: a two-digit
alternative there would match the first two digits of a three-digit number and
cite the wrong standard, confidently.
"""

from __future__ import annotations

import pytest

from app.applicability import library_identifier, normalise_identifier
from app.datasheets import referenced_standards


# ------------------------------------------------------- citation: shapes

@pytest.mark.parametrize("text,expected", [
    # Saudi Aramco material system specifications. This corpus's own submittal
    # cites 32-SAMSS-004 ten times and the pattern could not see it at all.
    ("Vessels shall comply with 32-SAMSS-004 throughout.", ["32-SAMSS-004"]),
    ("per 01-SAMSS-016 and 02-SAMSS-014", ["01-SAMSS-016", "02-SAMSS-014"]),
    # Three-digit and four-digit SAES.
    ("as required by SAES-A-206", ["SAES-A-206"]),
    ("as required by SAES-R-1101", ["SAES-R-1101"]),
    # ASME, only ever with a complete identifier.
    ("flanges to ASME B16.5", ["ASME B16.5"]),
    ("piping to ASME B31.3", ["ASME B31.3"]),
    ("vessel per ASME Sec VIII Div 1", ["ASME Sec VIII Div 1"]),
    ("vessel per ASME Section VIII", ["ASME Section VIII"]),
])
def test_each_citation_shape_is_read_whole(text, expected):
    assert referenced_standards(text) == expected


def test_a_bare_asme_family_letter_is_not_a_citation():
    """THE NEGATIVE FIXTURE, and the defect it stands for.

    The old pattern matched `ASME\\s*[IVXB]+`, so "ASME B31.3" yielded the two
    characters "ASME B" - a whole family of codes, not a document. It was then
    reported as a MISSING reference: a citation that can never resolve, shown
    to an engineer as a gap in the library, sending them to look for a document
    that does not exist under that name.

    Asserted as an absence AND as a presence on the same input, so this cannot
    pass by the pattern having stopped matching anything at all.
    """
    found = referenced_standards("piping shall be to ASME B31.3 throughout")

    assert "ASME B" not in found
    assert found == ["ASME B31.3"], "the complete identifier must still be read"


@pytest.mark.parametrize("text", [
    "the ASME B family of codes",          # no number at all
    "ASME Section",                        # no roman numeral
    "the vessel is ASME stamped",
])
def test_an_incomplete_asme_reference_is_not_a_citation(text):
    """An identifier nobody can look up is worse than no identifier."""
    assert [f for f in referenced_standards(text) if f.upper().startswith("ASME")] == []


@pytest.mark.parametrize("text,expected", [
    # KOC standard numbers use BOTH one-letter and two-letter discipline
    # codes (the pump datasheet's own reference list, page 7: KOC-ME-008 Pt1/Pt2 are
    # two-letter "mechanical equipment"; KOC-E-003, KOC-E-004, KOC-E-010,
    # KOC-E-020 are one-letter "electrical"; KOC-P-001 is one-letter
    # "painting"). The pattern required exactly two letters, so a real
    # submittal's electrical and painting standard citations were silently
    # dropped - never reported applicable, and never reported missing
    # either, because the extractor never saw them as citations at all.
    ("per KOC-E-003 and KOC-E-004", ["KOC-E-003", "KOC-E-004"]),
    ("per KOC-E-010 and KOC-E-020", ["KOC-E-010", "KOC-E-020"]),
    ("painting per KOC-P-001", ["KOC-P-001"]),
    ("per KOC-G-004 and KOC-I-002 and KOC-Q-014", ["KOC-G-004", "KOC-I-002", "KOC-Q-014"]),
    # Two-letter discipline codes must keep working unchanged.
    ("per KOC-ME-008 Pt1 and KOC-MP-027", ["KOC-ME-008 Pt1", "KOC-MP-027"]),
])
def test_koc_one_and_two_letter_discipline_codes_are_both_read(text, expected):
    assert referenced_standards(text) == expected


def test_a_bare_two_digit_saes_is_not_a_citation():
    """NOT in the citation pattern, on purpose.

    "SAES-B-14" in prose is far more likely to be a typo or a truncation than a
    real document number, and a two-digit alternative would also match the
    first two digits of SAES-B-140 - citing a different standard with complete
    confidence. The forgiving read happens on FILENAMES only, below.
    """
    assert referenced_standards("see SAES-B-14 for details") == []
    # And the three-digit form on the same shape still reads, so this is not
    # passing because the SAES alternative broke.
    assert referenced_standards("see SAES-B-140 for details") == ["SAES-B-140"]


# --------------------------------------------- library filename: padding

@pytest.mark.parametrize("filename,expected", [
    ("SAES-B-14 -Final Draft 01-29-23.pdf", "SAES-B-014"),
    ("SAES-B-014.pdf", "SAES-B-014"),
    ("SAES-A-105.pdf", "SAES-A-105"),
    ("SAES-R-1101.PDF", "SAES-R-1101"),
    ("SAES-B-062 Editorial Revision.pdf", "SAES-B-062"),
    ("SAES-B-801 Editorial Revision _10-27-2021_.pdf", "SAES-B-801"),
])
def test_a_library_filename_resolves_to_its_padded_number(filename, expected):
    assert library_identifier(filename) == expected


@pytest.mark.parametrize("filename", [
    "P-1000001-2003-SP-0810-0003_00.pdf",     # a submittal, not a standard
    "Engineering Deliverables.pdf",
    "notes about SAES-B-014.pdf",           # the number is not at the start
])
def test_a_filename_that_is_not_a_standard_number_yields_nothing(filename):
    """Anchored at the start: a filename MENTIONING a number is not that
    document, and treating it as one would put another document's requirements
    under this one's name."""
    assert library_identifier(filename) is None


def test_the_padded_filename_matches_the_citation_key():
    """The two sides meeting, which is the whole point.

    The library holds `SAES-B-14 -Final Draft 01-29-23.pdf`; a submittal cites
    `SAES-B-014`. Before padding, the filename's comparison key was
    "SAESB14FINALDRAFT01292 3PDF" and the document could not be matched to
    itself.
    """
    from_filename = normalise_identifier(
        library_identifier("SAES-B-14 -Final Draft 01-29-23.pdf"))
    from_citation = normalise_identifier(
        referenced_standards("built to SAES-B-014 requirements")[0])

    assert from_filename == from_citation == "SAESB014"
