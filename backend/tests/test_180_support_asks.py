"""Orders 180.1 item 2: a plain statement supports a blank-field row only if it asks the
sheet to state something. "Weld repairs shall be re-examined and the results noted on
a data report" does not ask for an "Ultrasonic" value; "The vendor shall state the
ultrasonic examination extent" does. Invented sentences and fields only.
"""

from __future__ import annotations

import uuid

import pytest

from app import (
    comparison,
    datasheets,
    db,
    match_rules,
    scope_ledger,
    standards,
    statement_asks,
    submittal_review,
)
from app.config import settings

NOW = "2026-10-20T00:00:00Z"


def req(text, kind="statement"):
    return {"requirement_type": kind, "source_text": text, "requirement_text": text}


NOT_ASKING = [
    "Weld repairs shall be re-examined and the results noted on a data report.",
    "Ultrasonic examination shall be performed on all butt welds.",
    "Welders shall be qualified before work starts and records kept.",
]
ASKING = [
    "The vendor shall state the ultrasonic examination extent.",
    "Ultrasonic acceptance standard to be specified by the contractor.",
    "Provide the ultrasonic examination procedure number.",
    "The test results must be recorded and submitted with the datasheet.",
]


@pytest.mark.parametrize("text", NOT_ASKING)
def test_a_statement_that_asks_for_work_not_for_a_stated_value_does_not_ask(text):
    assert not statement_asks.asks_to_state(req(text))


@pytest.mark.parametrize("text", ASKING)
def test_a_statement_that_says_state_specify_provide_or_record_asks(text):
    assert statement_asks.asks_to_state(req(text))


@pytest.mark.parametrize(
    "kind", ["numeric_limit", "range_limit", "table_row", "nominal_value"]
)
def test_a_requirement_with_its_own_value_is_never_judged_by_this_rule(kind):
    assert statement_asks.asks_to_state(req("Anything at all.", kind))


def test_only_a_blank_field_is_refused_for_a_statement_that_does_not_ask():
    r = req(NOT_ASKING[0])
    blank = {"field_name": "Ultrasonic", "is_blank": True}
    filled = {"field_name": "Ultrasonic", "raw_value": "100%", "is_blank": False}
    assert match_rules.refusal(r, blank, sheet=None) == match_rules.NOT_ASKED
    assert match_rules.refusal(r, filled, sheet=None) is None
    assert match_rules.refusal(req(ASKING[0]), blank, sheet=None) is None


# ------------------------------------------------------------------- on a review


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "asks.sqlite")
    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    monkeypatch.setattr(settings, "ai_division_scope_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, role, text, **meta):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES (?,?,?,?,0,0)",
            (doc_id, 1, text, len(text)),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,1,1,1,NULL,'prose',"
            "?,1,?,1)",
            (f"{doc_id}-1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
        )


def test_a_blank_field_is_supported_only_by_the_clause_that_asks_for_it(temp_storage):
    _doc("std", "COMPANY_STANDARD", "x", document_number="STD-1")
    _doc("sub", "CONTRACTOR_SUBMITTAL", "Ultrasonic ___\n", equipment_type="Pump")
    ids = {}
    for key, text, subject in (
        (
            "repair",
            "Ultrasonic re-examination of weld repairs shall be done and the results noted.",
            "ultrasonic re-examination of weld repairs",
        ),
        (
            "asks",
            "The vendor shall state the ultrasonic examination extent.",
            "ultrasonic examination extent",
        ),
    ):
        ids[key] = standards.create_requirement(
            standard_document_id="std",
            chunk_id="std-1",
            clause=None,
            page=1,
            requirement_text=text,
            source_text=text,
            structured={"requirement_type": "statement", "subject": subject},
        )["id"]
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="sub-1",
        field_label="Ultrasonic",
        raw_value="___",
        page=1,
    )
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,?,'pending',?,?)",
            (run, "sub", NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
            "selection_method,included,created_at) VALUES (?,?,?,'manual',1,?)",
            (str(uuid.uuid4()), run, "std", NOW),
        )
    result = comparison.run_comparison(
        run, allowed_document_ids=frozenset({"std", "sub"})
    )
    by_req = {f.get("requirement_id"): f for f in result["findings"]}
    assert by_req[ids["asks"]]["compliance_status"] == comparison.MISSING_INFORMATION
    assert ids["repair"] not in by_req or (
        by_req[ids["repair"]]["compliance_status"] != comparison.MISSING_INFORMATION
    )
    stored = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}
    assert stored[ids["asks"]]["reason_code"] == "missing_information"
    assert stored[ids["repair"]]["reason_code"] != "missing_information"


def test_a_statement_that_names_its_value_or_carries_one_still_asks():
    named = "The casing material shall be carbon steel or stainless steel grade 316."
    assert statement_asks.asks_to_state(req(named))
    rated = "Nozzle flanges shall have a minimum pressure rating of Class 300."
    assert statement_asks.asks_to_state(req(rated))
    assert statement_asks.asks_to_state(
        {**req(NOT_ASKING[0]), "raw_value": "Class 300"}
    )
