"""Pairing a requirement with a submitted value, deterministically.

WHY CONTAINMENT AND NOT EQUALITY. Measured over 77 numeric requirements from
ten applicable standards and 38 field names from a real submittal: exact
equality matched NOTHING. A requirement's subject is a sentence fragment -
"internal design pressure shall be according to the following table" - and a
field name is the bare noun phrase inside it. Containment found the two pairs
an engineer picked out by hand, and nothing else.

No fuzzy matching, no synonyms, no model. Every rule here is a string test with
a stated reason, because a pairing that cannot be explained produces findings
that cannot be defended.
"""

from __future__ import annotations

import pytest

from app import comparison


def requirement(subject, **over):
    base = {"requirement_type": "numeric_limit", "value": 3.5, "unit": "bar",
            "raw_value": "3.5", "raw_unit": "bar", "subject": subject}
    return {**base, **over}


def fact(field_name, **over):
    base = {"id": f"fact-{field_name}", "field_name": field_name,
            "raw_value": "2.2", "raw_unit": "bar", "unit": "bar"}
    return {**base, **over}


def test_a_field_name_inside_a_subject_is_a_match():
    result = comparison.match_by_containment(
        requirement("the internal design pressure shall be at least"),
        [fact("internal design pressure")])

    assert result["fact"]["id"] == "fact-internal design pressure"
    assert result["matched_phrase"] == "internal design pressure"
    assert result["method"] == "containment"


def test_exact_equality_needs_no_separate_path():
    """A subject that IS the field name is just containment with nothing
    either side. Asserted so nobody adds a second code path for it."""
    result = comparison.match_by_containment(
        requirement("internal design pressure"), [fact("internal design pressure")])

    assert result["matched_phrase"] == "internal design pressure"


def test_a_match_must_fall_on_whole_words():
    """"design pressure" must not match inside "redesign pressure".

    They are different fields. A substring test would file a real number
    against a requirement about something else, and the finding would read
    exactly like a correct one.
    """
    result = comparison.match_by_containment(
        requirement("the redesign pressure shall be at least"),
        [fact("design pressure")])

    assert result["fact"] is None
    # AND THE SAME FACT MATCHES THE HONEST SUBJECT, so this is not passing
    # because containment stopped working.
    assert comparison.match_by_containment(
        requirement("the design pressure shall be at least"),
        [fact("design pressure")])["fact"] is not None


def test_the_longest_field_name_wins():
    """Two fields are named inside one subject; the more specific is meant.

    "internal design pressure" and "design pressure" are both contained in the
    subject, and the requirement is about the first.
    """
    result = comparison.match_by_containment(
        requirement("the internal design pressure shall be at least"),
        [fact("design pressure"), fact("internal design pressure")])

    assert result["matched_phrase"] == "internal design pressure"


def test_a_genuine_tie_returns_no_match_and_names_the_candidates():
    """NEVER PICK ARBITRARILY.

    Two equally specific fields are named in one subject. Choosing one would
    attach a real number to a requirement that may be about the other, and
    nothing on the finding would say it was a guess.
    """
    result = comparison.match_by_containment(
        requirement("the shell thickness and the crown thickness shall exceed"),
        [fact("shell thickness"), fact("crown thickness")])

    assert result["fact"] is None
    assert result["reason"] == comparison.AMBIGUOUS_MATCH
    assert result["candidates"] == ["crown thickness", "shell thickness"]


def test_names_of_different_length_are_not_a_tie():
    """The guard on the rule above: "head thickness" is shorter than "shell
    thickness", so it is resolved by specificity rather than refused. Without
    this the tie test could pass against a matcher that refused every multiple
    match."""
    result = comparison.match_by_containment(
        requirement("the shell thickness and the head thickness shall exceed"),
        [fact("shell thickness"), fact("head thickness")])

    assert result["matched_phrase"] == "shell thickness"


def test_a_categorical_fact_never_matches():
    """THE RULE THAT KILLS THE INSULATION FALSE FRIEND.

    SAES-W-010 clause 13 is about PWHT heating blankets and contains the word
    "insulation"; the submittal has an `insulation` field answered "yes". The
    word is shared and the quantity is not, so there is nothing to compare -
    and a finding pairing a temperature limit with the answer "yes" would be
    nonsense presented with citations.
    """
    result = comparison.match_by_containment(
        requirement("the insulation shall be removed above"),
        [fact("insulation", raw_value=None, unit=None)])

    assert result["fact"] is None


def test_a_requirement_with_no_numeric_value_is_not_matched():
    """A requirement carrying no number has nothing to compare, so pairing it
    could only produce a finding whose verdict is unknowable.

    THE TEST IS ON `raw_value`, NOT `value`. `value` is the NORMALISED number
    and is NULL for every unit `claims` recognises but cannot convert - dB(A)
    among them, which is the product's own worked example. Scoping on it
    silently excluded the flagship comparison while looking like a tightening.
    """
    assert comparison.match_by_containment(
        requirement("the design pressure shall be adequate",
                    raw_value=None, value=None),
        [fact("design pressure")])["fact"] is None


def test_a_requirement_whose_unit_cannot_be_converted_is_still_matched():
    """The guard on the rule above, and the reason it is `raw_value`.

    A dB(A) limit has no normalised value because nothing converts decibels.
    It is still a number, the submitted value is still a number, and two
    values in the same unit compare without any conversion at all.
    """
    result = comparison.match_by_containment(
        requirement("the noise level shall not exceed", value=None,
                    raw_value="90", raw_unit="dB(A)", unit=None),
        [fact("noise level", raw_value="95", raw_unit="dB(A)", unit=None)])

    assert result["matched_phrase"] == "noise level"


def test_a_statement_requirement_is_not_matched():
    assert comparison.match_by_containment(
        requirement("the design pressure shall be stated",
                    requirement_type="statement"),
        [fact("design pressure")])["fact"] is None


def test_a_very_short_field_name_is_not_matched():
    """A one-word fragment is contained in half of everything. "pages" and
    "or rings" are real field names on a real bill of materials, and matching
    them would pair a moment limit with a drawing index row."""
    assert comparison.match_by_containment(
        requirement("the vessel shall have at least"), [fact("of")])["fact"] is None


def test_punctuation_and_case_do_not_prevent_a_match():
    """Both sides are folded the same way; that is the only reason comparing
    them means anything."""
    result = comparison.match_by_containment(
        requirement("The Internal Design Pressure, per 6.2, shall be at least"),
        [fact("internal design pressure")])

    assert result["matched_phrase"] == "internal design pressure"


def test_the_requirement_field_column_is_never_written():
    """`standard_requirements.field` STAYS NULL.

    The pairing is a property of one comparison, not of the requirement, and a
    populated `field` would make the column read as a usable join key when the
    measured exact-match rate against it is zero. Nothing in the matcher writes
    it, and this asserts the function returns its result rather than storing
    one.
    """
    req = requirement("the internal design pressure shall be at least")
    comparison.match_by_containment(req, [fact("internal design pressure")])

    assert req.get("field") is None
