# ruff: noqa: F811 - pytest fixtures imported by name
"""Owner order 3 Nov 2026: a requirement pairs with a datasheet field only if its SUBJECT is the same quantity.

The live review of a specification paired a maximum coating thickness with the sheet's corrosion allowance and an acrylic
window's design life with the vessel's design life. Invented numbers and wording only. Off by default.
"""

from __future__ import annotations

import pytest

from app import comparison, match_rules
from app import subject_pairing as sp
from app.config import settings
from tests.test_same_kind_pairing import (  # noqa: F401 - the fixture and helpers
    _limit,
    _review,
    world,
)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "pairing_subject_gate_enabled", True)


def req(subject, **over):
    base = {
        "requirement_type": "numeric_limit",
        "value": 0.05,
        "unit": "mm",
        "raw_value": "0.05",
        "raw_unit": "mm",
        "subject": subject,
        "requirement_text": f"{subject} shall not exceed 0.05 mm",
    }
    return {**base, **over}


def fact(name, **over):
    base = {
        "id": f"fact-{name}",
        "field_name": name,
        "raw_value": "2.4",
        "raw_unit": "mm",
        "unit": "mm",
    }
    return {**base, **over}


def test_it_is_off_by_default():
    assert settings.pairing_subject_gate_enabled is False
    assert (
        sp.conflict(req("maximum coating thickness"), fact("corrosion allowance"))
        is None
    )


def test_a_coating_thickness_is_not_the_corrosion_allowance(on):
    assert (
        sp.conflict(req("The maximum coating thickness"), fact("Corrosion allowance"))
        == sp.SUBJECT_DIFFERS
    )
    assert (
        match_rules.refusal(
            req("The maximum coating thickness"),
            fact("Corrosion allowance"),
            sheet=None,
        )
        == match_rules.SUBJECT_QUANTITY
    )


def test_the_design_life_of_a_window_is_not_the_sheets_design_life(on):
    window = req("(9) The design life of the acrylic window", raw_unit="yr", unit="yr")
    assert (
        sp.conflict(window, fact("Design life", raw_unit="years")) == sp.SUBJECT_DIFFERS
    )


def test_mawp_is_not_the_design_pressure_and_an_unrelated_clause_is_not_a_temperature(
    on,
):
    assert (
        sp.conflict(
            req("(3) The maximum allowable working pressure (MAWP)"),
            fact("Design pressure"),
        )
        == sp.SUBJECT_DIFFERS
    )
    assert (
        sp.conflict(req("the weld bead width"), fact("Design temperature"))
        == sp.SUBJECT_DIFFERS
    )


@pytest.mark.parametrize(
    "subject, label",
    [
        ("design pressure", "Design pressure"),
        (
            "The maximum design temperature",
            "Design temperature",
        ),  # which bound is another rule's question
        (
            "the design pressure of the heat exchanger",
            "Design pressure",
        ),  # the sheet's own equipment is not a different object
        (
            "Corrosion allowance",
            "corrosion allowance (T-7001/QA)",
        ),  # a tag is not part of the quantity
        ("Corrosion allowance", "corrosion allowance (P-101AB)"),
    ],
)
def test_the_same_quantity_still_pairs(on, subject, label):
    assert sp.conflict(req(subject), fact(label), "heat exchanger") is None


def test_a_requirement_with_no_subject_is_refused_not_paired_by_the_words_of_its_sentence(
    on,
):
    assert (
        sp.conflict(
            req(None, requirement_text="the corrosion allowance shall be 3 mm"),
            fact("Corrosion allowance"),
        )
        == sp.SUBJECT_UNKNOWN
    )
    assert sp.conflict(req(""), fact("Design pressure")) == sp.SUBJECT_UNKNOWN


def test_a_field_with_no_words_to_compare_is_left_alone(on):
    assert sp.conflict(req("design pressure"), fact("")) is None
    assert sp.conflict(req("design pressure"), fact("(7001-12)")) is None


def _the_model_proposes(monkeypatch, field):
    monkeypatch.setattr(settings, "match_enabled", True)
    monkeypatch.setattr(settings, "match_ask_max_per_run", 0)

    def proposed(requirement, facts, **_kw):
        [fact] = [f for f in facts if f["field_name"] == field]
        return {
            "fact": fact,
            "matched_phrase": field,
            "method": comparison.METHOD_MODEL_CHOICE,
            "reason": "a coating thickness is a kind of corrosion allowance",
            "candidates": [],
        }

    monkeypatch.setattr(comparison, "match_by_model", proposed)


def test_the_ai_matchers_pair_of_a_coating_thickness_with_the_corrosion_allowance_is_refused(
    world, monkeypatch, on
):
    _the_model_proposes(monkeypatch, "corrosion allowance")
    _row, [_fact_row], found = _review(
        "The maximum coating thickness shall not exceed 0.07 mm.",
        _limit("the maximum coating thickness", "0.07", "mm"),
        [("Corrosion allowance", "2.4 mm", None)],
    )
    assert found["fact_id"] is None  # never paired: no value of the sheet is compared
    assert found["compliance_status"] not in (
        comparison.COMPLIANT,
        comparison.NON_COMPLIANT,
    )
    assert match_rules.SUBJECT_QUANTITY in found["ai_rationale"]


def test_the_same_pair_is_made_with_the_switch_off(world, monkeypatch):
    monkeypatch.setattr(settings, "pairing_subject_gate_enabled", False)
    _the_model_proposes(monkeypatch, "corrosion allowance")
    _row, [fact], found = _review(
        "The maximum coating thickness shall not exceed 0.07 mm.",
        _limit("the maximum coating thickness", "0.07", "mm"),
        [("Corrosion allowance", "2.4 mm", None)],
    )
    assert (
        found["fact_id"] == fact["id"]
        and comparison.MODEL_PAIR_PREFIX in found["ai_rationale"]
    )


def test_an_acrylic_window_life_is_not_paired_with_the_design_life(
    world, monkeypatch, on
):
    _the_model_proposes(monkeypatch, "design life")
    _row, [_fact_row], found = _review(
        "The design life of the acrylic window shall be 8 yr from the date of fabrication.",
        _limit("the design life of the acrylic window", "8", "yr", "=="),
        [("Design life", "30 years", None)],
    )
    assert found["fact_id"] is None
    assert match_rules.SUBJECT_QUANTITY in found["ai_rationale"]


def test_a_same_quantity_pair_still_pairs_and_decides(world, on):
    _row, [fact], found = _review(
        "The corrosion allowance shall not exceed 6 mm.",
        _limit("the corrosion allowance", "6", "mm"),
        [("Corrosion allowance", "2.4 mm", None)],
    )
    assert (
        found["fact_id"] == fact["id"]
        and found["compliance_status"] == comparison.COMPLIANT
    )
