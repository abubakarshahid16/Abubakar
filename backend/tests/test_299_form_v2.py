"""Order 299.1: the relief-valve form v2. The converter compares a rule only to a box of the type's form; v2 adds the
quantities the public relief-valve standards name, as data. Invented text and names only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app import field_links, form_reader_fields, rule_roles, standards_converter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_form_v2_names

PSV = "Pressure Safety Valve"


def _own_numeric_boxes(equipment_type: str) -> set[str]:
    out = set()
    for f in form_reader_fields.field_list_for(equipment_type):
        wanted = rule_roles._ROLE_FAMILIES.get(f.key) or rule_roles._KIND_FAMILIES.get(
            f.unit_kind or ""
        )
        if wanted:
            out.add(field_links.canonical(f.key.replace("_", " ")))
    return out


def _form_with(monkeypatch, tmp_path, boxes):
    (tmp_path / "pressure_safety_valve.json").write_text(
        json.dumps({"equipment_type": PSV, "boxes": boxes}), encoding="utf-8"
    )
    monkeypatch.setattr(rule_roles, "FORM_V2_DIR", tmp_path)


def test_form_v2_adds_boxes_and_never_cuts_or_renames_the_types_own():
    dictionary, roles, families = rule_roles.form(PSV)
    own = _own_numeric_boxes(PSV)
    extra = {field_links.canonical(b["name"]) for b in rule_roles.extra_boxes(PSV)}
    assert own and extra
    assert set(dictionary) == own | extra
    assert not own & extra
    for name in own:
        assert roles[name] == name.replace(" ", "_") or roles[name] in {
            f.key for f in form_reader_fields.field_list_for(PSV)
        }
    assert all(families[name] for name in dictionary)


def test_every_box_has_a_unique_name_and_a_checkable_unit_family():
    boxes = rule_roles.extra_boxes(PSV)
    names = [field_links.canonical(b["name"]) for b in boxes]
    assert len(names) == len(set(names))
    assert all(b["unit_kind"] in rule_roles._KIND_FAMILIES for b in boxes)


def test_a_type_without_a_form_v2_file_has_its_own_boxes_only():
    dictionary, _roles, _families = rule_roles.form("Pump")
    assert set(dictionary) == _own_numeric_boxes("Pump")
    assert rule_roles.extra_boxes("Pump") == []
    assert rule_roles.extra_boxes("some unknown machine") == []


def test_a_box_with_no_checkable_unit_kind_is_an_error_not_a_silent_box(
    monkeypatch, tmp_path
):
    _form_with(
        monkeypatch, tmp_path, [{"name": "ratio of things", "unit_kind": "text"}]
    )
    with pytest.raises(ValueError, match="no checkable unit kind"):
        rule_roles.form(PSV)


def test_a_box_listed_twice_or_already_on_the_form_is_an_error(monkeypatch, tmp_path):
    twice = {"name": "relieving pressure", "unit_kind": "pressure"}
    _form_with(monkeypatch, tmp_path, [twice, twice])
    with pytest.raises(ValueError, match="listed twice"):
        rule_roles.form(PSV)
    _form_with(
        monkeypatch, tmp_path, [{"name": "set pressure", "unit_kind": "pressure"}]
    )
    with pytest.raises(ValueError, match="already a box"):
        rule_roles.form(PSV)


def _verdict(sentence, quote, limit, unit, field):
    dictionary, roles, families = rule_roles.form(PSV)
    answer = {
        "condition": None,
        "field": dictionary.index(field),
        "comparator": "<=",
        "limit": limit,
        "unit": unit,
        "quote": quote,
    }
    row = {
        "requirement_text": sentence,
        "clause": "4.2",
        "requirement_type": "statement",
    }
    return standards_converter.verify(answer, row, dictionary, roles, families)


def test_a_rule_that_names_an_added_box_is_a_check_with_its_unit_kind_proven():
    sentence = "The accumulation shall not exceed 10 %."
    status, reason, check = _verdict(
        sentence, "accumulation shall not exceed 10 %", "10", "%", "accumulation"
    )
    assert (status, reason) == ("verified", None)
    assert check.field == "accumulation"


def test_an_added_box_refuses_a_unit_of_the_wrong_kind():
    sentence = "The accumulation shall not exceed 10 bar."
    status, reason, _check = _verdict(
        sentence, "accumulation shall not exceed 10 bar", "10", "bar", "accumulation"
    )
    assert status == "unproven"
    assert reason == "unit_not_of_field"


def test_no_added_box_name_is_a_shorter_run_of_another_boxes_name():
    """The quote gate looks at the quote, not the words before it ("casing design pressure" is a "design pressure"
    by design), so an ADDED box whose words sit inside another box's name would take that box's rules whenever the
    model cut the quote short. (A longer added name around an existing box is fine: it only gives the model a
    better box.)"""
    dictionary, _roles, _families = rule_roles.form(PSV)
    added = [field_links.canonical(b["name"]) for b in rule_roles.extra_boxes(PSV)]
    for short in added:
        for long_ in dictionary:
            if short != long_:
                words, run = long_.split(), short.split()
                inside = any(
                    words[i : i + len(run)] == run
                    for i in range(len(words) - len(run) + 1)
                )
                assert not inside, (short, long_)


def test_the_names_checker_counts_one_box_none_and_several_and_prints_no_name(
    tmp_path, capsys
):
    csv_path = tmp_path / "names.csv"
    csv_path.write_text(
        "field name,unit family\n"
        "Accumulation,percent\n"
        "Set Pressure,pressure\n"
        "Invented Gizmo Rating,pressure\n"
        "Invented Gizmo Colour,\n",
        encoding="utf-8",
    )
    check_form_v2_names.main(
        [str(csv_path), "--type", PSV, "--unit-column", "unit family"]
    )
    out = capsys.readouterr().out
    assert "names: 4" in out
    assert "one_box: 2" in out
    assert "no_box: 2" in out
    assert "no_box_with_unit_family: 1" in out
    assert "Gizmo" not in out
    check_form_v2_names.main([str(csv_path), "--type", PSV, "--show-unmapped"])
    assert "unmapped: Invented Gizmo Rating" in capsys.readouterr().out


def test_the_names_checker_reports_a_name_two_boxes_claim_as_several(monkeypatch):
    monkeypatch.setattr(
        check_form_v2_names,
        "box_spellings",
        lambda _t: {
            "alpha pressure": {"alpha pressure", "shared"},
            "beta pressure": {"beta pressure", "shared"},
        },
    )
    mapping = check_form_v2_names.map_names(
        ["Shared", "Alpha Pressure", "Nothing"], PSV
    )
    assert mapping == {
        "Shared": ["alpha pressure", "beta pressure"],
        "Alpha Pressure": ["alpha pressure"],
        "Nothing": [],
    }
    assert check_form_v2_names.counts(mapping) | {} == {
        "names": 3,
        "one_box": 1,
        "no_box": 1,
        "several_boxes": 1,
        "no_box_with_unit_family": 0,
    }
