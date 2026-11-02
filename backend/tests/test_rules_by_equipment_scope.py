"""Rules by equipment scope: a rule written for another equipment type or document
kind is left out and counted; unknown scope stays in; switch off changes nothing.
Invented standards and rules only."""

# ruff: noqa: F811, I001
from __future__ import annotations

import json

import pytest

from app import db, equipment_scope, scope_ledger
from app.config import settings
from tests.test_partial_standards import temp_storage as review_storage  # noqa: F401
from tests.test_applicability import _doc, temp_storage  # noqa: F401

LABELS = {
    "std_pump": "API 610",
    "std_hx": "API 660",
    "std_gen": "ACME General Practice",
    "std_vessel": "ASME VIII",
}
TABLE = {
    "pump": ["API 610"],
    "heat exchanger": ["API 660"],
}


def _r(rid, std, **extra):
    return {
        "id": rid,
        "standard_document_id": std,
        "requirement_text": "x shall be y",
        **extra,
    }


def _ids(rows):
    return sorted(r["id"] for r in rows)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "rules_by_equipment_scope_enabled", True)


def _gate(reqs, equipment=("heat exchanger",), kind=None):
    return equipment_scope.gate(
        reqs, equipment=set(equipment), kind=kind, standard_labels=LABELS, table=TABLE
    )


def test_exchanger_keeps_exchanger_general_and_unknown_drops_pump_and_vessel(on):
    reqs = [
        _r("hx", "std_hx"),
        _r("gen", "std_gen"),  # no known scope: stays in
        _r("pump", "std_pump"),
        _r("ves", "std_vessel"),
        _r("own_vessel", "std_gen", equipment_type="pressure vessel"),
        _r("own_pump", "std_gen", equipment_type="centrifugal pump"),  # stored type
        _r(
            "own_unclear", "std_gen", equipment_type="gizmo"
        ),  # unreadable type: unknown
    ]
    out = _gate(reqs)
    # a vessel rule (by its standard or its own stored type) stays: an exchanger is built to a
    # vessel code; a rule's own stored type never drops it
    assert _ids(out["kept"]) == [
        "gen",
        "hx",
        "own_pump",
        "own_unclear",
        "own_vessel",
        "ves",
    ]
    assert _ids([i["requirement"] for i in out["items"]]) == ["pump"]
    assert {i["code"] for i in out["items"]} == {"other_equipment_scope"}


def test_note_counts_and_boundary(on):
    reqs = [
        _r("p1", "std_pump"),
        _r("p2", "std_pump"),
        _r("v1", "std_vessel"),
        _r("g", "std_gen"),
        _r("h", "std_hx"),
    ]
    s = _gate(reqs)["summary"]
    assert s["considered"] == 5 and s["left_out"] == 2
    assert s["by_other_scope"] == {"pump": 2}
    assert s["kept_scope_unknown"] == 2
    assert s["note"].startswith("2 rules left out: they apply to pump")
    assert "of the 5 rules of the standards in scope" in s["note"]


def test_unknown_or_unsure_submittal_equipment_drops_nothing(on):
    reqs = [_r("pump", "std_pump"), _r("ves", "std_vessel")]
    out = _gate(reqs, equipment=())
    assert _ids(out["kept"]) == ["pump", "ves"] and out["items"] == []
    assert out["summary"]["kept_submittal_scope_undecided"] == 1
    assert out["summary"]["note"] is None


def test_document_kind_scope(on):
    reqs = [
        _r("ds", "std_gen", document_kind=["datasheet"]),
        _r("proc", "std_gen", document_kind="procedure"),
        _r("free", "std_gen"),
    ]
    out = _gate(reqs, equipment=(), kind="datasheet")
    assert _ids(out["kept"]) == ["ds", "free"]
    assert _ids([i["requirement"] for i in out["items"]]) == ["proc"]
    # kind not decided: nothing is dropped on it
    out = _gate(reqs, equipment=(), kind=None)
    assert out["items"] == []


def test_switch_off_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "rules_by_equipment_scope_enabled", False)
    reqs = [_r("pump", "std_pump"), _r("ves", "std_vessel")]
    out = _gate(reqs)
    assert out["kept"] == reqs and out["items"] == [] and out["summary"] is None
    assert equipment_scope.split_part(out) == {}


def test_a_standard_serving_the_sheet_type_is_never_dropped(on):
    out = _gate(
        [_r("hx", "std_hx", equipment_type="heat exchanger")],
        equipment=("heat exchanger",),
    )
    assert out["items"] == []


def test_split_part_and_ledger_code(on):
    out = _gate([_r("pump", "std_pump")])
    assert equipment_scope.split_part(out)["equipment_scope"]["left_out"] == 1
    assert (
        scope_ledger.REASONS["other_equipment_scope"][0] == scope_ledger.DOES_NOT_APPLY
    )


def test_shipped_table_lists_pump_only_standards():
    table = equipment_scope.scope_only_table()
    assert "API 610" in table["pump"] and "API 660" in table["heat exchanger"]


@pytest.mark.parametrize(
    "state,guess,expected",
    [
        ("confirmed", False, "procedure"),
        ("suggested", False, "procedure"),
        ("suggested", True, None),
        ("confirmed", True, "procedure"),
        ("needs_engineer", False, None),
    ],
)
def test_submittal_kind_only_when_decided(temp_storage, state, guess, expected):
    _doc("d1", "d.pdf", "CONTRACTOR_SUBMITTAL")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, evidence, routed_at)"
            " VALUES ('d1','procedure',?,?, '2026-11-01')",
            (state, json.dumps({"guess": guess})),
        )
    assert equipment_scope.submittal_kind("d1") == expected
    assert equipment_scope.submittal_kind("missing") is None


# ------------------------------------------- the real review path (wiring in comparison)


def _review(equipment_type, standard_file, design_code=None):
    import uuid

    from app import comparison, datasheets, standards
    from tests.test_partial_standards import NOW
    from tests.test_partial_standards import _doc as _pdoc

    _pdoc("std", standard_file, "COMPANY_STANDARD")
    _pdoc("sub", "sheet.pdf", "CONTRACTOR_SUBMITTAL", equipment_type=equipment_type)
    with db.connect() as conn:
        for cid, doc in (("ac", "std"), ("fc", "sub")):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
                "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose',"
                "'x',1,?,1)",
                (cid, doc, "f.pdf", f"h-{cid}"),
            )
    text = "The design pressure shall not exceed 300 psi."
    rid = standards.create_requirement(
        standard_document_id="std",
        chunk_id="ac",
        clause="1",
        page=1,
        requirement_text=text,
        source_text=text,
        structured={
            "requirement_type": "numeric_limit",
            "operator": "<=",
            "raw_value": "300",
            "raw_unit": "psi",
            "subject": "design pressure",
        },
    )["id"]
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="fc",
        field_label="Design pressure",
        raw_value="10 barg",
        page=1,
    )
    if design_code:
        datasheets.create_fact(
            submittal_document_id="sub",
            chunk_id="fc",
            field_label="Design code",
            raw_value=design_code,
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
            "selection_method,included,created_at) VALUES (?,?,?,'rule',1,?)",
            (str(uuid.uuid4()), run, "std", NOW),
        )
    result = comparison.run_comparison(
        run, allowed_document_ids=frozenset({"std", "sub"})
    )
    return (
        result,
        {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)},
        rid,
    )


def test_review_leaves_out_a_pump_standard_rule_on_an_exchanger_and_counts_it(
    review_storage, monkeypatch
):
    monkeypatch.setattr(settings, "rules_by_equipment_scope_enabled", True)
    result, stored, rid = _review("Heat Exchanger", "API-610.pdf")
    assert stored[rid]["reason_code"] == "other_equipment_scope"
    assert stored[rid]["state"] == scope_ledger.DOES_NOT_APPLY
    note = result["requirement_split"]["equipment_scope"]
    assert note["left_out"] == 1 and note["considered"] == 1
    assert note["note"].startswith("1 rules left out: they apply to pump")


def test_review_switch_off_does_not_leave_it_out(review_storage, monkeypatch):
    monkeypatch.setattr(settings, "rules_by_equipment_scope_enabled", False)
    result, stored, rid = _review("Heat Exchanger", "API-610.pdf")
    assert stored[rid]["reason_code"] != "other_equipment_scope"
    assert "equipment_scope" not in result["requirement_split"]


def test_the_count_and_its_boundary_reach_the_run_summary_lines(on):
    from app import absence

    out = _gate([_r("p1", "std_pump"), _r("g", "std_gen")])
    outcome = {"requirement_split": equipment_scope.split_part(out)}
    (line,) = equipment_scope.lines(outcome)
    assert "1 rules left out: they apply to pump" in line["line"]
    assert "of the 2 rules of the standards in scope" in line["line"]
    assert equipment_scope.lines({"requirement_split": {}}) == []
    assert equipment_scope.lines(None) == []
    # wired into the summary the engineer reads, as kind_rules is
    parts = absence.unchecked_parts(run_status="completed", outcome=outcome)
    assert any(
        p.get("part") == "equipment_scope" and p["line"] == line["line"] for p in parts
    )
