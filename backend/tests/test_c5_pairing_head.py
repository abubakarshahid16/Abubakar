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
    ["generator package list including fittings", "references to the manufacturer"],
)
def test_a_statement_that_only_mentions_the_field_pairs_nothing(subject):
    label = "Fittings" if "fittings" in subject else "Manufacturer"
    facts = [
        {
            "id": "f1",
            "field_name": label,
            "field_value": "Stainless steel",
            "raw_value": "Stainless steel",
            "raw_unit": "",
            "is_blank": False,
        }
    ]
    assert comparison.match_statement(_statement(subject), facts)["fact"] is None


def test_a_statement_about_the_field_pairs_it():
    facts = [
        {
            "id": "f1",
            "field_name": "Manufacturer",
            "field_value": "Acme Pumps",
            "raw_value": "Acme Pumps",
            "raw_unit": "",
            "is_blank": False,
        }
    ]
    assert (
        comparison.match_statement(_statement("manufacturer of the pump"), facts)[
            "fact"
        ]
        is facts[0]
    )
