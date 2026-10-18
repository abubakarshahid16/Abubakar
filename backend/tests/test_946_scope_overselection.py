"""#946, measured (planner 23:54 PKT, reading the real PF1 database read-only):
the ~280 "standards" a real vessel sheet showed were CONSIDERED (semantic
candidates), not included - the real included counts were 7 (pump) and 19
(vessel), and every finding came from an included standard. Applicability's
inclusion policy is NOT the cause and this PR does not change it (an earlier
version of this PR wrongly did - reverted once the real counts came in).

The two real, general causes, both measured on the PF1 database:

1. SPEED: the scope-decision step asks the model about every semantic
   candidate (~260-270 of them per sheet) even though almost all of them end
   up excluded anyway - hours of model calls for candidates nothing was ever
   going to include.
2. NOISE: inside the FEW included standards, about 90% of their requirements
   are not about the datasheet at all (procedures, fabrication, testing -
   another document's scope) and are read as findings anyway, then rejected
   one row at a time downstream as `NOT_IN_DOCUMENT_SCOPE`.

`test_route_counts_reports_every_method_without_writing_anything` proves the
MEASUREMENT TOOL itself (`applicability.route_counts`) on an invented
library, so the same call can be re-run unchanged on a real submittal.

Invented standards and submittals only.
"""
from __future__ import annotations

import pytest

from app import applicability, db, fts_index, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    fts_index.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "", **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-10-13T00:00:00Z')""",
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
            (f"{doc_id}-c1", doc_id, filename, text or filename, f"h-{doc_id}"))
    fts_index.index_document(doc_id)
    return doc_id


def _scope(*ids): return frozenset(ids)


def test_route_counts_reports_every_method_without_writing_anything():
    """THE MEASUREMENT TOOL: a small library where only equipment-matched
    standards are included and the rest carry no classification match at
    all (so they are simply never touched - a library with no indexed text
    produces no semantic candidates either, which is why #946's real
    "~270 semantic candidates" volume is measured on the real corpus with
    `scripts/measure_applicability_routes.py`, not reproduced here)."""
    vessel_ids = [_doc(f"std_v{i}", f"vessel-{i}.pdf", "COMPANY_STANDARD",
                       equipment_type="pressure vessel") for i in range(3)]
    other_ids = [_doc(f"std_o{i}", f"other-{i}.pdf", "COMPANY_STANDARD",
                      equipment_type="rotating equipment") for i in range(20)]
    sub = _doc("sub", "vessel-sheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pressure vessel")
    scope = _scope(sub, *vessel_ids, *other_ids)

    report = applicability.route_counts(sub, allowed_document_ids=scope)

    assert report["library_size"] == 23
    assert report["included"] == 3
    assert report["by_method"][applicability.METHOD_EQUIPMENT] == 3
    # the 20 unrelated standards have no classification match on any field,
    # so no route touches them at all - never silently included, either.
    assert report["no_route_matched"] == 20
    assert report["considered_not_included"] == 0
    # a library smaller than the candidate cap is asked about in full.
    assert report["scope_candidates_asked"] == 23
    # READ-ONLY: nothing was written for a submittal with no review run.
    assert db.connect().execute(
        "SELECT COUNT(*) FROM review_applicable_standards").fetchone()[0] == 0


def test_the_scope_reasoning_cap_asks_about_matched_standards_plus_a_capped_rest(monkeypatch):
    """#946 cause 1 (speed), measured on the real PF1 database: the AI
    scope-reasoning step used to ask about every library standard with a
    stored scope record - PF1 measured ~260-270 of them per sheet, almost
    all ending excluded anyway. It is now capped to what a cheaper route
    already surfaced plus a bounded top-up, never dropping a standard
    another route already found."""
    equip = _doc("std_eq", "vessel.pdf", "COMPANY_STANDARD", equipment_type="pressure vessel")
    # 20 of the 50 share distinctive words with the submittal (so the
    # semantic ranker has more candidates than the remaining cap budget);
    # the other 30 share nothing with it at all.
    overlap = [_doc(f"std_o{i:03d}", f"overlap-{i}.pdf", "COMPANY_STANDARD",
                    text="corrosion allowance nozzle schedule inspection requirements",
                    equipment_type="rotating equipment") for i in range(20)]
    unrelated = [_doc(f"std_u{i:03d}", f"unrelated-{i}.pdf", "COMPANY_STANDARD",
                      text="electrical cabling conduit routing", equipment_type="rotating equipment")
                for i in range(30)]
    sub = _doc("sub", "vessel-sheet.pdf", "CONTRACTOR_SUBMITTAL",
              text="corrosion allowance nozzle schedule inspection requirements",
              equipment_type="pressure vessel")
    scope = _scope(sub, equip, *overlap, *unrelated)

    asked = []

    def fake_scope_decisions_by_reasoning(library, profile, provider=None, heartbeat=None):
        asked.append({entry["id"] for entry in library})
        return {}, None

    monkeypatch.setattr(settings, "applicability_reasoning_enabled", True)
    monkeypatch.setattr(applicability, "scope_decisions_by_reasoning",
                        fake_scope_decisions_by_reasoning)
    monkeypatch.setattr(settings, "applicability_scope_reasoning_candidate_cap", 10)

    report = applicability.route_counts(sub, allowed_document_ids=scope)

    assert len(asked) == 1
    # the equipment-matched standard (already `included`) is always among
    # the candidates asked about - no cheaper route's finding is dropped.
    assert equip in asked[0]
    assert len(asked[0]) == 10
    # the 9 top-up slots came from the overlap-ranked pool, never from the
    # 30 standards sharing nothing with the submittal.
    assert asked[0] - {equip} <= set(overlap)
    assert not (asked[0] & set(unrelated))
    assert report["scope_candidates_asked"] == 10


def test_a_cap_of_zero_disables_the_cap_and_asks_about_the_whole_library(monkeypatch):
    equip = _doc("std_eq", "vessel.pdf", "COMPANY_STANDARD", equipment_type="pressure vessel")
    rest = [_doc(f"std_{i:03d}", f"other-{i}.pdf", "COMPANY_STANDARD",
                equipment_type="rotating equipment") for i in range(5)]
    sub = _doc("sub", "vessel-sheet.pdf", "CONTRACTOR_SUBMITTAL",
              equipment_type="pressure vessel")
    scope = _scope(sub, equip, *rest)
    monkeypatch.setattr(settings, "applicability_reasoning_enabled", True)
    monkeypatch.setattr(settings, "applicability_scope_reasoning_candidate_cap", 0)

    report = applicability.route_counts(sub, allowed_document_ids=scope)

    assert report["scope_candidates_asked"] == report["library_size"] == 6
