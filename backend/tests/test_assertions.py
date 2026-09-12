"""Compliance assertions: caught when invented, silent when merely reworded.

The second half is the hard half. A check that fires on honest paraphrase gets
switched off within a week, so most of these tests assert SILENCE - and the
fixtures are the real sentences from doc16.pdf p.16 and NORSOKM501Rev5.pdf p.9,
not invented ones that could not produce the condition.
"""

from __future__ import annotations

import pytest

from app import assertions

# The measured defect. doc16.pdf p.16, and the summary produced from it.
SOURCE_P16 = (
    "This data is provided at the start of a project and contains only data "
    "that has been through the quality control process."
)
SUMMARY_P16 = (
    "This approach provides designers with a starting point that contains "
    "only quality-controlled data compliant with relevant standards."
)

# NORSOKM501Rev5.pdf p.9, and an honest rewording of it.
SOURCE_P9 = (
    "Minimum coating thickness for structural items and outfitting steel "
    "shall be 125 um and 900 g/m2."
)


def test_the_measured_defect_is_caught():
    """"compliant with relevant standards" over a source that says only that
    data went through a quality control process. The citation resolved to a
    real page, so every existing check passed it."""
    assert assertions.unsupported(SUMMARY_P16, SOURCE_P16) == frozenset({"conformance"})


def test_an_honest_rewording_is_silent():
    """"specifies" for "shall be" is the same claim. A check that fires here
    deletes the summaries this product exists to produce."""
    reworded = "Minimum coating thickness for structural steel shall be 125 um."
    assert assertions.unsupported(reworded, SOURCE_P9) == frozenset()


def test_accordance_in_the_source_supports_conforms_in_the_summary():
    """Same family, different words. Splitting these would fire on prose that
    is doing exactly what a summary should do."""
    assert assertions.unsupported(
        "The primer conforms to ISO 12944.",
        "The primer shall be in accordance with ISO 12944.",
    ) == frozenset()


def test_a_sentence_asserting_nothing_is_silent():
    """Most summary sentences assert no compliance at all. They must pass
    untouched, or this module becomes a filter on ordinary prose."""
    assert assertions.unsupported(
        "The workflow begins with cells and modules.",
        "The model workflow begins with pre-defined data known as cells and modules.",
    ) == frozenset()


def test_an_invented_approval_is_caught():
    assert "approval" in assertions.unsupported(
        "The system is approved for splash zones.",
        "The system may be selected for splash zones.",
    )


def test_a_prohibition_is_not_read_as_an_obligation():
    """"shall not" CONTAINS "shall". Reporting a prohibition as an obligation
    inverts the claim, which is the worst way to be wrong about a spec."""
    assert assertions.families("Stainless steel shall not be coated.") == frozenset(
        {"prohibition"}
    )
    assert "obligation" not in assertions.families("It shall not be coated.")


def test_an_invented_prohibition_is_caught():
    assert "prohibition" in assertions.unsupported(
        "Stainless steel shall not be coated.",
        "Stainless steel shall be coated 50 mm beyond the weld zone.",
    )


def test_evidence_asserting_more_than_the_sentence_is_not_a_defect():
    """The direction matters. A source that says more than the summary is
    normal; only the reverse is invention."""
    assert assertions.unsupported(
        "The thickness is 125 um.",
        "Coating thickness shall comply with ISO 1461 and be 125 um.",
    ) == frozenset()


@pytest.mark.parametrize("family", sorted(assertions.REASONS))
def test_every_family_has_a_reason_a_reader_can_act_on(family):
    """"unsupported assertion" is not a sentence anyone can do anything with."""
    text = assertions.reason(family)
    assert len(text) > 20 and "cited span" in text


def test_the_fixture_can_actually_produce_the_condition():
    """Standing rule 14, applied to this file. The defect fixture must contain
    the language it is testing for - a fixture that cannot produce the
    condition proves nothing, and this project has five recorded instances of
    exactly that."""
    assert "complian" in SUMMARY_P16.lower()
    assert "complian" not in SOURCE_P16.lower()
    assert "conform" not in SOURCE_P16.lower()
