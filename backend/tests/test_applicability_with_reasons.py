"""Applicability with reasons (B5, per the master order): every standard in
the library classified for one submittal into exactly one of four buckets -
applicable and assessable, applicable but needs another document, not
applicable (with a reason), or unknown.

Mutations: `python scripts/mutation_check.py --phase 61`.
"""
from __future__ import annotations

import pytest

from app import applicability, db, keyword, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "", **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename))
        columns = ["document_id", "suggested_by", "document_role", *meta]
        values = [doc_id, "test", role, *meta.values()]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})", values)
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, filename, text or filename,
             f"h-{doc_id}"))
    keyword.index_document(doc_id)
    return doc_id


def _requirement(req_id: str, standard_document_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO standard_requirements
                (id, standard_document_id, clause, page, requirement_text,
                 source_text, category, requirement_type, extraction_method,
                 created_at, updated_at)
               VALUES (?,?,?,?,?,?,'requirement','numeric_limit','test',
                       '2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (req_id, standard_document_id, "5.1", 3,
             "Design pressure shall not exceed 50 barg.",
             "Design pressure shall not exceed 50 barg."))


def _scope(*ids): return frozenset(ids)


def _status_of(rows, document_number):
    return next(r for r in rows if r["document_number"] == document_number)


def test_a_selected_standard_with_requirements_is_applicable_assessable():
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
              document_number="API 610", equipment_type="pump")
    _requirement("req1", "std_610")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pump")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "API 610")
    assert row["status"] == applicability.STATUS_APPLICABLE_ASSESSABLE
    assert "equipment_type" in row["reason"] or "equipment type" in row["reason"]


def test_a_selected_standard_with_no_requirements_needs_another_document():
    """THE MUTATION TARGET: a standard this system selected but has not yet
    extracted anything from cannot honestly be called "assessable" - there
    is nothing here to compare the submittal against."""
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
              document_number="API 610", equipment_type="pump")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pump")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "API 610")
    assert row["status"] == applicability.STATUS_APPLICABLE_NEEDS_ANOTHER_DOCUMENT
    assert "no requirements have been extracted" in row["reason"]


def test_a_standard_with_a_conflicting_attribute_is_not_applicable_with_a_reason():
    """THE MUTATION TARGET: a real, stated mismatch - not a guess."""
    std = _doc("std_elec", "SAES-P-100.pdf", "COMPANY_STANDARD",
              document_number="SAES-P-100", equipment_type="transformer")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pump")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "SAES-P-100")
    assert row["status"] == applicability.STATUS_NOT_APPLICABLE
    assert "transformer" in row["reason"] and "pump" in row["reason"]


def test_a_standard_with_no_comparable_fields_is_unknown_not_not_applicable():
    """THE MUTATION TARGET: a standard recording no equipment_type,
    discipline, service or project of its own cannot honestly be called
    "not applicable" - this system has nothing to compare it against."""
    std = _doc("std_bare", "SAES-X-001.pdf", "COMPANY_STANDARD",
              document_number="SAES-X-001")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pump")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "SAES-X-001")
    assert row["status"] == applicability.STATUS_UNKNOWN


def test_a_submittal_with_no_profile_at_all_makes_every_unselected_standard_unknown():
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
              document_number="API 610", equipment_type="pump")
    sub = _doc("sub", "unclassified.pdf", "CONTRACTOR_SUBMITTAL")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "API 610")
    assert row["status"] == applicability.STATUS_UNKNOWN


def test_a_field_blank_on_one_side_is_never_reported_as_a_stated_mismatch():
    """THE MUTATION TARGET: a field only ONE side records is not evidence of
    a conflict - only a field BOTH sides state, and disagree on, may be
    reported as a mismatch. The standard here records a service the
    submittal does not; that silence must not be reported as a clash."""
    std = _doc("std_x", "SAES-X-002.pdf", "COMPANY_STANDARD",
              document_number="SAES-X-002", equipment_type="transformer",
              service="sour service")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pump")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "SAES-X-002")
    assert row["status"] == applicability.STATUS_NOT_APPLICABLE
    assert "service" not in row["reason"]


def test_a_discipline_committee_name_never_produces_a_false_mismatch():
    """THE REAL BUG FOUND BY THE OWNER'S SPOT-CHECK (2026-09-25): a
    standard's `discipline` is the COMMITTEE that owns it ("Piping
    Standards Committee"), read verbatim off its cover page. A submittal's
    `discipline` is a broad CATEGORY ("Mechanical"), read off its own title
    block. These are different vocabularies - comparing them can only ever
    produce a false "does not match", never a true confirmation. 9 of 10
    sampled not_applicable verdicts on the real corpus were exactly this:
    a Piping-committee standard reported not applicable to a Mechanical
    submittal. `discipline` must never appear in a stated mismatch."""
    std = _doc("std_piping", "SAES-L-150.pdf", "COMPANY_STANDARD",
              document_number="SAES-L-150", equipment_type="pump",
              discipline="Piping Standards Committee")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pump", discipline="Mechanical")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "SAES-L-150")
    # equipment_type matches on both sides here, so nothing is even a
    # candidate mismatch - but the point stands for any standard whose
    # discipline alone would otherwise have looked like a conflict.
    assert "discipline" not in row["reason"]
    assert "Committee" not in row["reason"]


def test_a_standard_known_only_by_its_committee_discipline_is_unknown():
    """THE MUTATION TARGET: a standard recording ONLY a committee-shaped
    discipline (no equipment_type/service/project of its own) has nothing
    this system can actually compare - UNKNOWN, not a false NOT_APPLICABLE
    manufactured from a vocabulary that was never comparable."""
    std = _doc("std_piping", "SAES-L-150.pdf", "COMPANY_STANDARD",
              document_number="SAES-L-150",
              discipline="Piping Standards Committee")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pump", discipline="Mechanical")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "SAES-L-150")
    assert row["status"] == applicability.STATUS_UNKNOWN


def test_a_cited_standard_is_applicable_regardless_of_attributes():
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
              document_number="API 610")
    _requirement("req1", "std_610")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL",
              text="Pump shall comply with API 610.")
    rows = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(std, sub))
    row = _status_of(rows, "API 610")
    assert row["status"] == applicability.STATUS_APPLICABLE_ASSESSABLE
    assert "API 610" in row["reason"]
