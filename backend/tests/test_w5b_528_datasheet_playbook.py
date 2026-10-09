"""#528 (W5b-04): the datasheet review playbook is a data file.

`reference/datasheet_playbook.json` holds what used to be literals in
`rule_eval.KNOWN_RULES` and `field_links` (flange classes, radiography levels,
family fields). Regression: the data equals the literals it replaced, so the
review's results are today's. Editing the file changes the review. A missing
or broken file raises a named error; it never runs empty. Invented text only.

Mutations: M5801-M5808 (scripts/mutations/w5b_528_datasheet_playbook.py).
"""
from __future__ import annotations

import copy
import importlib
import json

import pytest

from app import datasheet_playbook as dp, field_links, rule_eval

#: The literals as they were in code before #528 - the regression baseline.
BEFORE_KNOWN_RULES = (
    {"output": "design pressure",
     "input_names": ["mop", "maximum operating pressure", "max operating pressure",
                     "operating pressure"],
     "requirement_words": ("design pressure",)},
    {"output": "design temperature",
     "input_names": ["mot", "maximum operating temperature", "max operating temperature",
                     "operating temperature"],
     "requirement_words": ("design temperature",)},
)
BEFORE_CLASSES = (150, 300, 400, 600, 900, 1500, 2500)
BEFORE_RT_LEVELS = {"none": 0, "nil": 0, "no": 0, "spot": 1, "partial": 1, "random": 1,
                    "full": 2, "100%": 2, "100 %": 2}
BEFORE_FAMILY_FIELDS = {"flange_rating": frozenset({"flange rating"}),
                        "radiography": frozenset({"radiography"}), "pwht": frozenset({"pwht"})}


def _data() -> dict:
    return json.loads(dp.PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ regression


def test_the_data_file_equals_the_code_it_replaced():
    """Results equal today's: the review reads exactly the old values."""
    assert rule_eval.KNOWN_RULES == BEFORE_KNOWN_RULES
    assert field_links._CLASSES == BEFORE_CLASSES
    assert field_links._RT_LEVELS == BEFORE_RT_LEVELS
    assert field_links.FAMILY_FIELDS == BEFORE_FAMILY_FIELDS


def test_the_review_modules_read_the_data_file_not_a_copy():
    assert rule_eval.KNOWN_RULES is dp.PLAYBOOK["derivation_rules"]
    assert field_links.FAMILY_FIELDS is dp.PLAYBOOK["family_fields"]
    assert field_links._RT_LEVELS is dp.PLAYBOOK["radiography_levels"]


def test_every_class_in_the_data_is_read_in_text():
    for cls in BEFORE_CLASSES:
        rule = field_links.categorical_requirement(f"minimum pressure rating of Class {cls}")
        assert rule is not None and rule["value"] == cls, cls


def test_a_requirement_is_matched_to_its_derivation_rule():
    found = rule_eval.known_rule_for({"requirement_text": "The design temperature shall be MOT plus 25."})
    assert found is not None and found["output"] == "design temperature"


# ------------------------------------------------------------------ editing the file


@pytest.fixture
def edited(tmp_path, monkeypatch):
    """Point the playbook at an edited copy and re-import the review modules;
    restore the shipped file afterwards."""
    def apply(change):
        data = _data()
        change(data)
        path = tmp_path / "datasheet_playbook.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(dp, "PATH", path)
        dp.PLAYBOOK = dp.load()
        importlib.reload(field_links)
        importlib.reload(rule_eval)
    yield apply
    monkeypatch.undo()
    dp.PLAYBOOK = dp.load()
    importlib.reload(field_links)
    importlib.reload(rule_eval)


def test_an_engineer_edit_to_the_file_changes_the_review(edited):
    def change(data):
        data["categorical"]["flange_classes"].append(4500)
        data["derivation_rules"][0]["requirement_words"].append("pressure design basis")
    edited(change)
    rule = field_links.categorical_requirement("minimum pressure rating of Class 4500")
    assert rule is not None and rule["value"] == 4500
    found = rule_eval.known_rule_for({"requirement_text": "the pressure design basis is MOP plus 10 %"})
    assert found is not None and found["output"] == "design pressure"


def test_the_shipped_file_is_restored_after_an_edit():
    assert field_links.categorical_requirement("minimum pressure rating of Class 4500") is None
    assert rule_eval.KNOWN_RULES == BEFORE_KNOWN_RULES


# ------------------------------------------------------------------ never silent


def test_a_missing_file_is_a_named_error(tmp_path):
    with pytest.raises(dp.DatasheetPlaybookError, match="missing"):
        dp.load(tmp_path / "nope.json")


def test_a_file_that_is_not_json_is_a_named_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(dp.DatasheetPlaybookError, match="cannot be read"):
        dp.load(bad)


@pytest.mark.parametrize("change, message", [
    (lambda d: d.update(format="other/1"), "format"),
    (lambda d: d.update(derivation_rules=[]), "derivation_rules"),
    (lambda d: d["derivation_rules"][0].update(output=" "), "no output"),
    (lambda d: d["derivation_rules"][0].update(input_names=[]), "input_names"),
    (lambda d: d["derivation_rules"][1].update(requirement_words=["design temperature", ""]), "requirement_words"),
    (lambda d: d["categorical"].update(flange_classes=[150, "300"]), "flange_classes"),
    (lambda d: d["categorical"].update(flange_classes=[True]), "flange_classes"),
    (lambda d: d["categorical"].update(radiography_levels={"full": "2"}), "radiography_levels"),
    (lambda d: d["categorical"].update(family_fields={}), "family_fields"),
    (lambda d: d["categorical"]["family_fields"].update(pwht=[]), "family_fields.pwht"),
    (lambda d: d.pop("categorical"), "categorical"),
])
def test_a_wrong_shape_is_refused_by_name(change, message):
    data = copy.deepcopy(_data())
    change(data)
    with pytest.raises(dp.DatasheetPlaybookError, match=message):
        dp.parse(data)
