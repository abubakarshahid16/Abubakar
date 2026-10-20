"""Orders 180.1 item 6: a standard the run judged not applicable is never used as support.

A pump sheet cites a pressure-vessel code. The standards check says "cited but does
not appear to apply"; the same run must not then quote that code's clauses under other
rows. It is HELD for the engineer instead. Invented standards and sheets only.
"""

from __future__ import annotations

import pytest

from app import applicability, db, fts_index, standard_judgment, submittal_review
from app.config import settings

NOW = "2026-10-20T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "judged.sqlite")
    monkeypatch.setattr(settings, "applicability_reasoning_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    fts_index.ensure_schema()
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
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,1,1,1,NULL,'prose',"
            "?,1,?,1)",
            (f"{doc_id}-1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
        )
    fts_index.index_document(doc_id)


def _select(sheet_text):
    _doc(
        "vessel",
        "COMPANY_STANDARD",
        "pressure vessel code",
        document_number="ASME VIII",
    )
    _doc("pump", "COMPANY_STANDARD", "centrifugal pump code", document_number="API 610")
    _doc("sub", "CONTRACTOR_SUBMITTAL", sheet_text, equipment_type="Pump")
    allowed = frozenset({"vessel", "pump", "sub"})
    out = applicability.select("sub", allowed_document_ids=allowed, persist=False)
    return {r["standard_document_id"]: r for r in out["selected"]}, out[
        "standards_check"
    ]


def test_a_cited_standard_the_check_judged_not_applicable_is_held_not_included():
    rows, check = _select(
        "Centrifugal pump data sheet. Design code: ASME VIII. Applicable: API 610."
    )
    assert any("ASME" in r["identifier"] for r in check["cited_not_applicable"])
    assert rows["vessel"]["included"] is False
    assert "judged it not applicable" in rows["vessel"]["held_for_engineer"]
    assert rows["pump"]["included"] is True


def test_the_standard_the_equipment_takes_is_untouched():
    rows, _check = _select("Centrifugal pump data sheet. Applicable: API 610.")
    assert rows["pump"]["included"] is True
    assert "held_for_engineer" not in rows["pump"]


def test_the_helper_marks_only_listed_standards_and_never_overwrites_a_hold():
    selected = {
        "a": {"method": "referenced"},
        "b": {"method": "referenced", "held_for_engineer": "x"},
    }
    check = {
        "cited_not_applicable": [
            {"identifier": "A", "reason": "r1"},
            {"identifier": "B", "reason": "r2"},
        ]
    }
    find = lambda _lib, ident: {"id": ident.lower()}  # noqa: E731
    standard_judgment.hold(selected, check, [], find)
    assert "r1" in selected["a"]["held_for_engineer"]
    assert selected["b"]["held_for_engineer"] == "x"
    assert standard_judgment.hold({}, {}, [], find) is None
