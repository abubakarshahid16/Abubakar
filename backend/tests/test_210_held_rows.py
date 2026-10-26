"""Order 210 fix 3: a requirement the review held is an engineer-review row (Rule A).

The PF1 items it should catch: vessel D2 (impact test, 8.2) and control valve D2
(fire-safe certificate, 9.3). The standards' sentences are the invented ones."""

from __future__ import annotations

import uuid

import pytest

from app import comparison, datasheets, db, scope_ledger, standards, submittal_review
from app.config import settings

NOW = "2026-10-26T00:00:00Z"


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "held.sqlite")
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


def _review(sentences: dict[str, str], facts: list[tuple[str, str]], equipment: str):
    _doc("std", "COMPANY_STANDARD", "x", document_number="STD-1")
    _doc("sub", "CONTRACTOR_SUBMITTAL", "sheet\n", equipment_type=equipment)
    ids = {}
    for key, text in sentences.items():
        ids[key] = standards.create_requirement(
            standard_document_id="std",
            chunk_id="std-1",
            clause=None,
            page=1,
            requirement_text=text,
            source_text=text,
            structured={"requirement_type": "statement"},
        )["id"]
    for label, value in facts:
        datasheets.create_fact(
            submittal_document_id="sub",
            chunk_id="sub-1",
            field_label=label,
            raw_value=value,
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
    return ids, run, result


def _row(result, rid):
    return [f for f in result["findings"] if f.get("requirement_id") == rid]


def _stored_rows(run, rid):
    with db.connect() as conn:
        return conn.execute(
            "SELECT compliance_status, ai_rationale FROM review_findings"
            " WHERE review_run_id = ? AND requirement_id = ?",
            (run, rid),
        ).fetchall()


def test_a_service_the_sheet_does_not_state_is_an_engineer_row_not_only_a_count():
    # control valve D2 (fire-safe certificate, hydrocarbon service)
    ids, run, result = _review(
        {
            "fire": "A fire-safe certificate shall be stated for valves in hydrocarbon service."
        },
        [("Body material", "Carbon steel")],
        "Control Valve",
    )
    ledger = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}
    assert ledger[ids["fire"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    rows = _row(result, ids["fire"])
    assert len(rows) == 1
    assert rows[0]["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "not compared with the datasheet" in rows[0]["ai_rationale"]
    assert "hydrocarbon" in rows[0]["ai_rationale"]
    stored = _stored_rows(run, ids["fire"])
    assert [r["compliance_status"] for r in stored] == [
        comparison.NEEDS_ENGINEER_REVIEW
    ]


def test_the_row_is_never_a_pass_and_the_ledger_count_does_not_move():
    ids, run, result = _review(
        {
            "fire": "A fire-safe certificate shall be stated for valves in hydrocarbon service."
        },
        [("Body material", "Carbon steel")],
        "Control Valve",
    )
    assert all(
        f["compliance_status"] != comparison.COMPLIANT for f in result["findings"]
    )
    states = [
        d["state"]
        for d in scope_ledger.decisions_for(run)
        if d["requirement_id"] == ids["fire"]
    ]
    assert states == [scope_ledger.APPLIES_NOT_CHECKED]


def test_a_list_that_states_no_requirement_gets_no_row():
    ids, _, result = _review(
        {"list": "Gaskets, bolts, studs, nuts and flange protectors."},
        [("Body material", "Carbon steel")],
        "Control Valve",
    )
    assert _row(result, ids["list"]) == []


def test_which_held_items_become_rows():
    from app import held_findings

    unsure = {
        "requirement": {"id": "r"},
        "code": "applicability_unsure",
        "detail": "Part 2 applies only to magnetic-drive pumps; an engineer decides",
    }
    assert held_findings.eligible(unsure)
    assert held_findings.eligible(
        {"requirement": {"id": "r"}, "code": "service_unknown"}
    )
    assert not held_findings.eligible(
        {"requirement": {"id": "r"}, "code": "text_quality"}
    )
    assert not held_findings.eligible({**unsure, "not_a_requirement": True})
    said = held_findings.verdict(unsure, "fallback")
    assert said["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "magnetic-drive" in said["rationale"] and "fallback" not in said["rationale"]
    assert "fallback" in held_findings.verdict({"code": "x"}, "fallback")["rationale"]


def _plans(n):
    return {
        f"p{i}": f"The seal flush shall follow Plan {30 + i} with a clean fluid."
        for i in range(n)
    }


def test_many_held_clauses_of_one_standard_and_kind_are_one_row_with_the_count():
    _, run, result = _review(_plans(40), [("Seal plan", "Plan 11")], "Pump")
    ledger = [
        d
        for d in scope_ledger.decisions_for(run)
        if d["reason_code"] == "service_unknown"
    ]
    assert len(ledger) == 40  # the ledger still holds every requirement
    rows = [
        f
        for f in result["findings"]
        if f["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    ]
    assert len(rows) == 1
    assert "40 requirements" in rows[0]["ai_rationale"]
    assert "scope ledger" in rows[0]["ai_rationale"]
    assert len(_stored_rows(run, rows[0]["requirement_id"])) == 1


def test_a_few_held_clauses_keep_a_row_each():
    ids, _, result = _review(_plans(3), [("Seal plan", "Plan 11")], "Pump")
    rows = [
        f
        for f in result["findings"]
        if f["compliance_status"] == comparison.NEEDS_ENGINEER_REVIEW
    ]
    assert sorted(f["requirement_id"] for f in rows) == sorted(ids.values())


def test_the_kind_of_hold_decides_the_group():
    from app import held_findings

    assert held_findings.kind_of({"code": "service_unknown"}) == "service"
    assert (
        held_findings.kind_of(
            {"code": "applicability_unsure", "decided_by": "code:scope-not-read"}
        )
        == "part_not_read"
    )
    assert (
        held_findings.kind_of(
            {"code": "applicability_unsure", "decided_by": "ai:m+code"}
        )
        == "scope_unsure"
    )


def test_a_hold_that_is_not_the_division_gates_is_not_called_a_part_scope_hold():
    from app import comparison as cmp_
    from app import held_findings

    held = [
        {
            "requirement": {
                "id": f"r{i}",
                "clause": f"4.{i}",
                "standard_document_id": "std",
            },
            "code": "applicability_unsure",
            "detail": "the datasheet cites this standard for specific clauses only",
            "decided_by": "code",
        }
        for i in range(6)
    ]
    assert {held_findings.kind_of(h) for h in held} == {"other"}
    made = []

    def fake(**kw):
        row = {
            "id": "f",
            "requirement_id": kw["requirement"]["id"],
            "ai_rationale": kw["verdict"]["rationale"],
        }
        made.append(row)
        return row, []

    import app.comparison as c

    original = c._prepare_finding
    c._prepare_finding = fake
    try:
        rows, findings = [], []
        held_findings.add(
            held, {}, rows, findings, ("run", "sub", False, {"std": "STD-1"})
        )
    finally:
        c._prepare_finding = original
    assert len(rows) == 1
    text = rows[0]["ai_rationale"]
    assert "6 requirements of STD-1 were held for reasons that differ" in text
    assert "part of the standard" not in text
    assert cmp_.NEEDS_ENGINEER_REVIEW in text or "Held, not compared" in text
