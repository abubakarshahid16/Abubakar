"""The one non-trivial piece of scripts/export_cited_but_not_held.py: finding
an edition/revision mentioned near a citation, without attributing a LATER
standard's edition to an EARLIER one in the same sentence."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
from export_cited_but_not_held import _edition_near


def test_an_edition_year_right_after_the_citation_is_found():
    assert _edition_near("Materials shall comply with ASME B31.3-2020 "
                         "for all piping.", "ASME B31.3") == "-2020"


def test_an_ordinal_edition_right_after_the_citation_is_found():
    assert _edition_near("Pump shall comply with API 610 11th Edition.",
                         "API 610") == "11th Edition"


def test_no_edition_nearby_returns_none():
    assert _edition_near("Pump shall comply with API 610 for all service.",
                         "API 610") is None


def test_an_edition_belonging_to_a_different_earlier_standard_is_not_attributed():
    """THE MUTATION TARGET: "NACE MR0175 (2015)" is a different standard's
    edition, mentioned BEFORE "API 610" in the same sentence - it must not
    be read as API 610's own edition."""
    text = "Materials per NACE MR0175 (2015) and pump per API 610."
    assert _edition_near(text, "API 610") is None


def test_the_identifier_not_present_at_all_returns_none():
    assert _edition_near("Some unrelated text.", "API 610") is None
