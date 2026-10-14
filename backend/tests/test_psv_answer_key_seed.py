"""The PSV answer-key seed (`eval/rule_trust/psv_invented_seed.json`): its
expected answers are arithmetic on the invented standard's limits; this test
checks the engine agrees with every one of them, and that the seed has the
shape `rule_trust.prove_family` reads. Invented data only; no model."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app import comparison, rule_eval

SEED = Path(__file__).resolve().parents[2] / "eval" / "rule_trust" / "psv_invented_seed.json"


def _same(a, b) -> bool:
    fold = lambda t: " ".join(re.findall(r"[a-z0-9]+", str(t).lower()))  # noqa: E731
    return fold(a) == fold(b)


def _engine(rule: dict, case: dict) -> str:
    values = case["values"]
    if rule.get("rows"):
        out = next(v for k, v in values.items() if _same(k, rule["output"]))
        inp = next(v for k, v in values.items() if _same(k, rule["input"]))
        return rule_eval.evaluate(rule, float(inp["value"]), inp["unit"], float(out["value"]), out["unit"])["status"]
    facts = [{"field_name": k, "raw_value": str(v["value"]), "raw_unit": v["unit"],
              "field_value": f'{v["value"]} {v["unit"]}', "is_blank": 0} for k, v in values.items()]
    return comparison.compare(rule, facts[0], submittal_facts=facts)["status"]


@pytest.fixture(scope="module")
def seed() -> dict:
    return json.loads(SEED.read_text(encoding="utf-8"))


def test_the_seed_has_the_shape_the_proof_reads(seed):
    ids = {r["id"] for r in seed["rules"]}
    assert len(seed["cases"]) >= 75 and len(ids) == 6
    for case in seed["cases"]:
        assert set(case) >= {"rule_id", "values", "expected"} and case["rule_id"] in ids
        assert case["expected"] in ("COMPLIANT", "NON_COMPLIANT")
        assert all(set(v) == {"value", "unit"} for v in case["values"].values())


def test_both_answers_are_present_and_none_is_borderline_by_accident(seed):
    kinds = Counter(c["expected"] for c in seed["cases"])
    assert kinds["COMPLIANT"] >= 30 and kinds["NON_COMPLIANT"] >= 30
    assert any(c["made"] == "at_limit" for c in seed["cases"])


def test_the_engine_agrees_with_every_arithmetic_answer(seed):
    rules = {r["id"]: r for r in seed["rules"]}
    wrong = [(c["made"], c["expected"]) for c in seed["cases"] if _engine(rules[c["rule_id"]], c) != c["expected"]]
    assert wrong == [], wrong
