"""Order 298.2 (I-06 hand check, CRS-015): "API RP 520 Pt-1&2" cites Parts 1 AND 2. The CRS said the contractor
did not reference Part II. Invented citations only."""

from __future__ import annotations

import pytest

from app import applicability, datasheets, standard_ids


def _cites(text: str, wanted: str) -> bool:
    return applicability._cited_by(datasheets.referenced_standards(text), wanted)


@pytest.mark.parametrize(
    "text",
    [
        "Design Standard: API RP 520 Pt-1&2, KOC-MP-027 Pt. 1&2",
        "API RP 520 Part 1 and 2",
        "API 520 Part I & II",
        "API RP 520 Pt.1/2",
        "API 520 Part 1 & 2 & 3",
    ],
)
def test_a_citation_naming_several_parts_cites_each_of_them(text):
    assert _cites(text, "API 520 Part II") and _cites(text, "API 520 Part 1")


@pytest.mark.parametrize(
    ("text", "wanted"),
    [
        (
            "API RP 520 Pt-1",
            "API 520 Part II",
        ),  # one part named: the other is not cited
        ("API RP 520 Pt-1&2", "API 520 Part III"),  # a part not in the list
        (
            "API 520 Part 1 and a note",
            "API 520 Part 2",
        ),  # a word after "and" is not a part
        ("API RP 521 Pt-1&2", "API 520 Part II"),  # another standard
    ],
)
def test_what_is_not_named_is_not_cited(text, wanted):
    assert not _cites(text, wanted)


@pytest.mark.parametrize(
    "text",
    [
        "API 520 Part 1 and 2 valves shall be supplied by the vendor.",
        "API 520 Part 1 and 2 units are supplied.",
        "per API 610 Part 1 and 5 pumps",
        "Per API 520 Part 1 and 3 bar max",
        "API 520 Part 1 / 2 mm",
    ],
)
def test_a_number_that_counts_things_after_a_part_is_not_a_second_part(text):
    """cloud-3 on #1432: a count noun after the number makes it a quantity; 'Part 1 and 2 shall apply' still cites both."""
    assert len(standard_ids.cited_standards(text)) == 1
    assert len(standard_ids.cited_standards("API 520 Part 1 and 2 shall apply.")) == 2


def test_a_quantity_after_a_citation_is_not_a_part():
    assert standard_ids.cited_standards(
        "API 610, 2 units supplied; API 682 & 2 spares"
    ) == ["API 610", "API 682"]
    assert standard_ids.cited_standards("API 520 Part 1, 2 are noted") == [
        "API 520 Part 1"
    ]
    assert standard_ids.cited_standards("API 520 Part 1, 2 units supplied") == [
        "API 520 Part 1"
    ]


def test_each_part_is_its_own_entry_and_other_citations_are_unchanged():
    assert standard_ids.cited_standards("API RP 520 Pt-1&2, API 526") == [
        "API RP 520 Pt-1",
        "API RP 520 Pt-2",
        "API 526",
    ]
    assert standard_ids.cited_standards("API 610 and API 682") == ["API 610", "API 682"]
