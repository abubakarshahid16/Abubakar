"""Orders 180.1 item 5: a pump standard for another pump type is not asked of this pump.

API 610 governs centrifugal pumps and API 674 reciprocating ones. A centrifugal
sheet was shown "contractor did not reference API 674 / 675 / 676". The sheet's
own stated type now decides (data in `reference/governing_standards.json`);
when it states none, the engineer is asked, never "missing". Invented sheets.
"""

from __future__ import annotations

import pytest

from app import (
    applicability,
    crs_mapping,
    db,
    equipment_subtype,
    fts_index,
    submittal_review,
)
from app.config import settings

NOW = "2026-10-20T00:00:00Z"
TABLE = None


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "subtype.sqlite")
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


def _sheet(text):
    _doc("sub", "CONTRACTOR_SUBMITTAL", text, equipment_type="Pump")
    return applicability.standards_check("sub", allowed_document_ids=frozenset({"sub"}))


def _ids(rows):
    return sorted(r["identifier"] for r in rows)


# ------------------------------------------------------------------ the table


def test_a_standard_for_another_pump_type_is_not_required_of_a_centrifugal_pump():
    table = applicability.governing_table()
    text = "Centrifugal pump data sheet"
    assert equipment_subtype.classify("pump", "API 610", text, table)[0] == "required"
    assert equipment_subtype.classify("pump", "API 674", text, table)[0] == "other"
    assert equipment_subtype.classify("pump", "api 682", text, table)[0] == "required"
    assert equipment_subtype.identifiers("pump", text, table) == ["API 610", "API 682"]


def test_a_sheet_that_states_no_pump_type_asks_the_engineer_for_every_typed_standard():
    table = applicability.governing_table()
    for std in ("API 610", "API 674", "API 675", "API 676", "API 682"):
        assert (
            equipment_subtype.classify("pump", std, "Pump data sheet", table)[0]
            == "unsure"
        )
    assert equipment_subtype.identifiers("pump", "Pump data sheet", table) == []


def test_a_type_or_standard_the_table_does_not_know_behaves_as_before():
    table = applicability.governing_table()
    assert equipment_subtype.classify("valve", "API 600", "any", table)[0] == "required"
    assert (
        equipment_subtype.classify("pump", "ISO 9906", "Centrifugal", table)[0]
        == "required"
    )


# ------------------------------------------------------- on the standards check


def test_the_check_does_not_ask_a_centrifugal_sheet_for_the_other_pump_standards():
    check = _sheet("Centrifugal pump data sheet. Applicable standard: API 610.")
    assert _ids(check["required"]) == ["API 610", "API 682"]
    assert _ids(check["required_not_cited"]) == ["API 682"]
    assert not any(r.get("unsure") for r in check["required_not_cited"])


def test_a_sheet_with_no_pump_type_gets_engineer_questions_not_missing_rows():
    check = _sheet("Pump data sheet.")
    assert _ids(check["required_not_cited"]) == [
        "API 610",
        "API 674",
        "API 675",
        "API 676",
        "API 682",
    ]
    assert all(r["unsure"] for r in check["required_not_cited"])
    rows = crs_mapping.standards_check_rows(check, "sheet")
    assert rows and all(
        r["comment"].startswith("Engineer to check whether") for r in rows
    )
    assert not any("did not reference" in r["comment"] for r in rows)
    assert "does not state the pump type" in rows[0]["comment"]


def test_a_cited_standard_still_reads_as_before_on_a_typed_sheet():
    check = _sheet("Reciprocating pump data sheet. Applicable standard: API 674.")
    assert _ids(check["required"]) == ["API 674"]
    assert check["required_not_cited"] == []


def test_a_required_standard_the_contractor_did_not_cite_reads_as_before():
    check = _sheet("Centrifugal pump data sheet.")
    rows = crs_mapping.standards_check_rows(check, "sheet")
    plain = [r for r in rows if "API 610" in r["comment"]]
    assert plain and plain[0]["comment"].startswith(
        "Contractor did not reference API 610"
    )


# --------------------------------------------------------------- on the selection


def test_a_standard_for_another_pump_type_is_not_selected_for_the_review():
    for std in ("API 610", "API 674"):
        _doc(
            std.replace(" ", ""), "COMPANY_STANDARD", f"{std} text", document_number=std
        )
    _doc(
        "sub",
        "CONTRACTOR_SUBMITTAL",
        "Centrifugal pump data sheet",
        equipment_type="Pump",
    )
    allowed = frozenset({"sub", "API610", "API674"})
    library = applicability._library(allowed)
    chosen, _missing = applicability.governing_standards("sub", library, allowed)
    assert {v["identifier"] for v in chosen.values()} == {"API 610"}
