"""Audit C5: a field is a clause's field only when the clause is ABOUT it.

On the real pump review a field called "Fittings" was answered by a clause about
a package list, "Manufacturer" by a list of references and "Rated power" by a
clause about cut-water clearance: the label stood somewhere inside the clause's
subject and that was enough. The label must stand in the subject's head: no word
that opens a complement may come before it. Invented sentences only.
"""

from __future__ import annotations

import pytest

from app import comparison, pairing_head
from tests.test_match_rules import fact, requirement


@pytest.mark.parametrize(
    ("subject", "label", "named"),
    [
        ("rated power of the motor", "rated power", True),
        ("rated power", "rated power", True),
        ("design pressure for nozzles", "design pressure", True),
        (
            "internal design pressure and maximum operating pressure",
            "maximum operating pressure",
            True,
        ),
        ("maximum and minimum design temperature", "minimum design temperature", True),
        ("degree of protection of the motor", "degree of protection", True),
        # an opening quantity noun + "of" is skipped: the field still pairs
        ("type of enclosure", "enclosure", True),
        ("number of stages", "stages", True),
        ("power of the motor", "motor", True),
        ("type of the cut water for rated power", "rated power", False),
        # the label only appears inside a complement, a list or a condition
        ("cut water clearance for rated power", "rated power", False),
        ("generator package list including fittings", "fittings", False),
        ("references to the manufacturer", "manufacturer", False),
        ("stress in the shell at design temperature", "design temperature", False),
        ("at normal flow the valve", "normal flow", False),
        ("travel when the pump is at rated power", "rated power", False),
        # whole words, as before
        ("redesign pressure", "design pressure", False),
        ("", "rated power", False),
        ("rated power", "", False),
    ],
)
def test_the_label_must_stand_in_the_subjects_head(subject, label, named):
    assert pairing_head.names_head(subject, label) is named


def test_a_numeric_clause_about_something_else_that_mentions_the_label_pairs_nothing():
    req = requirement("cut water clearance for rated power", raw_unit="kW")
    facts = [fact("Rated power", raw_value="55", raw_unit="kW")]
    result = comparison.match_by_containment(req, facts)
    assert result["fact"] is None


def test_the_same_label_as_the_head_still_pairs():
    req = requirement("rated power of the motor", raw_unit="kW")
    facts = [fact("Rated power", raw_value="55", raw_unit="kW")]
    assert comparison.match_by_containment(req, facts)["fact"] is facts[0]


def _statement(subject):
    return {
        "id": "s1",
        "requirement_type": "statement",
        "subject": subject,
        "source_text": f"The {subject} shall be as stated.",
        "requirement_text": f"The {subject} shall be as stated.",
    }


@pytest.mark.parametrize(
    "subject",
    [
        "generator package list including casing material",
        "references to the casing material",
        "cut water clearance for casing material",
    ],
)
def test_a_statement_that_only_mentions_the_field_pairs_nothing(subject):
    facts = [_named("Casing material", "Cast iron")]
    assert comparison.match_statement(_statement(subject), facts)["fact"] is None


def _named(label, value):
    return {
        "id": "f1",
        "field_name": label,
        "field_value": value,
        "raw_value": value,
        "raw_unit": "",
        "is_blank": False,
    }


def test_a_statement_about_the_field_pairs_it():
    facts = [_named("Casing material", "Cast iron")]
    result = comparison.match_statement(
        _statement("casing material of the pump"), facts
    )
    assert result["fact"] is facts[0]


def test_normalised_shapes_pair_through_the_real_route(tmp_path):
    """An article, a hyphen, a leading adjective and a parenthetical stay in the head."""
    cases = [
        ("The Rated-Power of the motor", "Rated power"),
        ("Maximum rated power", "Rated power"),
        ("vessel MAWP (12 barg)", "MAWP"),
        ("Type of enclosure", "Enclosure"),
    ]
    for subject, label in cases:
        req = requirement(subject, raw_unit="kW")
        facts = [fact(label, raw_value="55", raw_unit="kW")]
        assert comparison.match_by_containment(req, facts)["fact"] is facts[0], subject


def test_when_the_rule_empties_the_first_pass_a_later_route_may_pick_another_row():
    """The rule never pairs a label outside the head; when it empties the first
    pass, a LATER route (the closing noun, #913) can pair a different row.
    "Normal flow" no longer claims "At normal flow the valve ..."; the travel row does."""
    from tests.test_913_closing_noun import _fact, _req

    plain, travel = _fact("Normal flow"), _fact("Travel at normal flow")
    result = comparison.match_by_containment(_req(), [plain, travel])
    assert result["fact"] is travel


def test_the_abbreviation_route_obeys_the_same_rule():
    """ "Max operating temp" meets "maximum operating temperature" only when the
    label heads the subject, never inside a complement."""
    facts = [fact("Max operating temp", raw_value="80", raw_unit="C")]
    inside = requirement("clearance for maximum operating temperature", raw_unit="C")
    assert comparison.match_by_containment(inside, facts)["fact"] is None
    heads = requirement("maximum operating temperature of the casing", raw_unit="C")
    assert comparison.match_by_containment(heads, facts)["fact"] is facts[0]


@pytest.mark.parametrize(
    "subject",
    [
        "where the pump is at rated power",
        "when rated power is exceeded",
        "if rated power is stated",
        "per rated power of the driver",
        "in rated power operation",
    ],
)
def test_a_subject_that_opens_with_a_condition_word_pairs_nothing_with_a_label_after_it(
    subject,
):
    """The stated cost of the rule: a label that follows an opening condition word is
    the condition, not what the clause is about; the clause goes to the engineer."""
    req = requirement(subject, raw_unit="kW")
    facts = [fact("Rated power", raw_value="55", raw_unit="kW")]
    assert comparison.match_by_containment(req, facts)["fact"] is None


def test_a_plural_subject_does_not_pair_a_singular_numeric_label():
    """Whole words, as before the rule: "rated powers" is not "rated power"."""
    req = requirement("rated powers of the motors", raw_unit="kW")
    facts = [fact("Rated power", raw_value="55", raw_unit="kW")]
    assert comparison.match_by_containment(req, facts)["fact"] is None


def test_an_opening_quantity_noun_is_loose_by_design():
    """ "power of the motor" pairs the field "Motor": the opening is skipped so that
    "type of enclosure" still pairs "Enclosure". Stated in A-1302."""
    req = requirement("power of the motor", raw_unit="kW")
    facts = [fact("Motor", raw_value="55", raw_unit="kW")]
    assert comparison.match_by_containment(req, facts)["fact"] is facts[0]
