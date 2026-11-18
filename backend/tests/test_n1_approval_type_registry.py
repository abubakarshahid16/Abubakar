"""An approval's equipment type and the type a review asks with are compared through the ONE registry of equipment names
(`reference/equipment_vocabulary.json`, `subject_scope.equipment_key`), not by spelling. The live fault (16 Nov 2026): the one
owner approval was typed "Pressure Safety Valve", the AI reviewer asks with "relief valve" (the same type, two registered names),
so the approval never reached a review. No database, no model: the approval rows are replaced by a list."""

from __future__ import annotations

import pytest

from app import compiled_rule_report, rule_labels, subject_scope


def _rows(monkeypatch, *rows):
    monkeypatch.setattr(
        compiled_rule_report, "book_approval_rows", lambda _c, _v: list(rows)
    )


def _tier(equipment_type):
    return rule_labels._person_decisions(None, "v1", equipment_type)


@pytest.mark.parametrize(
    "asked",
    [
        "relief valve",
        "Relief  Valve",
        "PSV",
        "pressure safety valve",
        "safety relief valves",
        "pressure relief valve",
    ],
)
def test_an_approval_for_a_type_applies_to_a_review_of_the_same_type_under_any_registered_name(
    monkeypatch, asked
):
    _rows(monkeypatch, ("approve", "Pressure Safety Valve", "owner"))
    assert _tier(asked) == ("owner", False)


@pytest.mark.parametrize(
    "asked", ["control valve", "check valve", "pump", "steam turbine"]
)
def test_an_approval_does_not_apply_to_a_different_registered_type(monkeypatch, asked):
    _rows(monkeypatch, ("approve", "Pressure Safety Valve", "owner"))
    assert _tier(asked) == (None, False)


@pytest.mark.parametrize("asked", ["gizmo", "valve", "turbine"])
def test_an_unregistered_or_ambiguous_name_matches_no_registered_type_fail_closed(
    monkeypatch, asked
):
    _rows(monkeypatch, ("approve", "Pressure Safety Valve", "owner"))
    assert _tier(asked) == (None, False)


def test_an_approval_typed_with_an_unregistered_or_ambiguous_name_reaches_no_registered_type(
    monkeypatch,
):
    for typed in ("gizmo", "valve"):
        _rows(monkeypatch, ("approve", typed, "owner"))
        assert _tier("relief valve") == (None, False)
        assert _tier(typed) == (
            "owner",
            False,
        )  # the same spelling still matches itself, as before


def test_a_later_refusal_under_another_name_of_the_same_type_ends_the_approval(
    monkeypatch,
):
    _rows(
        monkeypatch,
        ("approve", "Pressure Safety Valve", "owner"),
        ("reject", "PSV", None),
    )
    assert _tier("relief valve") == (None, True)


def test_a_refusal_for_another_type_leaves_the_approval_standing(monkeypatch):
    _rows(
        monkeypatch,
        ("approve", "Pressure Safety Valve", "owner"),
        ("reject", "pump", None),
    )
    assert _tier("relief valve") == ("owner", False)


def test_a_review_that_names_no_type_still_reads_every_standing_approval(monkeypatch):
    _rows(monkeypatch, ("approve", "Pressure Safety Valve", "engineer"))
    assert _tier(None) == ("engineer", False)


def test_the_registry_key_is_one_type_or_none():
    assert (
        subject_scope.equipment_key("PSV")
        == subject_scope.equipment_key("Pressure Safety Valve")
        == "relief valve"
    )
    assert subject_scope.equipment_key("valve") is None  # listed under several types
    assert subject_scope.equipment_key("gizmo") is None
    assert subject_scope.equipment_key("") is None
