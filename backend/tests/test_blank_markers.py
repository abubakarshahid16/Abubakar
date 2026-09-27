"""Unit tests for `app.blank_markers` - the one home for "not provided yet".
CRS quick wins (audit crs.md defect 12). Standalone, no db.
"""
from __future__ import annotations

from app import blank_markers


def test_a_lone_star_is_blank():
    """THE MUTATION TARGET (M1311): the enquiry-sheet convention "* = vendor
    to advise" - a single character, which the old text-reader rule missed
    (it needed two)."""
    is_blank, marker = blank_markers.classify("*")
    assert is_blank is True
    assert marker == "*"


def test_vendor_to_advise_and_its_short_forms_are_blank():
    for value in ("VENDOR TO ADVISE", "TBA", "VTA", "By Contractor", "TBD",
                  "to be confirmed"):
        assert blank_markers.classify(value)[0] is True, value


def test_na_is_an_answer_not_a_blank():
    """THE MUTATION TARGET (M1312): "N/A" says the field does not apply -
    turning it into "to be provided" asks a vendor for a value the sheet has
    already said does not exist."""
    for value in ("N/A", "NA", "NIL", "NONE", "NOT REQUIRED", "no"):
        assert blank_markers.classify(value) == (False, None), value


def test_a_value_with_a_marker_anywhere_is_still_blank():
    """THE MUTATION TARGET (M1313): "340 psig By Contractor" is a provisional
    figure, not a value - the marker can sit inside a longer cell."""
    is_blank, marker = blank_markers.classify("340 psig By Contractor /Vendor")
    assert is_blank is True
    assert "contractor" in marker.lower()


def test_a_real_value_is_never_blank():
    assert blank_markers.classify("88 dB(A)") == (False, None)
    assert blank_markers.classify("SA-516 GR.70 (CARBON STEEL)") == (False, None)


def test_an_empty_cell_is_blank_with_the_empty_marker():
    assert blank_markers.classify("") == (True, "empty")
    assert blank_markers.classify(None) == (True, "empty")


def test_names_a_marker_reads_a_phrase_but_not_a_field_label():
    assert blank_markers.names_a_marker("vendor to advise") is True
    assert blank_markers.names_a_marker("BY PASS VALVE") is False
