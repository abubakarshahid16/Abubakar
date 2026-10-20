"""#882: a value the reader recorded as the PURCHASER'S requirement is never the
contractor's submitted value (`required_values.is_purchaser_kind`).

Found by the PF1 baseline on a sheet with Required and Offered columns: the
clause "the seat leakage class shall be Class IV or tighter" was judged
COMPLIANT against the REQUIRED column's own "Class IV" while the Offered cell
was blank. The AI and model readers record a value's kind in `section` as
`model:<kind>`; nothing read it. Now a required-kind value is taken out of the
pool every matcher draws from; with no offered value the field is not stated.
A fact with no kind (every code-reader fact) behaves exactly as before. Made-up
sample text and values only.
"""

from __future__ import annotations

import uuid

import pytest

from app import (
    comparison,
    datasheets,
    db,
    match_rules,
    required_values,
    standards,
    submittal_review,
)
from app.config import settings

NOW = "2026-10-20T00:00:00Z"
STD, SUB = "std-req", "sub-req"
CLASS_CLAUSE = "The seat leakage class shall be Class IV or tighter."
NUMBER_CLAUSE = "The design pressure shall be not less than 10 bar."


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "req.sqlite")
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    with db.connect() as conn:
        for doc_id, role in ((STD, "COMPANY_STANDARD"), (SUB, "CONTRACTOR_SUBMITTAL")):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
                "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
            )
            conn.execute(
                "INSERT INTO document_classification (document_id,suggested_by,"
                "document_role) VALUES (?,?,?)",
                (doc_id, "test", role),
            )
        for chunk_id, doc_id in (("sc", STD), ("fc", SUB)):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                "section,kind,text,token_count,content_hash,retrievable) VALUES "
                "(?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
                (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"),
            )
    yield
    db.reset_connection()


def _review(text, structured, facts):
    """One requirement, the given datasheet rows `(label, raw, blank, kind)`,
    one run. The finding and the run's outcome."""
    req = standards.create_requirement(
        standard_document_id=STD,
        chunk_id="sc",
        requirement_text=text,
        source_text=text,
        clause="4.1",
        page=1,
        structured=structured,
    )
    for label, raw, blank, kind in facts:
        datasheets.create_fact(
            submittal_document_id=SUB,
            chunk_id="fc",
            field_label=label,
            raw_value=raw,
            page=1,
            blank=blank,
            section=f"model:{kind}" if kind and not kind.startswith("col:") else None,
            value_column=kind[4:] if kind and kind.startswith("col:") else None,
        )
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
            "updated_at) VALUES (?,?,'pending',?,?)",
            (run_id, SUB, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,"
            "standard_document_id,selection_reason,selection_method,included,"
            "created_at) VALUES (?,?,?,'cited','referenced',1,?)",
            (str(uuid.uuid4()), run_id, STD, NOW),
        )
    outcome = comparison.run_comparison(
        run_id, allowed_document_ids=frozenset({STD, SUB})
    )
    found = [f for f in outcome["findings"] if f.get("requirement_id") == req["id"]]
    assert len(found) == 1, found
    return found[0], outcome


CLASS_RULE = {"subject": "the seat leakage class", "requirement_type": "statement"}
NUMBER_RULE = {
    "subject": "the design pressure",
    "operator": ">=",
    "raw_value": "10",
    "raw_unit": "bar",
    "requirement_type": "numeric_limit",
}


def test_a_required_class_with_a_blank_offer_is_missing_information(world):
    """The PF1 defect: the Required column's own "Class IV" was the clause's
    answer while the Offered cell (a field of its own) was blank."""
    found, outcome = _review(
        CLASS_CLAUSE,
        CLASS_RULE,
        [
            ("Seat leakage class", "Class IV", None, "required"),
            ("Seat leakage class Offered", None, (True, "______"), "offered"),
        ],
    )
    assert found["compliance_status"] == comparison.MISSING_INFORMATION
    assert found["ai_rationale"].startswith(f"{required_values.REQUIRED_VALUE_ONLY}:")
    assert "does not state an offered value" in found["ai_rationale"]
    assert outcome["purchaser_values_not_used"] == 1


def test_a_required_class_beside_a_same_name_blank_offer_is_still_missing(world):
    found, _ = _review(
        CLASS_CLAUSE,
        CLASS_RULE,
        [
            ("Seat leakage class", "Class IV", None, "required"),
            ("Seat leakage class", None, (True, "______"), "offered"),
        ],
    )
    assert found["compliance_status"] == comparison.MISSING_INFORMATION


def test_a_required_class_against_a_worse_offered_class_is_not_compliant(world):
    found, _ = _review(
        CLASS_CLAUSE,
        CLASS_RULE,
        [
            ("Seat leakage class", "Class IV", None, "required"),
            ("Seat leakage class", "Class III", None, "offered"),
        ],
    )
    assert found["compliance_status"] != comparison.COMPLIANT
    assert "Class III" in (found["ai_rationale"] or "")


def test_a_required_number_with_no_offer_is_missing_information(world):
    found, outcome = _review(
        NUMBER_CLAUSE,
        NUMBER_RULE,
        [
            ("Design pressure", "10 bar", None, "required"),
        ],
    )
    assert found["compliance_status"] == comparison.MISSING_INFORMATION
    assert found["fact_id"] is None
    assert found["ai_rationale"].startswith(f"{required_values.REQUIRED_VALUE_ONLY}:")
    assert outcome["purchaser_values_not_used"] == 1


def test_a_required_number_is_not_compared_when_an_offer_is_there(world):
    """Required 10 bar and offered 8 bar: the breach is on the OFFERED value."""
    found, _ = _review(
        NUMBER_CLAUSE,
        NUMBER_RULE,
        [
            ("Design pressure", "10 bar", None, "required"),
            ("Design pressure", "8 bar", None, "offered"),
        ],
    )
    assert found["compliance_status"] == comparison.NON_COMPLIANT
    assert "8" in (found["ai_rationale"] or "")


def test_an_offer_alone_is_judged_as_before(world):
    found, outcome = _review(
        NUMBER_CLAUSE,
        NUMBER_RULE,
        [
            ("Design pressure", "12 bar", None, "offered"),
        ],
    )
    assert found["compliance_status"] == comparison.COMPLIANT
    assert outcome["purchaser_values_not_used"] == 0


def test_a_fact_with_no_kind_is_judged_as_before(world):
    found, outcome = _review(
        NUMBER_CLAUSE,
        NUMBER_RULE,
        [
            ("Design pressure", "8 bar", None, None),
        ],
    )
    assert found["compliance_status"] == comparison.NON_COMPLIANT
    assert outcome["purchaser_values_not_used"] == 0


def test_a_measured_value_is_not_a_purchaser_value(world):
    found, _ = _review(
        NUMBER_CLAUSE,
        NUMBER_RULE,
        [
            ("Design pressure", "12 bar", None, "measured"),
        ],
    )
    assert found["compliance_status"] == comparison.COMPLIANT


# ------------------------------------------------ the matchers, called directly
def _fact(kind, value="10 bar"):
    return {
        "id": f"f-{kind}",
        "field_name": "design pressure",
        "field_value": value,
        "raw_value": value.split()[0],
        "raw_unit": "bar",
        "unit": "bar",
        "is_blank": 0,
        "section": f"model:{kind}" if kind else None,
    }


def _req():
    return {
        "id": "r",
        "requirement_type": "numeric_limit",
        "subject": "the design pressure",
        "operator": ">=",
        "raw_value": "10",
        "raw_unit": "bar",
        "unit": "bar",
        "requirement_text": NUMBER_CLAUSE,
    }


def test_the_rule_refuses_a_required_kind_and_only_that():
    assert (
        match_rules.refusal(_req(), _fact("required"), sheet=None)
        == required_values.REQUIRED_KIND
    )
    for kind in ("offered", "measured", None):
        assert match_rules.refusal(_req(), _fact(kind), sheet=None) is None


def test_the_containment_matcher_never_returns_a_required_value():
    match = comparison.match_by_containment(_req(), [_fact("required")])
    assert match["fact"] is None
    assert [r["reason"] for r in match["refused"]] == [required_values.REQUIRED_KIND]


def test_the_model_shortlist_never_offers_a_required_value():
    assert comparison.candidate_facts(_req(), [_fact("required")]) == []
    assert len(comparison.candidate_facts(_req(), [_fact("offered")])) == 1


# ------------------------------------------- when the "no offered value" note applies
_MISSING = {"status": comparison.MISSING_INFORMATION, "rationale": "no field answered"}


def _note(*, fact=None, rule_verdict=None, purchaser=None):
    purchaser = [{**_fact("required"), "page": 3}] if purchaser is None else purchaser
    return required_values.only_required_value(
        _MISSING, _req(), purchaser, None, fact, rule_verdict
    )


def test_a_clause_no_field_answered_gets_the_note_with_the_page():
    out = _note()
    assert out["status"] == comparison.MISSING_INFORMATION
    assert out["rationale"].startswith(f"{required_values.REQUIRED_VALUE_ONLY}:")
    assert "page 3" in out["rationale"]


def test_a_clause_a_field_answered_or_a_rule_judged_keeps_its_verdict():
    assert _note(fact=_fact("offered")) == _MISSING
    assert _note(rule_verdict={"status": comparison.COMPLIANT}) == _MISSING


def test_a_sheet_with_no_purchaser_value_keeps_the_verdict():
    assert _note(purchaser=[]) == _MISSING


def test_a_verdict_that_is_not_missing_information_is_left_alone():
    done = {"status": comparison.COMPLIANT, "rationale": "ok"}
    assert (
        required_values.only_required_value(
            done, _req(), [{**_fact("required"), "page": 3}], None, None, None
        )
        == done
    )


# ------------------------------------- the code readers' Required column (item 2)
def _code_fact(label, column=None):
    """A fact as the code readers store it: the geometry reader records the
    column header (`value_column`), the table reader names the cell
    "<row label> - <column header>". Neither sets a `section` kind."""
    return {
        **_fact(None),
        "field_name": label.lower(),
        "field_label": label,
        "value_column": column,
    }


def test_a_code_read_required_column_is_refused_as_the_submission():
    for fact in (
        _code_fact("Design pressure Required", "Required"),
        _code_fact("Design pressure - Specified"),
        _code_fact("Design pressure - Required"),
    ):
        assert required_values.is_purchaser_kind(fact), fact
        assert (
            match_rules.refusal(_req(), fact, sheet=None)
            == required_values.REQUIRED_KIND
        )


def test_a_code_read_offered_or_unnamed_column_is_not_refused():
    for fact in (
        _code_fact("Design pressure Offered", "Offered"),
        _code_fact("Design pressure - Offered"),
        _code_fact("Design pressure MIN", "MIN"),
        _code_fact("Design pressure", "Value"),
        _code_fact("Design pressure"),
    ):
        assert not required_values.is_purchaser_kind(fact), fact
        assert match_rules.refusal(_req(), fact, sheet=None) is None


def test_the_model_shortlist_never_offers_a_code_read_required_value():
    """The AI matcher chooses among the shortlist: a Required-column number must
    not be on it, however the code reader named the cell."""
    required = _code_fact("Design pressure Required", "Required")
    offered = _code_fact("Design pressure Offered", "Offered")
    shortlist = comparison.candidate_facts(_req(), [required, offered])
    assert [f["field_label"] for f in shortlist] == ["Design pressure Offered"]


def test_a_table_reader_required_cell_is_counted_and_never_the_submission(world):
    found, outcome = _review(
        NUMBER_CLAUSE,
        NUMBER_RULE,
        [("Design pressure - Required", "12", None, None)],
    )
    assert found["compliance_status"] == comparison.MISSING_INFORMATION
    assert outcome["purchaser_values_not_used"] == 1
