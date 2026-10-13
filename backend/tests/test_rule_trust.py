"""rule_trust: tiered automatic use of AI-compiled rules.

Every test is about what CODE does: tiers from the reference file and
generic condition words, proof on an answer key through the existing
evaluators, the second check (verify_proposal + contradicts_source, reused),
trust labels and the downgrade of an UNPROVEN verdict, uncovered fields, the
random audit and its effect on a proof. Invented text only.
"""
from __future__ import annotations

import pytest

from app import access, db
from app import rule_trust as rt
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "rule_trust.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


SENTENCE = "The nozzle projection shall not exceed 60 mm."


def limit_rule(**over) -> dict:
    base = {"id": "r1", "standard_document_id": "doc1", "equipment_type": "pump",
            "field": "nozzle projection", "operator": "<=", "raw_value": "60", "raw_unit": "mm",
            "requirement_type": "numeric_limit", "source_text": SENTENCE, "confirmed_by": None}
    return {**base, **over}


def cases(n: int, rule_id: str = "r1") -> list[dict]:
    """n answer-key cases, some under and some over the 60 mm limit."""
    out = []
    for i in range(n):
        value = 40 + (i % 40)          # 40 .. 79
        out.append({"rule_id": rule_id, "values": {"nozzle projection": {"value": str(value), "unit": "mm"}},
                    "expected": rt.COMPLIANT if value <= 60 else rt.NON_COMPLIANT})
    return out


# ------------------------------------------------------------ 1. tiers

@pytest.mark.parametrize("field", ["Set Pressure", "PSV set pressure (barg)", "Design temperature",
                                   "SIL", "Hazardous area classification", "Relieving capacity"])
def test_safety_field_list_makes_a_rule_safety_tier(field):
    level, why = rt.tier(limit_rule(field=field, source_text="The value shall be 10 bar."))
    assert level == rt.SAFETY and "safety field" in why


def test_sentence_naming_sour_service_makes_material_safety_tier():
    rule = limit_rule(field="material hardness", source_text="Hardness shall not exceed 22 HRC in sour service.")
    assert rt.tier(rule)[0] == rt.SAFETY


@pytest.mark.parametrize("words", ["except for drains", "unless agreed otherwise", "provided that it is",
                                   "in accordance with clause 4", "as per the data sheet",
                                   "see Section 7", "where fitted"])
def test_condition_exception_and_cross_reference_words_make_safety_tier(words):
    rule = limit_rule(source_text=f"The nozzle projection shall not exceed 60 mm, {words}.")
    level, why = rt.tier(rule)
    assert level == rt.SAFETY and "condition" in why


def test_plain_rule_on_ordinary_field_is_standard_tier():
    assert rt.tier(limit_rule()) == (rt.STANDARD, None)
    # words that only CONTAIN an operator word are not one ("lifting", "whereas"-free text)
    assert rt.tier(limit_rule(source_text="The lifting lug nozzle projection shall not exceed 60 mm."))[0] \
        == rt.STANDARD


def test_safety_list_is_reference_data_not_code(tmp_path):
    ref = tmp_path / "ref.json"
    ref.write_text('{"safety_fields": [{"name": "nozzle projection"}], "condition_words": []}')
    assert rt.tier(limit_rule(), ref=rt.reference(ref))[0] == rt.SAFETY


# ------------------------------------------------------------ 2. proof

def test_proof_uses_existing_evaluator_and_is_proven_at_min_cases_with_no_error():
    result = rt.prove_family([limit_rule()], cases(300))
    assert result["cases"] == 300 and result["correct"] == 300 and result["errors"] == []
    assert result["status"] == rt.PROVEN


def test_proof_below_min_cases_is_not_proven():
    result = rt.prove_family([limit_rule()], cases(299))
    assert result["status"] == rt.NOT_PROVEN and "at least 300" in result["reason"]


def test_one_error_is_not_proven():
    key = cases(400)
    key[7] = {**key[7], "expected": rt.NON_COMPLIANT if key[7]["expected"] == rt.COMPLIANT else rt.COMPLIANT}
    result = rt.prove_family([limit_rule()], key)
    assert result["status"] == rt.NOT_PROVEN and len(result["errors"]) == 1
    assert result["errors"][0]["case"] == 7


def test_case_for_unknown_rule_or_raising_evaluator_is_an_error():
    def boom(rule, case):
        raise ValueError("x")
    assert rt.prove_family([limit_rule()], cases(5, "nope"), min_cases=1)["status"] == rt.NOT_PROVEN
    result = rt.prove_family([limit_rule()], cases(5), boom, min_cases=1)
    assert len(result["errors"]) == 5 and "evaluation failed" in result["errors"][0]["got"]


def test_table_rule_goes_through_rule_eval():
    rule = {"id": "t1", "output": "design pressure", "input": "operating pressure", "unit": "kPa",
            "comparator": ">=", "rows": [{"from": None, "to": 100000, "op": "single", "terms": [{"k": 1, "c": 170}]}]}
    case = {"rule_id": "t1", "values": {"operating pressure": {"value": "1000", "unit": "kPa"},
                                        "design pressure": {"value": "1100", "unit": "kPa"}}}
    assert rt.evaluate_case(rule, case) == rt.NON_COMPLIANT


def test_proof_invalid_on_model_or_revision_change():
    key = rt.family_key("doc1", "Pump")
    saved = rt.save_proof(key, rt.prove_family([limit_rule()], cases(300)),
                          model_id="m1", standard_revision="Rev 2")
    assert saved["status"] == rt.PROVEN
    assert rt.load_proof(key, model_id="m1", standard_revision="Rev 2")["status"] == rt.PROVEN
    assert rt.load_proof(key, model_id="m2", standard_revision="Rev 2")["status"] == rt.INVALID
    assert rt.load_proof(key, model_id="m1", standard_revision="Rev 3")["status"] == rt.INVALID
    assert rt.load_proof("other|-", model_id="m1", standard_revision="Rev 2") is None


# ------------------------------------------------------------ 3. second check

def test_second_check_passes_a_rule_its_sentence_supports():
    assert rt.second_check(limit_rule()) == (True, None)


def test_contradicting_operator_fails_second_check_and_is_unproven():
    rule = limit_rule(operator=">=")       # "shall not exceed 60" is <= 60
    ok, why = rt.second_check(rule)
    assert not ok and why
    assert rt.trust_label(rule, {"status": rt.PROVEN}) == rt.UNPROVEN


def test_contradicts_source_runs_with_the_rules_operator(monkeypatch):
    """verify_proposal agreeing is not enough: contradicts_source has the last word."""
    monkeypatch.setattr(rt.ai_requirements, "verify_proposal", lambda p, s: ({}, None))
    monkeypatch.setattr(rt.requirements_3b, "contradicts_source", lambda limit, s: limit["operator"] == ">=")
    assert rt.second_check(limit_rule(operator=">="))[1] == "the operator points the opposite way to the sentence"
    assert rt.second_check(limit_rule())[0] is True


def test_value_not_in_sentence_fails_second_check():
    assert rt.second_check(limit_rule(raw_value="65"))[0] is False


# ------------------------------------------------------------ 4. labels

def test_trust_labels():
    proven = {"status": rt.PROVEN}
    assert rt.trust_label(limit_rule(confirmed_by="u1"), None) == rt.ENGINEER_CONFIRMED
    assert rt.trust_label(limit_rule(), proven) == rt.AUTO_PROVEN
    assert rt.trust_label(limit_rule(), None) == rt.UNPROVEN
    assert rt.trust_label(limit_rule(), {"status": rt.INVALID}) == rt.UNPROVEN


@pytest.mark.parametrize("status", [rt.COMPLIANT, rt.NON_COMPLIANT])
def test_unproven_verdict_is_downgraded(status):
    out = rt.apply_trust({"status": status, "rationale": "r"}, rt.UNPROVEN)
    assert out["status"] == rt.NEEDS_ENGINEER_REVIEW and out["rule_said"] == status
    assert "not yet proven" in out["trust_words"] and "engineer decides" in out["rationale"]


def test_proven_and_confirmed_verdicts_are_kept_and_labelled():
    assert rt.apply_trust({"status": rt.COMPLIANT}, rt.AUTO_PROVEN)["status"] == rt.COMPLIANT
    out = rt.apply_trust({"status": rt.NON_COMPLIANT}, rt.ENGINEER_CONFIRMED)
    assert out["status"] == rt.NON_COMPLIANT and out["trust_words"] == "engineer-approved rule"
    assert rt.apply_trust({"status": "MISSING_INFORMATION"}, rt.UNPROVEN)["status"] == "MISSING_INFORMATION"


def test_hook_is_off_by_default_and_flags_safety_compliant_when_on(monkeypatch):
    finding = {"status": rt.COMPLIANT}
    safety = limit_rule(field="design pressure", raw_unit="bar", source_text="The design pressure shall not exceed 60 bar.")
    assert rt.label_finding(finding, safety, {"status": rt.PROVEN}) is finding
    monkeypatch.setattr(settings, "rule_auto_use_enabled", True)
    out = rt.label_finding(finding, safety, {"status": rt.PROVEN})
    assert out["trust_label"] == rt.AUTO_PROVEN and out["tier"] == rt.SAFETY
    assert out["show_for_engineer_tick"] is True
    plain = rt.label_finding(finding, limit_rule(), {"status": rt.PROVEN})
    assert plain["show_for_engineer_tick"] is False
    assert rt.label_finding(finding, safety, None)["status"] == rt.NEEDS_ENGINEER_REVIEW


# ------------------------------------------------------------ 5. uncovered

def test_uncovered_fields_lists_read_values_no_rule_targets():
    facts = [{"field_name": "Nozzle Projection", "raw_value": "55"},
             {"field_name": "Design pressure", "raw_value": "10"},
             {"field_name": "Pressure", "raw_value": "4"},
             {"field_name": "Noise level", "raw_value": None, "is_blank": 1},
             {"field_name": "Casing material", "raw_value": ""}]
    rules = [limit_rule(), limit_rule(id="r2", field="pressure")]
    out = [f["field_name"] for f in rt.uncovered_fields(facts, rules)]
    # "pressure" does not cover "design pressure"; blanks were not read with a value
    assert out == ["Design pressure"]
    assert [f["field_name"] for f in rt.uncovered_fields(facts[:1], [])] == ["Nozzle Projection"]


# ------------------------------------------------------------ 6. audit

def test_audit_sample_size_clamp_and_determinism():
    ids = [f"f{i}" for i in range(100)]
    assert len(rt.audit_sample(ids, 0.03, "run1")) == 3
    assert len(rt.audit_sample(ids, 0.5, "run1")) == 5          # clamped to 5%
    assert len(rt.audit_sample(ids, 0.0, "run1")) == 2          # clamped to 2%
    assert len(rt.audit_sample(ids[:3], 0.03, "run1")) == 1     # at least one
    assert rt.audit_sample([], 0.03, "run1") == []
    assert rt.audit_sample(ids, 0.03, "run1") == rt.audit_sample(list(ids), 0.03, "run1")
    assert rt.audit_sample(ids, 0.03, "run1") != rt.audit_sample(ids, 0.03, "run2")
    assert len(rt.audit_sample(ids, None, "s")) == 3            # settings default 0.03


def test_audit_error_invalidates_proof_and_correct_does_not():
    key = rt.family_key("doc1", "pump")
    rt.save_proof(key, rt.prove_family([limit_rule()], cases(300)), model_id="m1", standard_revision="R1")
    assert rt.record_audit_outcome("f1", key, correct=True, engineer="u1")["status"] == rt.PROVEN
    after = rt.record_audit_outcome("f2", key, correct=False, engineer="u1")
    assert after["status"] == rt.INVALID and "f2" in after["invalid_reason"]
    proof = rt.load_proof(key, model_id="m1", standard_revision="R1")
    assert rt.trust_label(limit_rule(), proof) == rt.UNPROVEN
