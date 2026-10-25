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
    assert equipment_subtype.identifiers("pump", text, table) == [
        ("API 610", "required"),
        ("API 682", "required"),
    ]


def test_a_sheet_that_states_no_pump_type_asks_the_engineer_for_every_typed_standard():
    table = applicability.governing_table()
    for std in ("API 610", "API 674", "API 675", "API 676", "API 682"):
        assert (
            equipment_subtype.classify("pump", std, "Pump data sheet", table)[0]
            == "unsure"
        )
    assert [
        v for _i, v in equipment_subtype.identifiers("pump", "Pump data sheet", table)
    ] == ["unsure"] * 5


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


def test_a_rotary_seal_or_metering_word_on_a_centrifugal_sheet_does_not_pull_in_other_pump_types():
    table = applicability.governing_table()
    text = "Centrifugal pump data sheet. Rotary seal, metering of flush, end suction casing."
    assert equipment_subtype.classify("pump", "API 676", text, table)[0] == "other"
    assert equipment_subtype.classify("pump", "API 675", text, table)[0] == "other"
    assert equipment_subtype.classify(
        "pump", "API 610", "End suction pump data sheet", table
    )[0] == ("required")
    assert equipment_subtype.classify("pump", "API 676", "Gear pump data sheet", table)[
        0
    ] == ("required")


def test_a_sheet_that_names_two_pump_types_is_unsure_for_both_never_decided_by_one_word():
    table = applicability.governing_table()
    text = "Centrifugal pump data sheet. Spare: reciprocating pump, not supplied."
    assert equipment_subtype.classify("pump", "API 610", text, table)[0] == "unsure"
    assert equipment_subtype.classify("pump", "API 674", text, table)[0] == "unsure"


def test_a_reciprocating_engine_driver_does_not_make_a_centrifugal_pump_reciprocating():
    table = applicability.governing_table()
    text = "Centrifugal pump data sheet. Driver: reciprocating engine."
    assert equipment_subtype.classify("pump", "API 674", text, table)[0] == "other"
    assert equipment_subtype.classify("pump", "API 610", text, table)[0] == "required"


def test_an_unsure_standard_is_selected_held_with_its_own_reason_not_dropped():
    for std in ("API 610", "API 674"):
        _doc(
            std.replace(" ", ""), "COMPANY_STANDARD", f"{std} text", document_number=std
        )
    _doc("sub", "CONTRACTOR_SUBMITTAL", "Pump data sheet", equipment_type="Pump")
    allowed = frozenset({"sub", "API610", "API674"})
    library = applicability._library(allowed)
    chosen, _missing = applicability.governing_standards("sub", library, allowed)
    assert {v["identifier"] for v in chosen.values()} == {"API 610", "API 674"}
    for row in chosen.values():
        assert "held for the engineer" in row["held_for_engineer"]
        assert row["held_code"] == "subtype_unsure"
        assert applicability.is_included(row) is False


def test_the_run_stores_and_says_why_an_unsure_type_standard_was_held():
    import uuid

    from app import held_standards

    monkey = settings.applicability_reasoning_enabled
    settings.applicability_reasoning_enabled = False
    try:
        for std in ("API 610", "API 674"):
            _doc(
                std.replace(" ", ""),
                "COMPANY_STANDARD",
                f"{std} text",
                document_number=std,
            )
        _doc("sub", "CONTRACTOR_SUBMITTAL", "Pump data sheet", equipment_type="Pump")
        run = str(uuid.uuid4())
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                " VALUES (?,?,'pending',?,?)",
                (run, "sub", NOW, NOW),
            )
        allowed = frozenset({"sub", "API610", "API674"})
        applicability.select(
            "sub", allowed_document_ids=allowed, review_run_id=run, persist=True
        )
    finally:
        settings.applicability_reasoning_enabled = monkey
    codes = {
        r["standard_document_id"]: r["held_reason"]
        for r in db.connect().execute(
            "SELECT standard_document_id, held_reason FROM review_applicable_standards"
            " WHERE review_run_id = ?",
            (run,),
        )
    }
    assert codes["API610"] == codes["API674"] == held_standards.HELD_SUBTYPE_UNSURE
    sentence = held_standards.note(run, allowed)["sentence"]
    assert "does not state which type of equipment it is" in sentence
    assert "equipment type is unsure" not in sentence


# ------------------------------------- cloud-3's blockers on cfdec9f0 (21:09Z)


def _select_with_classified_library(sheet_text):
    """A library whose pump standards carry `equipment_type` = Pump: the match
    that is made BEFORE the sub-type table is read."""
    for std in ("API 610", "API 674"):
        _doc(
            std.replace(" ", ""),
            "COMPANY_STANDARD",
            f"{std} text",
            document_number=std,
            equipment_type="Pump",
        )
    _doc("sub", "CONTRACTOR_SUBMITTAL", sheet_text, equipment_type="Pump")
    allowed = frozenset({"sub", "API610", "API674"})
    keep = settings.applicability_reasoning_enabled
    settings.applicability_reasoning_enabled = False
    try:
        out = applicability.select("sub", allowed_document_ids=allowed, persist=False)
    finally:
        settings.applicability_reasoning_enabled = keep
    return {r["identifier"]: r for r in out["selected"]}


def test_a_library_standard_classified_for_pumps_is_not_compared_on_the_wrong_pump_type():
    chosen = _select_with_classified_library("Centrifugal pump data sheet")
    assert "API 674" not in chosen
    assert "held_for_engineer" not in chosen["API 610"]


def test_a_library_standard_classified_for_pumps_is_held_when_the_sheet_states_no_type():
    chosen = _select_with_classified_library("Pump data sheet")
    for std in ("API 610", "API 674"):
        assert chosen[std]["held_code"] == "subtype_unsure"
        assert applicability.is_included(chosen[std]) is False


def test_a_cited_standard_is_never_touched_by_the_sub_type_rule():
    chosen = _select_with_classified_library(
        "Centrifugal pump data sheet. Applicable standard: API 674."
    )
    assert "held_for_engineer" not in chosen["API 674"]


def test_a_bare_type_word_elsewhere_on_a_sheet_does_not_silently_drop_a_standard():
    table = applicability.governing_table()
    text = (
        "Reciprocating compressor data sheet. Suction scrubber: centrifugal separator."
    )
    assert equipment_subtype.classify("compressor", "API 618", text, table)[0] == (
        "required"
    )
    assert equipment_subtype.classify("compressor", "API 617", text, table)[0] == (
        "other"
    )
    bare = "Pump data sheet. Type: Centrifugal."
    assert equipment_subtype.classify("pump", "API 610", bare, table)[0] == "unsure"
    assert equipment_subtype.classify("pump", "API 674", bare, table)[0] == "unsure"


def test_the_standards_left_out_for_a_stated_type_are_listed_in_the_check():
    check = _sheet("Centrifugal pump data sheet. Applicable standard: API 610.")
    assert _ids(check["left_out_by_subtype"]) == ["API 674", "API 675", "API 676"]
    assert "states another pump type" in check["left_out_by_subtype"][0]["reason"]


def test_a_sheet_that_states_no_type_leaves_nothing_out():
    assert _sheet("Pump data sheet")["left_out_by_subtype"] == []
