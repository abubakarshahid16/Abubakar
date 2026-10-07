"""A top-level heading written on one line ("4 Vibration") is a heading
(CHUNKER_VERSION 11, found by the P1 question set).

It used to be refused, so it stayed on the END of the previous clause and a
question about vibration found that clause instead of the one under the
heading. Invented text only.
"""
from __future__ import annotations

from app import chunker as ch

_PAGE = "\n".join([
    "1 Scope",
    "1.1 This standard covers centrifugal pumps in continuous service.",
    "3 Inspection",
    "3.1 Each pump shall be inspected at intervals not exceeding 4000 operating hours.",
    "3.2 Any exceedance shall be reported to the area engineer before the pump is returned to service.",
    "4 Vibration",
    "4.1 Vibration measured at the bearing housing shall not exceed 3.0 mm/s RMS.",
    "4.2 Readings shall be taken monthly.",
])


def test_a_one_line_top_level_heading_is_a_heading():
    assert ch._split_line_heading(["4 Vibration"], 0) == ("4 Vibration", 1)
    assert ch._split_line_heading(["6 Heat treatment"], 0) == ("6 Heat treatment", 1)


def test_a_numbered_sentence_is_not_a_one_line_heading():
    # a footnote / list item, not a clause title: it ends like a sentence
    assert ch._split_line_heading(["1 Acceptance criteria are considered acceptable."], 0)[0] is None
    # opens a clause sentence
    assert ch._split_line_heading(
        ["2 When the vessel is heat treated, the marking must be recognisable"], 0)[0] is None
    # a plain number and a unit is data, not a heading
    assert ch._split_line_heading(["4 mm"], 0)[0] is None


def test_the_heading_goes_with_its_own_clause_not_the_clause_before():
    blocks, _ = ch.segment_document([(1, _PAGE)], set())
    before = next(b for b in blocks if b.text.startswith("3.2 "))
    assert "Vibration" not in before.text, before.text
    own = next(b for b in blocks if "bearing housing" in b.text)
    assert "4 Vibration" in own.text or (own.section or "").startswith("4"), (
        own.text, own.section)
