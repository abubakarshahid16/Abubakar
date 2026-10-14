"""A clause that compares ONE field of the sheet with ANOTHER ("the outlet size
shall be not less than the inlet size", "... not less than the maximum operating
pressure plus 2 bar", "... not less than half of the line size") is judged in
code against the sheet's two fields. A field the sheet does not state leaves it
with an engineer; nothing is invented. Invented data only."""
from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, requirements_3b as r, rule_eval, standards, submittal_review
import tests.test_b3_page_ledger as ledger_tests
from tests.test_b3_page_ledger import NOW, temp_storage  # noqa: F401 - autouse


@pytest.mark.parametrize("sentence, output, operator, factor, offset, unit, reference", [
    ("The outlet size shall be not less than the inlet size.", "outlet size", ">=", 1.0, 0.0, None, "inlet size"),
    ("The design pressure shall be not less than the maximum operating pressure plus 2 bar.",
     "design pressure", ">=", 1.0, 2.0, "bar", "maximum operating pressure"),
    ("The body size shall be not less than half of the line size.", "body size", ">=", 0.5, 0.0, None, "line size"),
    ("The set pressure shall not exceed the maximum allowable working pressure of the protected equipment.",
     "set pressure", "<=", 1.0, 0.0, None, "maximum allowable working pressure"),
    ("The wall thickness shall be not less than the corrosion allowance plus 3 mm.",
     "wall thickness", ">=", 1.0, 3.0, "mm", "corrosion allowance"),
])
def test_a_comparison_of_two_fields_is_read(sentence, output, operator, factor, offset, unit, reference):
    cross = r.parse_cross_field(sentence)
    assert cross == {"output": output, "reference": reference, "operator": operator, "factor": factor,
                     "offset": offset, "offset_unit": unit}, cross
    limit = r.parse_limit_or_range(sentence)
    assert limit["operator"] == r.CROSS_OPERATOR and r.classify(sentence, limit) == r.CROSS_FIELD_LIMIT


@pytest.mark.parametrize("sentence", [
    "The pump shall be not less than the value given in Table 3.",                        # a table, not a field
    "The flange rating shall be at least the design pressure rating when the line is hot.",   # a condition
    "The cable shall be at least 3 m.",                                                   # a plain limit
    "The vendor shall not be less than the purchaser.",                                   # parties, not fields
    "The outlet shall not be less than the inlet size unless the purchaser agrees.",      # a condition
    "Outlet size shall not be the inlet size.",                                           # no comparator
    "The rated capacity shall be not less than 1.1 times the required capacity.",         # a factor: left to the engineer
])
def test_when_unsure_a_sentence_is_not_a_field_comparison(sentence):
    assert r.parse_cross_field(sentence) is None
    limit = r.parse_limit_or_range(sentence)
    assert not limit or limit["operator"] != r.CROSS_OPERATOR


def test_it_is_a_stored_matchable_type_the_api_can_return():
    assert r.CROSS_FIELD_LIMIT in r.STORED_REQUIREMENT_TYPES and r.CROSS_FIELD_LIMIT in comparison.MATCHABLE_TYPES


def test_the_old_limit_reader_is_unchanged_by_sharing_its_comparator_words():
    limit = r.parse_limit("The wall shall be not less than 5 mm.")
    assert (limit["operator"], limit["raw_value"], limit["raw_unit"]) == (">=", "5", "mm")


# ------------------------------------------------------------ end to end
def _run(tmp_path, monkeypatch, rows, sentence):
    monkeypatch.setattr(ledger_tests, "ROWS", rows)
    sub = ledger_tests._sheet(tmp_path, notes_page=False)
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))
    std = "doc_std_x"
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES (?,?,?,1,'x','ready',1,?)", (std, "STD-X.pdf", "sha-std-x", NOW))
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                     "section,kind,text,token_count,content_hash,retrievable)"
                     " VALUES ('c-x',?,'STD-X.pdf',1,1,1,NULL,'prose',?,1,'h-x',1)", (std, sentence))
    scope = frozenset({std, sub})
    run = submittal_review.create_review_run(submittal_document_id=sub, allowed_document_ids=scope)
    with db.connect() as conn:
        conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
                     "selection_reason,selection_method,included,created_at)"
                     " VALUES (?,?,?,'cited','referenced',1,?)", (str(uuid.uuid4()), run, std, NOW))
    cross = r.parse_cross_field(sentence)
    standards.create_requirement(
        standard_document_id=std, chunk_id="c-x", clause="4.2", page=1, requirement_text=sentence,
        source_text=sentence,
        structured={"requirement_type": r.CROSS_FIELD_LIMIT, "operator": r.CROSS_OPERATOR,
                    "subject": cross["output"], "field": cross["output"]})
    comparison.run_comparison(run, allowed_document_ids=scope)
    [finding] = [dict(x) for x in db.connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? AND origin IS NULL", (run,))]
    return finding


SIZE = "The outlet size shall be not less than the inlet size."


def test_an_outlet_at_least_as_large_as_the_inlet_meets(tmp_path, monkeypatch):
    f = _run(tmp_path, monkeypatch, [("Inlet size", "4 in"), ("Outlet size", "6 in")], SIZE)
    assert f["compliance_status"] == "COMPLIANT" and f["match_method"] == "rule"


def test_an_outlet_smaller_than_the_inlet_does_not_meet(tmp_path, monkeypatch):
    f = _run(tmp_path, monkeypatch, [("Inlet size", "6 in"), ("Outlet size", "4 in")], SIZE)
    assert f["compliance_status"] == "NON_COMPLIANT"


def test_another_unit_of_the_same_quantity_is_converted(tmp_path, monkeypatch):
    f = _run(tmp_path, monkeypatch, [("Inlet size", "4 in"), ("Outlet size", "200 mm")], SIZE)
    assert f["compliance_status"] == "COMPLIANT"        # 200 mm = 7.87 in


def test_an_offset_in_its_own_unit_is_added_to_the_reference(tmp_path, monkeypatch):
    sentence = "The design pressure shall be not less than the maximum operating pressure plus 2 bar."
    meets = _run(tmp_path, monkeypatch, [("Maximum operating pressure", "10 bar"), ("Design pressure", "12 bar")], sentence)
    assert meets["compliance_status"] == "COMPLIANT"


def test_a_ceiling_is_a_ceiling(tmp_path, monkeypatch):
    sentence = "The cold differential test pressure shall not exceed the set pressure."
    f = _run(tmp_path, monkeypatch, [("Set pressure", "10 bar"), ("Cold differential test pressure", "12 bar")], sentence)
    assert f["compliance_status"] == "NON_COMPLIANT"


def test_a_reference_the_sheet_does_not_state_is_the_engineers_and_never_a_verdict(tmp_path, monkeypatch):
    f = _run(tmp_path, monkeypatch, [("Outlet size", "6 in")], SIZE)
    assert f["compliance_status"] in ("NEEDS_ENGINEER_REVIEW", "MISSING_INFORMATION")
    assert f["compliance_status"] not in ("COMPLIANT", "NON_COMPLIANT")


def test_incomparable_units_are_never_a_verdict(tmp_path, monkeypatch):
    f = _run(tmp_path, monkeypatch, [("Inlet size", "4 in"), ("Outlet size", "10 kg")], SIZE)
    assert f["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
