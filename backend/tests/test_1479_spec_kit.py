"""#1479 (preparation): the specification kit. Invented specification and datasheet only
(CLAUDE.md rule 3). No model, no socket. Each test fails without the code it names.
"""

from __future__ import annotations

import json

import pytest

from app import access, db, review_jobs, spec_kit
from app.config import settings
from tests.test_b3_page_ledger import NOW, _review, temp_storage  # noqa: F401 - autouse

SPEC_PAGE1 = (
    "Scope. This specification covers the design and fabrication of pressure vessel V-100. "
    "Design pressure shall be 12 bar. The vessel is designed to ASME Section VIII Division 1."
)
SPEC_PAGE2 = (
    "Corrosion allowance is 3 mm. The hydrostatic test shall be witnessed by the purchaser. "
    "Design temperature is 200 degC."
)


@pytest.fixture(autouse=True)
def _resolver():
    yield
    access.set_user_resolver(None)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "spec_kit_enabled", True)


def _doc(doc_id, pages, kind, *, number=None, tags=(), equipment="pressure vessel"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'x','ready',?,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", len(pages), NOW),
        )
        for n, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (doc_id, n, text, len(text)),
            )
        conn.execute(
            "INSERT INTO document_kinds (document_id,kind,state,routed_at) VALUES (?,?,?,?)",
            (doc_id, kind, "confirmed", NOW),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, equipment_type, document_number,"
            " equipment_tags, suggested_by) VALUES (?,?,?,?,'test')",
            (doc_id, equipment, number, json.dumps(list(tags))),
        )


def _datasheet(
    doc_id="doc_ds", *, number="DS-V100", tags=("V-100",), pressure="10", page=2
):
    _doc(
        doc_id,
        ["Datasheet V-100", "Pressure vessel data"],
        "datasheet",
        number=number,
        tags=tags,
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO submittal_facts (id,submittal_document_id,field_name,field_label,field_value,"
            "raw_unit,unit,page,created_at,updated_at,is_blank) VALUES (?,?,?,?,?,?,?,?,?,?,0)",
            (
                f"f-{doc_id}",
                doc_id,
                "design_pressure",
                "Design pressure",
                pressure,
                "bar",
                "bar",
                page,
                NOW,
                NOW,
            ),
        )
    return doc_id


def _world(kind="specification", pages=(SPEC_PAGE1, SPEC_PAGE2), datasheet=None, **kw):
    sub = "doc_spec"
    _doc(sub, list(pages), kind, number="SPEC-V100", tags=("V-100",), **kw)
    extra = _datasheet(**datasheet) if datasheet is not None else None
    run, scope = _review(sub)
    return sub, run, frozenset(scope | ({extra} if extra else set()))


def _rows(run):
    return [
        dict(r)
        for r in db.connect().execute(
            "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = ? ORDER BY ai_rationale",
            (run, spec_kit.ORIGIN),
        )
    ]


def test_kits_name_held_and_draft_items_and_say_draft():
    kit = spec_kit.kits()
    assert set(kit) == {"pressure_vessel", "piping", "welding", "instrumentation"}
    for name, k in kit.items():
        held, draft = spec_kit.held_count(k)
        assert "DRAFT" in k["label"] and held >= 1 and draft >= 3, name
        for item in k["items"]:
            assert bool(item.get("held")) != bool(item.get("draft_reason")), item["id"]
            if item.get("held"):
                assert (
                    item["held"]["standard"].startswith("SAES-")
                    and item["held"]["page"] > 0
                )


def test_found_items_are_engineer_rows_with_page_and_a_verified_quote(on):
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    rows = {r["requirement"]: r for r in _rows(run)}
    pressure = next(r for k, r in rows.items() if "Design pressure" in k)
    assert pressure["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert pressure["contractor_page"] == 1
    assert (
        "covered on page 1" in pressure["finding"]
        and "engineer to confirm" in pressure["finding"]
    )
    assert "DRAFT item" in pressure["finding"]
    assert pressure["contractor_evidence_text"] in SPEC_PAGE1
    corrosion = next(r for k, r in rows.items() if "Corrosion" in k)
    assert corrosion["contractor_page"] == 2


def test_items_not_found_are_counted_in_one_note_and_never_missing_information(on):
    from app import crs_mapping

    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    rows = _rows(run)
    unfound = [r for r in rows if r["ai_rationale"].startswith(spec_kit.NOT_FOUND)]
    kit = spec_kit.kits()["pressure_vessel"]
    assert len(unfound) >= 3 and len(rows) == len(kit["items"])
    notes = spec_kit.notes(rows)
    assert len(notes) == 1 and notes[0]["count"] == len(unfound)
    assert "DRAFT" in notes[0]["detail"]
    assert {r["compliance_status"] for r in rows} == {"NEEDS_ENGINEER_REVIEW"}
    assert all(r["contractor_page"] is None for r in unfound)
    # the CRS: one note, no line per unfound item
    built = crs_mapping.build_crs_rows(rows, [], "spec.pdf")
    assert len([b for b in built if b.get("row_kind") == "spec_kit"]) == len(
        rows
    ) - len(unfound)


def test_a_specification_is_never_compliant_or_missing_information(on):
    _sub, run, scope = _world(datasheet={})
    spec_kit.for_review(run, scope)
    statuses = {r["compliance_status"] for r in _rows(run)}
    assert statuses == {"NEEDS_ENGINEER_REVIEW"}


def test_numeric_mismatch_with_the_datasheet_is_a_row_with_both_pages(on):
    _sub, run, scope = _world(datasheet={"pressure": "10", "page": 2})
    spec_kit.for_review(run, scope)
    mismatch = [
        r for r in _rows(run) if r["ai_rationale"].startswith(spec_kit.MISMATCH)
    ]
    assert len(mismatch) == 1
    text = mismatch[0]["finding"]
    assert (
        "specification says 12 bar (page 1)" in text
        and "datasheet DS-V100 says 10 bar (page 2)" in text
    )
    assert mismatch[0]["compliance_status"] == "NEEDS_ENGINEER_REVIEW"


def test_the_same_value_in_another_unit_is_not_a_mismatch(on):
    # 1.2 MPa is 12 bar: the unit code converts, so no row
    pages = (SPEC_PAGE1.replace("12 bar", "1.2 MPa"), SPEC_PAGE2)
    _sub, run, scope = _world(pages=pages, datasheet={"pressure": "12"})
    spec_kit.for_review(run, scope)
    assert [
        r for r in _rows(run) if r["ai_rationale"].startswith(spec_kit.MISMATCH)
    ] == []


def test_a_datasheet_is_matched_by_number_or_tag_only_and_inside_the_scope(on):
    sub, run, scope = _world(datasheet={"number": "DS-OTHER", "tags": ("P-9",)})
    spec_kit.for_review(run, scope)
    assert [
        r for r in _rows(run) if r["ai_rationale"].startswith(spec_kit.MISMATCH)
    ] == []
    assert spec_kit.matching_datasheets(sub, scope) == []


def test_a_matching_datasheet_outside_the_review_scope_is_not_looked_at(on):
    sub, run, scope = _world(datasheet={"pressure": "10"})
    assert spec_kit.matching_datasheets(sub, scope) == ["doc_ds"]
    outside = scope - {"doc_ds"}
    assert spec_kit.matching_datasheets(sub, outside) == []
    spec_kit.for_review(run, outside)
    assert [
        r for r in _rows(run) if r["ai_rationale"].startswith(spec_kit.MISMATCH)
    ] == []


def test_switch_off_changes_nothing():
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    assert _rows(run) == []


@pytest.mark.parametrize("kind", ["datasheet", "procedure"])
def test_only_a_specification_is_run(on, kind):
    _sub, run, scope = _world(kind=kind)
    spec_kit.for_review(run, scope)
    assert _rows(run) == []


def test_a_rerun_replaces_undecided_rows_and_not_an_engineers(on):
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    first = len(_rows(run))
    decided = _rows(run)[0]["id"]
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET engineer_comment = 'seen' WHERE id = ?",
            (decided,),
        )
    spec_kit.for_review(run, scope)
    ids = [r["id"] for r in _rows(run)]
    assert decided in ids and len(ids) == first + 1


def test_rows_are_not_in_a_headline(on):
    from app import clause_review

    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    findings = [{"origin": spec_kit.ORIGIN}, {"origin": None}]
    assert clause_review.without_rows(findings) == [{"origin": None}]


def test_the_review_job_runs_it_after_the_other_checks(monkeypatch):
    calls = []
    monkeypatch.setattr(review_jobs, "_ai_check", lambda *a: calls.append("ai"))
    monkeypatch.setattr(review_jobs, "_web_check", lambda *a: calls.append("web"))
    monkeypatch.setattr(spec_kit, "for_review", lambda *a: calls.append("spec"))
    review_jobs._checks("r", frozenset(), [])
    assert calls == ["ai", "web", "spec"]


def test_a_failure_never_fails_the_review(on, monkeypatch):
    _sub, run, scope = _world()
    monkeypatch.setattr(spec_kit, "rows_for", lambda *a: 1 / 0)
    spec_kit.for_review(run, scope)
    assert _rows(run) == []


def test_a_specification_of_no_discipline_says_so_in_one_note(on):
    from app import crs_mapping

    _sub, run, scope = _world(equipment="cable tray")
    with db.connect() as conn:
        conn.execute("UPDATE documents SET filename = 'doc.pdf'")
    spec_kit.for_review(run, scope)
    rows = _rows(run)
    assert len(rows) == 1 and rows[0]["ai_rationale"].startswith(spec_kit.NOT_RUN)
    notes = spec_kit.notes(rows)
    assert [n["note"] for n in notes] == [spec_kit.NOT_RUN_NOTE]
    assert "equipment type, title, file name" in notes[0]["note"]
    built = crs_mapping.build_crs_rows(rows, [], "spec.pdf")
    assert [b for b in built if b.get("row_kind") == "spec_kit"] == []


def _mismatches(spec_text, fact_value="10", unit="bar"):
    pages = [(1, spec_text)]
    facts = [
        {
            "field_label": "Design pressure",
            "field_name": "design_pressure",
            "field_value": fact_value,
            "raw_unit": unit,
            "unit": unit,
            "page": 2,
        }
    ]
    return spec_kit.numeric_rows(pages, facts, "datasheet D1", "doc_d1")


def test_two_numbers_of_one_quantity_in_a_sentence_make_no_row():
    for text in (
        "Design pressure shall be 10 bar and hydrotest pressure 15 bar.",
        "Hydrotest pressure is 15 bar and design pressure shall be 10 bar.",
    ):
        assert _mismatches(text) == []


def test_a_minimum_is_met_by_a_higher_datasheet_value_and_missed_by_a_lower():
    assert _mismatches("Design pressure shall be not less than 8 bar.") == []
    rows = _mismatches("Design pressure shall be not less than 12 bar.")
    assert len(rows) == 1 and "12 bar" in rows[0]["finding"]


def test_a_maximum_is_met_by_a_lower_datasheet_value_and_missed_by_a_higher():
    assert _mismatches("Design pressure shall not exceed 12 bar.") == []
    rows = _mismatches("Design pressure shall not exceed 8 bar.")
    assert len(rows) == 1 and "datasheet D1 says 10 bar" in rows[0]["finding"]


def test_each_matched_datasheet_is_named_and_its_row_is_unique(on):
    _sub, run, scope = _world(datasheet={"pressure": "10", "number": "DS-A"})
    _datasheet("doc_ds2", number="DS-B", pressure="9", page=3)
    spec_kit.for_review(run, scope | {"doc_ds2"})
    rows = [r for r in _rows(run) if r["ai_rationale"].startswith(spec_kit.MISMATCH)]
    assert len(rows) == 2
    assert len({r["requirement_id"] for r in rows}) == 2
    text = " ".join(r["finding"] for r in rows)
    assert "datasheet DS-A" in text and "datasheet DS-B" in text
