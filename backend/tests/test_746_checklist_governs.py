"""#746 part 2: when the submittal's equipment type has a review checklist, the
library requirements of the standards that checklist CITES are not checked one
by one - the checklist items are. Planner decision on #746: a fourth group,
"not used: the checklist governs", shown with its count and kept out of the
unchecked share; GUARDED to the checklist's own `source.standard`s; generic by
type (a type with no checklist is unchanged). Invented documents only.
"""
from __future__ import annotations

import uuid

import pytest

from app import absence, comparison, datasheets, db, scope_ledger, standards, submittal_review
from app.config import settings

NOW = "2026-10-10T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "governs.sqlite")
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
    return doc_id


def _chunk(chunk_id, doc_id):
    with db.connect() as conn:
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                     "section,kind,text,token_count,content_hash,retrievable)"
                     " VALUES (?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
                     (chunk_id, doc_id, "f.pdf", f"h-{chunk_id}"))
    return chunk_id


def _req(std, chunk, text):
    return standards.create_requirement(
        standard_document_id=std, chunk_id=chunk, clause="5.1", page=1, requirement_text=text,
        source_text=text, structured={"requirement_type": "statement"})["id"]


def _review(equipment_type):
    """A submittal of `equipment_type`, two applicable standards: one the relief
    valve checklist cites (API 520-I, by its file name) and one it does not."""
    cited = _doc("cited", "API-520-I.pdf", "COMPANY_STANDARD")
    other = _doc("other", "SPEC-X-valves.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", equipment_type=equipment_type)
    cc, oc, fc = _chunk("cc", cited), _chunk("oc", other), _chunk("fc", sub)
    cell = standards.create_requirement(
        standard_document_id=cited, chunk_id=cc, clause="5.2", page=1,
        requirement_text="Orifice J - Effective area: 1.287", source_text="Orifice J - Effective area: 1.287",
        structured={"requirement_type": "table_value", "condition": "Orifice J",
                    "field": "Effective area", "raw_value": "1.287"})["id"]
    ids = {"cell": cell,
           "cited_1": _req(cited, cc, "The valve shall be sized for the relieving rate."),
           "cited_2": _req(cited, cc, "Built-up back pressure shall be evaluated."),
           "other": _req(other, oc, "The body shall be cast steel.")}
    datasheets.create_fact(submittal_document_id=sub, chunk_id=fc, field_label="Set pressure",
                           raw_value="9 barg", page=1)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,"
                     "updated_at) VALUES (?,?,'pending',?,?)", (run, sub, NOW, NOW))
        for std in (cited, other):
            conn.execute("INSERT INTO review_applicable_standards (id,review_run_id,"
                         "standard_document_id,selection_method,included,created_at)"
                         " VALUES (?,?,?,'rule',1,?)", (str(uuid.uuid4()), run, std, NOW))
    scope = frozenset({cited, other, sub})
    result = comparison.run_comparison(run, allowed_document_ids=scope)
    stored = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}
    return result, stored, ids


def test_the_checklist_governs_only_the_standards_it_cites():
    result, stored, ids = _review("Pressure Safety Valve")
    for key in ("cited_1", "cited_2"):
        assert stored[ids[key]]["state"] == scope_ledger.NOT_USED
        assert stored[ids[key]]["reason_code"] == "covered_by_checklist"
    # (a) the GUARD: a requirement from a standard the checklist does not cite is still checked
    assert stored[ids["other"]]["state"] == scope_ledger.CHECKED
    split = result["requirement_split"]
    assert split["not_used"] == 3 and split["checked"] == 1     # 2 statements + 1 table cell
    assert split["checklist"]["type"] == "Pressure Safety Valve"
    # never in the unchecked share
    assert split["applies_not_checked"] == 0 and split["unchecked_share"] == 0.0
    line = absence.split_lines(split)[0]
    assert line.startswith("Reviewed against the Pressure Safety Valve checklist (")
    assert "3 library requirement(s)" in line


def test_a_type_with_no_checklist_is_unchanged():
    # (b) generic by type: no checklist, the normal library path for every standard
    result, stored, ids = _review("Pressure Vessel")
    # nothing is "not used"; every requirement took the normal path (the subject
    # gate may still say a valve clause is about other equipment - its own call)
    assert not any(d["state"] == scope_ledger.NOT_USED for d in stored.values())
    assert stored[ids["other"]]["state"] == scope_ledger.CHECKED
    split = result["requirement_split"]
    assert split["not_used"] == 0 and "checklist" not in split and split["total"] == 4
    assert not any(line.startswith("Reviewed against") for line in absence.split_lines(split))


def test_the_cited_standard_is_found_by_its_identifier_not_a_list_in_code():
    _doc("a", "API RP 520 Pt-1 (2014).pdf", "COMPANY_STANDARD")
    _doc("b", "API-520-II.pdf", "COMPANY_STANDARD")
    _doc("c", "API-521.pdf", "COMPANY_STANDARD")
    assert comparison.governed_standards(["a", "b", "c"], ["API 520-I"]) == {"a"}
    assert comparison.governed_standards(["a", "b", "c"], []) == set()


def test_a_governed_standards_table_cell_no_field_answers_is_not_used_not_unchecked():
    """A table cell of a cited standard that no datasheet field answers would
    count as "applies, not checked"; under the checklist it is "not used"."""
    _result, stored, ids = _review("Pressure Safety Valve")
    assert stored[ids["cell"]]["state"] == scope_ledger.NOT_USED
    _result, stored, ids = _review_again("Pressure Vessel")
    assert stored[ids["cell"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED   # no checklist: unchanged


def _review_again(equipment_type):
    db.reset_connection()
    import os
    os.remove(settings.db_path)
    db.init_db(); submittal_review.ensure_schema(); submittal_review.migrate_facts_to_per_document()
    return _review(equipment_type)


def test_a_review_with_a_checklist_states_its_reader_coverage():
    """Planner 2026-10-10: every checklist review says how many of its fields
    were read, and how many are on the sheet but were not read."""
    result, _stored, _ids = _review("Pressure Safety Valve")
    cov = result["requirement_split"]["checklist_coverage"]
    assert cov["fields"] > 0 and cov["read"] <= cov["fields"]
