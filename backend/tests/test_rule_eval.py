"""Owner order 2a + 2b: table and formula rules evaluated in code, on the right field.

The design-pressure case the owner saw: a range table ("up to 1,800 kPa: MOP +
170 kPa; over 1,800 up to 6,900 kPa: the greater of 1.1 x MOP and MOP + 170
kPa") was paired with the operating pressure (its INPUT) and sent to an
engineer. Here, on a synthetic standard and a synthetic datasheet (every
number invented):

  * rule_eval: each supported shape, units, out-of-range input, gauge against
    absolute, unparseable -> None;
  * a model's parse is kept only when every number in it is on the page;
  * 2b: the OUTPUT field is judged and the input named - meets, does not meet,
    output missing (MISSING_INFORMATION), input missing (engineer).

Mutations M1073-M1081.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app import comparison, datasheets, db, rule_eval, standards, submittal_review
from app import reasoning_provider as rp
from app.config import settings
import tests.test_b3_page_ledger as ledger_tests
from tests.test_b3_page_ledger import NOW, temp_storage  # noqa: F401 - autouse

TABLE = """Design pressure shall be according to the following table.
Maximum operating pressure (MOP) | Design pressure
Up to 1,800 kPa | MOP + 170 kPa
Over 1,800 up to 6,900 kPa | 1.1 x MOP or MOP + 170 kPa, whichever is greater
Over 6,900 kPa | 1.1 x MOP"""
INPUTS = ["mop", "maximum operating pressure", "operating pressure"]


def _rule():
    return rule_eval.parse_rule(TABLE, output="design pressure", input_names=INPUTS)


# ---------------------------------------------------------------- pure

def test_the_table_parses_into_three_rows():
    rule = _rule()
    assert rule["unit"] == "kPa"
    assert [(r["from"], r["to"], r["op"]) for r in rule["rows"]] == [
        (None, 1800.0, "single"), (1800.0, 6900.0, "max"), (6900.0, None, "single")]


@pytest.mark.parametrize("mop, dp, status, required", [
    (1500, 1700, "COMPLIANT", 1670),          # MOP + 170
    (1500, 1600, "NON_COMPLIANT", 1670),
    (3000, 3300, "COMPLIANT", 3300),          # max(1.1 x 3000, 3170) = 3300
    (3000, 3200, "NON_COMPLIANT", 3300),
    (1000, 1170, "COMPLIANT", 1170),          # the max() in row 2 does not leak into row 1
    (8000, 8800, "COMPLIANT", 8800),          # 1.1 x MOP
])
def test_each_row_shape_is_evaluated(mop, dp, status, required):
    """M1073, M1074."""
    result = rule_eval.evaluate(_rule(), mop, "kPa", dp, "kPa")
    assert result["status"] == status
    assert round(result["required_value"], 6) == required


def test_units_convert_through_the_unit_table():
    """30 barg = 3,000 kPa gauge: required 3,300 kPa; 34 barg meets it."""
    result = rule_eval.evaluate(_rule(), 30, "barg", 34, "barg")
    assert result["status"] == "COMPLIANT"
    assert "read as gauge" in result["rationale"], "an assumed basis must be stated"


def test_gauge_against_absolute_is_not_compared():
    """M1075."""
    result = rule_eval.evaluate(_rule(), 30, "barg", 34, "bara")
    assert result["status"] == "NEEDS_ENGINEER_REVIEW" and "not one scale" in result["rationale"]


def test_a_max_rule_takes_the_greater_term_even_when_it_is_the_second():
    """M1073: 500 kPa -> max(1.1 x 500, 500 + 170) = 670, the SECOND term."""
    rule = rule_eval.parse_rule(
        "Up to 1,000 kPa | 1.1 x MOP or MOP + 170 kPa, whichever is greater",
        output="design pressure", input_names=INPUTS)
    assert rule_eval.evaluate(rule, 500, "kPa", 600, "kPa")["status"] == "NON_COMPLIANT"
    assert rule_eval.evaluate(rule, 500, "kPa", 670, "kPa")["required_value"] == 670


def test_a_min_rule_takes_the_lesser_term():
    rule = rule_eval.parse_rule(
        "Up to 100 kPa | 2 x MOP or MOP + 50 kPa, whichever is less",
        output="design pressure", input_names=INPUTS)
    assert rule_eval.evaluate(rule, 80, "kPa", 130, "kPa")["required_value"] == 130


def test_an_input_outside_every_row_is_for_an_engineer():
    rule = rule_eval.parse_rule("Up to 1,800 kPa | MOP + 170 kPa", output="design pressure",
                                input_names=INPUTS)
    result = rule_eval.evaluate(rule, 2500, "kPa", 3000, "kPa")
    assert result["status"] == "NEEDS_ENGINEER_REVIEW" and "outside every row" in result["rationale"]


@pytest.mark.parametrize("text", [
    "Design pressure shall be adequate for the service.",
    "Up to 1,800 kPa | as agreed with the company",
    "Up to 1,800 kPa | MOP + 170 kPa\nOver 1,800 bar | 1.1 x MOP",      # two units
    "Up to 1,800 kPa | 1.1 x TEMPERATURE",                              # not the input
    "Up to 1,800 kPa | MOP + 170 kPa\nOver 1,800 kPa | as agreed with the company",  # half-read
])
def test_an_unparseable_table_is_none_never_a_guess(text):
    """M1076: one unreadable row makes the whole table unreadable."""
    assert rule_eval.parse_rule(text, output="design pressure", input_names=INPUTS) is None


def test_a_number_not_on_the_page_fails_verification():
    """M1077: the model-parse gate."""
    rule = _rule()
    assert rule_eval.verify_numbers(rule, TABLE)
    invented = {**rule, "rows": [{"from": None, "to": 1900, "op": "single",
                                  "terms": [{"k": 1, "c": 170}]}]}
    assert not rule_eval.verify_numbers(invented, TABLE)


# ------------------------------------------------------ end to end (2b)

def _world(tmp_path, monkeypatch, rows, *, table=TABLE, requirement_text=None):
    monkeypatch.setattr(ledger_tests, "ROWS", rows)
    sub = ledger_tests._sheet(tmp_path, notes_page=False)
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))
    std = "doc_std_dp"
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES (?,?,?,1,'x','ready',1,?)",
                     (std, "STD-DP.pdf", "sha-std-dp", NOW))
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                     "section,kind,text,token_count,content_hash,retrievable)"
                     " VALUES ('c-dp',?,'STD-DP.pdf',1,1,1,NULL,'prose',?,1,'h-dp',1)", (std, table))
    scope = frozenset({std, sub})
    run = submittal_review.create_review_run(submittal_document_id=sub, allowed_document_ids=scope)
    with db.connect() as conn:
        conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
                     "selection_reason,selection_method,included,created_at)"
                     " VALUES (?,?,?,'cited','referenced',1,?)", (str(uuid.uuid4()), run, std, NOW))
    text = requirement_text or "Design pressure shall be according to the following table."
    standards.create_requirement(
        standard_document_id=std, chunk_id="c-dp", clause="4.2", page=1,
        requirement_text=text, source_text=text,
        structured={"requirement_type": "table_row", "operator": "<=", "value": 1800,
                    "unit": "kPa", "raw_value": "1,800", "raw_unit": "kPa",
                    "field": "design pressure", "subject": "design pressure"})
    comparison.run_comparison(run, allowed_document_ids=scope)
    [finding] = [dict(r) for r in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin IS NULL", (run,))]
    return finding


def test_design_pressure_meets_the_calculated_requirement(tmp_path, monkeypatch):
    """M1078: the OUTPUT is judged, the input named, the row cited."""
    f = _world(tmp_path, monkeypatch, [("Maximum operating pressure", "3000 kPa"),
                                       ("Design pressure", "3300 kPa")])
    assert f["compliance_status"] == "COMPLIANT"
    assert f["matched_phrase"] == "design pressure" and f["match_method"] == "rule"
    assert "required design pressure at least 3,300 kPa from operating pressure 3,000 kPa" \
        in f["ai_rationale"]
    assert "over 1,800 up to 6,900 kPa" in f["ai_rationale"]
    fact = db.connect().execute("SELECT field_name FROM submittal_facts WHERE id = ?",
                                (f["fact_id"],)).fetchone()
    assert fact["field_name"] == "design pressure", "the verdict judged the input field"


def test_design_pressure_too_low_does_not_meet(tmp_path, monkeypatch):
    f = _world(tmp_path, monkeypatch, [("Maximum operating pressure", "3000 kPa"),
                                       ("Design pressure", "3200 kPa")])
    assert f["compliance_status"] == "NON_COMPLIANT"


def test_design_pressure_missing_is_missing_information_not_a_comparison(tmp_path, monkeypatch):
    """M1079: only the input on the sheet - never compared against the rule."""
    f = _world(tmp_path, monkeypatch, [("Maximum operating pressure", "3000 kPa"),
                                       ("Design temperature", "120 C")])
    assert f["compliance_status"] == "MISSING_INFORMATION"
    assert "design pressure not stated on the datasheet" in f["ai_rationale"]


def test_the_input_missing_leaves_the_required_value_uncalculated(tmp_path, monkeypatch):
    f = _world(tmp_path, monkeypatch, [("Design pressure", "3300 kPa"),
                                       ("Design temperature", "120 C")])
    assert f["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert "could not be calculated" in f["ai_rationale"]


def test_the_parsed_rule_is_stored_once_with_its_source(tmp_path, monkeypatch):
    """M1080: computed once and auditable."""
    _world(tmp_path, monkeypatch, [("Maximum operating pressure", "3000 kPa"),
                                   ("Design pressure", "3300 kPa")])
    row = db.connect().execute("SELECT rule_json, rule_source FROM standard_requirements").fetchone()
    assert row["rule_source"] == "code"
    assert json.loads(row["rule_json"])["unit"] == "kPa"


def test_a_garbled_table_stays_with_an_engineer_and_says_so(tmp_path, monkeypatch):
    f = _world(tmp_path, monkeypatch, [("Maximum operating pressure", "3000 kPa"),
                                       ("Design pressure", "3300 kPa")],
               table="Design pressure shall be according to the following table.\n"
                     "Up to 1,8OO kPa | M0P + l7O kPa")
    assert f["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert "the table on page 1 could not be read" in f["ai_rationale"]


class _FakeModel:
    def __init__(self, body):
        self.body = body

    def reason(self, packet):
        text = json.dumps(self.body)
        return rp.Response(text=text, provider=rp.CLAUDE, model_tag="fake", digest="d",
                           finish_reason="stop", prompt_sha256=packet.sha256)


GARBLED = "Design pressure: up to 1,800 kPa add 170 kPa to MOP."


def _req():
    return {"id": None, "requirement_text": GARBLED, "source_text": GARBLED,
            "chunk_id": None, "standard_document_id": None}


def test_a_model_parse_is_kept_only_when_every_number_is_on_the_page(monkeypatch):
    """M1081: reject, never repair."""
    monkeypatch.setattr(settings, "rule_parse_model_enabled", True)
    honest = _FakeModel({"unit": "kPa", "rows": [
        {"from": None, "to": 1800, "op": "single", "terms": [{"k": 1, "c": 170}]}]})
    invented = _FakeModel({"unit": "kPa", "rows": [
        {"from": None, "to": 1800, "op": "single", "terms": [{"k": 1.1, "c": 170}]}]})
    rule, source = rule_eval.rule_for(_req(), provider=honest)
    assert source == rule_eval.SOURCE_MODEL and rule["rows"][0]["terms"][0]["c"] == 170
    assert rule_eval.rule_for(_req(), provider=invented)[0] is None


def test_the_model_is_not_asked_when_its_flag_is_off(monkeypatch):
    class Explode:
        def reason(self, packet):
            raise AssertionError("the model was asked with the flag off")
    assert rule_eval.rule_for(_req(), provider=Explode())[0] is None
