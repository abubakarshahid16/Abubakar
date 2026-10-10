"""A standard an equipment type takes only IN PART.

ASME VIII Div 1 governs a relief valve only through its pressure relief device
rules. On the real PSV review (2026-10-10, hand check) two vessel-construction
clauses (openings, castings) were checked against the valve's design pressure
and read COMPLIANT: a "compliant" against a rule that does not apply. Now, on a
review of a type listed in `partial_standards`, only that standard's
requirements about the listed topic are checks; the rest do not apply, with the
reason. Invented documents only.
"""
from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, scope_ledger, standards, subject_scope, submittal_review
from app.config import settings

NOW = "2026-10-10T00:00:00Z"
PARTIAL = {"relief valve": [{"standard": "ASME BPVC Section VIII Division 1",
                             "applies_to": "pressure relief devices",
                             "words": ["pressure relief device", "set pressure", "safety valve"]}]}
LABELS = {"asme": "ASME-Sec-VIII-Div1-2023.pdf", "api": "API-520-I.pdf"}
DEVICE = {"id": "d", "standard_document_id": "asme",
          "requirement_text": "The set pressure of the pressure relief device shall not exceed the MAWP."}
VESSEL = {"id": "v", "standard_document_id": "asme",
          "requirement_text": "The maximum design pressure shall not exceed 350 psi."}
OTHER = {"id": "o", "standard_document_id": "api",
         "requirement_text": "The maximum design pressure shall not exceed 350 psi."}


def test_only_the_parts_a_type_takes_stay_checks():
    out = subject_scope.partial_gate([DEVICE, VESSEL, OTHER], equipment={"relief valve"},
                                     standard_labels=LABELS, partial_standards=PARTIAL)
    assert [r["id"] for r in out["kept"]] == ["d", "o"]      # the device rule, and any other standard
    [item] = out["items"]
    assert item["requirement"]["id"] == "v" and item["code"] == "outside_partial_scope"
    assert "relief valve only in its rules on pressure relief devices" in item["detail"]


def test_a_type_with_no_entry_is_untouched():
    out = subject_scope.partial_gate([DEVICE, VESSEL, OTHER], equipment={"pressure vessel"},
                                     standard_labels=LABELS, partial_standards=PARTIAL)
    assert [r["id"] for r in out["kept"]] == ["d", "v", "o"] and out["items"] == []
    out = subject_scope.partial_gate([VESSEL], equipment=set(), standard_labels=LABELS,
                                     partial_standards=PARTIAL)
    assert out["items"] == []


def test_the_committed_table_lists_asme_viii_for_a_relief_valve():
    from app import applicability
    table = applicability.governing_table()["partial_standards"]
    [entry] = table["relief valve"]
    assert entry["standard"] == "ASME BPVC Section VIII Division 1" and "set pressure" in entry["words"]


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "partial.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, filename, role, **meta):
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                     (doc_id, filename, f"sha-{doc_id}", filename, NOW))
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(f"INSERT INTO document_classification ({','.join(cols)})"
                     f" VALUES ({','.join('?' * len(cols))})", [doc_id, "test", role, *meta.values()])


def _review(equipment_type):
    _doc("asme", "ASME-Sec-VIII-Div1-2023.pdf", "COMPANY_STANDARD")
    _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", equipment_type=equipment_type)
    with db.connect() as conn:
        for cid, doc in (("ac", "asme"), ("fc", "sub")):
            conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
                         "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose',"
                         "'x',1,?,1)", (cid, doc, "f.pdf", f"h-{cid}"))
    ids = {}
    for key, text in (("device", "The set pressure of the pressure relief device shall not exceed 300 psi."),
                      ("vessel", "The maximum design pressure shall not exceed 350 psi.")):
        ids[key] = standards.create_requirement(
            standard_document_id="asme", chunk_id="ac", clause="1", page=1, requirement_text=text,
            source_text=text, structured={"requirement_type": "numeric_limit", "operator": "<=",
                                          "raw_value": "300" if key == "device" else "350", "raw_unit": "psi",
                                          "subject": "set pressure" if key == "device" else "maximum design pressure"})["id"]
    datasheets.create_fact(submittal_document_id="sub", chunk_id="fc", field_label="Design pressure",
                           raw_value="10 barg", page=1)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                     " VALUES (?,?,'pending',?,?)", (run, "sub", NOW, NOW))
        conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
                     "selection_method,included,created_at) VALUES (?,?,?,'rule',1,?)",
                     (str(uuid.uuid4()), run, "asme", NOW))
    result = comparison.run_comparison(run, allowed_document_ids=frozenset({"asme", "sub"}))
    return result, {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}, ids


def test_a_relief_valve_review_does_not_check_vessel_construction_rules(temp_storage):
    result, stored, ids = _review("Pressure Safety Valve")
    assert stored[ids["vessel"]]["state"] == scope_ledger.DOES_NOT_APPLY
    assert stored[ids["vessel"]]["reason_code"] == "outside_partial_scope"
    assert stored[ids["device"]]["state"] == scope_ledger.CHECKED
    # the vessel rule never reads COMPLIANT on a relief valve
    assert not any(f.get("requirement_id") == ids["vessel"] and f.get("compliance_status") == "COMPLIANT"
                   for f in result["findings"])


def test_a_pressure_vessel_review_still_checks_them(temp_storage):
    _result, stored, ids = _review("Pressure Vessel")
    assert stored[ids["vessel"]]["state"] == scope_ledger.CHECKED
