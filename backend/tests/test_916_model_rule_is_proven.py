"""#916 (PF2): a model-parsed table rule is kept only when its numbers, its
unit and each row's max / min are proven by the text; the direction is data of
the known rule, not a literal in the parser; a row with no terms is no verdict.

Invented sentences only; the model is a fake, no socket.
"""
from __future__ import annotations

import json

import pytest

from app import reasoning_provider as rp
from app import rule_eval
from app.config import settings
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse

TABLE = "Design pressure: up to 1,800 kPa add 170 kPa to MOP."
REAL_TABLE = ("Design pressure per table.\nMaximum operating pressure (MOP) | Design pressure\n"
              "Up to 1,800 kPa | MOP + 170 kPa")
TABLE_MAX = "Design pressure: up to 1,800 kPa the greater of MOP + 170 kPa or MOP."


class _FakeModel:
    def __init__(self, body):
        self.body = body

    def reason(self, packet):
        return rp.Response(text=json.dumps(self.body), provider=rp.CLAUDE, model_tag="fake", digest="d",
                           finish_reason="stop", prompt_sha256=packet.sha256)


def _req(text):
    return {"id": None, "requirement_text": text, "source_text": text, "chunk_id": None,
            "standard_document_id": None}


def _row(op="single", terms=None, to=1800):
    return {"from": None, "to": to, "op": op, "terms": terms if terms is not None else [{"k": 1, "c": 170}]}


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setattr(settings, "rule_parse_model_enabled", True)


def test_a_unit_the_text_does_not_say_is_refused():
    """The numbers are on the page; the unit is not (psi for kPa)."""
    wrong = _FakeModel({"unit": "psi", "rows": [_row()]})
    assert rule_eval.rule_for(_req(TABLE), provider=wrong)[0] is None
    right = _FakeModel({"unit": "kPa", "rows": [_row()]})
    assert rule_eval.rule_for(_req(TABLE), provider=right)[0] is not None


def test_a_max_or_min_the_text_does_not_say_is_refused():
    """"greater of" is not in this text, so a model's `max` row is an invention."""
    invented = _FakeModel({"unit": "kPa", "rows": [_row(op="max", terms=[{"k": 1, "c": 170}, {"k": 1}])]})
    assert rule_eval.rule_for(_req(TABLE), provider=invented)[0] is None


def test_a_min_where_the_text_says_greater_is_refused_and_a_max_is_kept():
    terms = [{"k": 1, "c": 170}, {"k": 1}]
    assert rule_eval.rule_for(_req(TABLE_MAX), provider=_FakeModel({"unit": "kPa", "rows": [_row("max", terms)]}))[0] is not None
    assert rule_eval.rule_for(_req(TABLE_MAX), provider=_FakeModel({"unit": "kPa", "rows": [_row("min", terms)]}))[0] is None


def test_a_single_row_with_several_terms_is_refused():
    two = _FakeModel({"unit": "kPa", "rows": [_row(terms=[{"k": 1, "c": 170}, {"k": 0, "c": 1800}])]})
    assert rule_eval.rule_for(_req(TABLE), provider=two)[0] is None


def test_the_direction_comes_from_the_known_rule_not_the_parser(monkeypatch):
    known = rule_eval.known_rule_for(_req(TABLE))
    assert known["comparator"] == ">="
    rule = rule_eval.parse_rule(REAL_TABLE, output=known["output"], input_names=known["input_names"],
                                comparator="<=")
    assert rule["comparator"] == "<="
    assert rule_eval.parse_rule(REAL_TABLE, output=known["output"], input_names=known["input_names"])["comparator"] == ">="


def test_a_row_with_no_terms_gives_no_verdict_not_a_crash():
    rule = {"output": "design pressure", "input": "mop", "input_names": ["mop"], "unit": "kPa",
            "comparator": ">=", "rows": [{"from": None, "to": 1800, "op": "single"}]}
    assert rule_eval.required_for(rule, 1000) is None
    rule["rows"][0]["terms"] = []
    assert rule_eval.required_for(rule, 1000) is None
