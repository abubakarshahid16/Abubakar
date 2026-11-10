# ruff: noqa: F811 - pytest fixtures imported by name
"""Owner order 10 Nov 2026, step 4 (#805 Cycle 2): CRS routing by the stored hold reason, behind
CRS_ROUTING_BY_HOLD_REASON_ENABLED (off). Invented findings, standards and documents only; no model.

Each rule moves exactly its rows and nothing else; switch off, the workbook is the one main made;
"By Contractor" (deferred_marker) and two-value applicability rows stay; the internal list and the
Review notes show the reason; a row with no hold code is untouched."""

from __future__ import annotations

import io
import zipfile

import openpyxl
import pytest

from app import compliance_list as cl
from app import crs_export, crs_mapping, crs_routing, export_status, hold_reason
from app.config import settings
from app.datasheet_checks import DRAFT_MARK

STATED, PLACEHOLDER = (
    {"field_value": "12 barg"},
    {"field_value": "10 barg By Contractor"},
)


def held(code, n=None, **over):
    """A held datasheet-check finding with the stored hold code `code` (None: no code)."""
    n = n or str(code)
    base = {
        "id": f"f-{n}",
        "origin": "datasheet_check",
        "compliance_status": "NEEDS_ENGINEER_REVIEW",
        "hold_reason_code": code,
        "standard_clause": f"4.{len(n)}",
        "standard_name": "INVENTED-STD 1",
        "contractor_section": f"Invented field {n}",
        "contractor_page": 1,
        "contractor_evidence_text": "12 barg",
        "fact_id": f"fact-{n}",
        "requirement": f"Invented requirement {n} ({DRAFT_MARK})",
        "finding": f"Datasheet check {n}: could not be checked.",
    }
    return {**base, **over}


CHECK = {
    "required_not_cited": [
        {
            "identifier": "API 991",
            "by": "equipment type",
            "reason": "it governs an invented pump",
        },
        {
            "identifier": "API 992",
            "by": "equipment type",
            "reason": "x",
            "unsure": True,
            "governs": ["pump"],
            "kind": "pump",
        },
    ],
    "cited_not_applicable": [
        {"identifier": "API 993", "reason": "it governs only an invented compressor"},
    ],
}


@pytest.fixture
def switch(monkeypatch):
    facts = {"fact-R3": STATED, "fact-R3tba": PLACEHOLDER, "fact-R3nodraft": STATED}
    monkeypatch.setattr(crs_routing, "_fact", facts.get)
    monkeypatch.setattr(crs_routing, "_kept_keys", lambda rows, run_id, scope: set())
    monkeypatch.setattr(
        crs_routing, "_spec_requires", lambda run_id, allowed: lambda ident: False
    )

    def set_(value=True, compliance=False):
        monkeypatch.setattr(settings, "crs_routing_by_hold_reason_enabled", value)
        monkeypatch.setattr(settings, "crs_compliance_list_enabled", compliance)

    set_(False)
    return set_


def everything():
    return [
        held(hold_reason.APPLICABILITY_NOT_STATED, "R2a"),
        held(
            hold_reason.APPLICABILITY_NOT_STATED_ABSENT,
            "R2b",
            contractor_evidence_text="",
        ),
        held(hold_reason.FIELD_SEVERAL_VALUES, "R3"),
        held(
            hold_reason.FIELD_SEVERAL_VALUES,
            "R3tba",
            contractor_evidence_text="10 barg By Contractor",
        ),
        held(
            hold_reason.FIELD_SEVERAL_VALUES,
            "R3nodraft",
            requirement="Invented signed rule",
            trust_label="TESTED_CARD",
        ),
        held(hold_reason.APPLICABILITY_SEVERAL_VALUES, "keep2v"),
        held(
            hold_reason.DEFERRED_MARKER,
            "keepdef",
            contractor_evidence_text="10 barg By Contractor",
        ),
        held(hold_reason.OTHER, "keepother"),
        held(None, "keepnone"),
        held(
            hold_reason.APPLICABILITY_NOT_STATED, "keepconfirmed", confirmed_by="eng-1"
        ),
    ]


MOVED_FINDINGS = {"f-R2a", "f-R2b", "f-R3"}
MOVED_STANDARDS = {"API 991", "API 993"}


def compose(findings, copy="internal"):
    """The CRS the export composes (`main._crs_content`'s order), from invented data."""
    rows = crs_mapping.build_crs_rows(
        findings, ["API 990"], "D.pdf", standards_check=CHECK
    )
    rows, added = export_status.one_row(
        rows, [], findings, CHECK, "run-1", "scope-1", frozenset()
    )
    notes = crs_mapping.build_review_notes(findings, ["API 990"]) + added
    return rows, notes


def ident(row):
    return tuple(row.get("finding_ids") or []) or row.get("standard_reference")


def test_the_kind_words_are_the_crs_mappings():
    assert crs_routing.NOT_CITED == crs_mapping.ROW_KIND_STANDARD_NOT_CITED
    assert crs_routing.NOT_APPLICABLE == crs_mapping.ROW_KIND_STANDARD_NOT_APPLICABLE


def test_switch_off_no_finding_moves(switch):
    for f in everything():
        assert crs_routing.rule(f) is None and not cl.is_listed(f)


def test_each_rule_moves_exactly_its_rows_and_nothing_else(switch, monkeypatch):
    off_rows, off_notes = compose(everything())
    switch(True)
    on_rows, on_notes = compose(everything())
    gone = {ident(r) for r in off_rows} - {ident(r) for r in on_rows}
    assert gone == {(i,) for i in MOVED_FINDINGS} | MOVED_STANDARDS
    assert [
        r for r in on_rows if ident(r) not in gone
    ] == on_rows  # nothing new, nothing reworded
    assert [r for r in off_rows if ident(r) not in gone] == on_rows
    assert {(n["note"], n["standard"]) for n in on_notes} - {
        (n["note"], n["standard"]) for n in off_notes
    } == {
        (crs_routing.NOTE_NOT_REQUIRED, "API 991"),
        (crs_routing.NOTE_NOT_APPLICABLE, "API 993"),
    }


@pytest.mark.parametrize(
    "code",
    [hold_reason.APPLICABILITY_NOT_STATED, hold_reason.APPLICABILITY_NOT_STATED_ABSENT],
)
def test_r2_applicability_not_stated_goes_to_the_internal_list(switch, code):
    switch(True)
    f = held(code, "R2")
    assert crs_routing.rule(f) == "R2" and cl.is_listed(f)
    assert crs_mapping.crs_groups([f]) == []
    switch(False)
    assert len(crs_mapping.crs_groups([f])) == 1


def test_two_value_applicability_by_contractor_other_and_no_code_stay_on_the_crs(
    switch,
):
    switch(True)
    for f in everything()[5:]:
        assert crs_routing.rule(f) is None
        assert len(crs_mapping.crs_groups([f])) == 1, f["id"]


def test_r3_needs_a_draft_rule_and_a_stated_value_with_no_placeholder(switch):
    switch(True)
    assert crs_routing.rule(held(hold_reason.FIELD_SEVERAL_VALUES, "R3")) == "R3"
    keep = [
        held(
            hold_reason.FIELD_SEVERAL_VALUES, "R3tba"
        ),  # "10 barg By Contractor": a placeholder mark
        held(
            hold_reason.FIELD_SEVERAL_VALUES,
            "R3nodraft",
            requirement="signed",
            trust_label="TESTED_CARD",
        ),
        held(hold_reason.FIELD_SEVERAL_VALUES, "R3", trust_label="OWNER_APPROVED"),
        held(hold_reason.FIELD_SEVERAL_VALUES, "R3", tier="SAFETY"),
        held(hold_reason.FIELD_SEVERAL_VALUES, "R3", contractor_evidence_text=""),
        held(hold_reason.FIELD_SEVERAL_VALUES, "R3", fact_id="fact-none"),
        held(hold_reason.FIELD_SEVERAL_VALUES, "R3", confirmed_by="eng-1"),
    ]
    for f in keep:
        assert crs_routing.rule(f) is None, f
    unproven = held(
        hold_reason.FIELD_SEVERAL_VALUES,
        "R3",
        requirement="no mark",
        trust_label="UNPROVEN",
    )
    assert crs_routing.rule(unproven) == "R3"


def test_only_a_held_datasheet_check_moves(switch):
    switch(True)
    assert (
        crs_routing.rule(
            held(
                hold_reason.APPLICABILITY_NOT_STATED, compliance_status="NON_COMPLIANT"
            )
        )
        is None
    )
    assert (
        crs_routing.rule(
            held(hold_reason.APPLICABILITY_NOT_STATED, origin="ai_engineering_check")
        )
        is None
    )
    assert crs_routing.rule(held("not_a_code")) is None


def test_the_internal_list_shows_each_moved_finding_with_its_reason(
    switch, monkeypatch
):
    switch(
        True
    )  # the compliance list's own switch stays off: the list is still written
    monkeypatch.setattr(cl, "_stored", lambda run_id: everything())
    lines = cl.for_run("run-1")
    assert {line[1] for line in lines} == {
        "Invented field R2a",
        "Invented field R2b",
        "Invented field R3",
    }
    status = {line[1]: line[4] for line in lines}
    assert (
        status["Invented field R2a"]
        == crs_routing.LISTED_PREFIX
        + crs_routing.REASON_WORDS[hold_reason.APPLICABILITY_NOT_STATED]
    )
    assert "more than one value" in status["Invented field R3"]
    rows, notes = compose(everything())
    data = crs_export.build_crs(
        rows, {"review_run_id": "run-1", "copy": "internal", "review_notes": notes}
    )
    sheet = openpyxl.load_workbook(io.BytesIO(data))[cl.SHEET]
    cells = [c.value for row in sheet.iter_rows() for c in row if c.value]
    assert (
        "3 held checks of this review run are listed here instead of the CRS"
        in cells[0]
    )
    assert cells[0].startswith("0 values with no issue found by a draft rule")
    assert status["Invented field R2b"] in cells
    issue = crs_export.build_crs(rows, {"review_run_id": "run-1", "copy": "issue"})
    assert cl.SHEET not in openpyxl.load_workbook(io.BytesIO(issue)).sheetnames


def test_the_count_line_is_unchanged_when_nothing_was_moved():
    assert cl.count_line(4) == cl.count_line(4, 0)
    assert cl.count_line(4).startswith("4 values with no issue found by a draft rule")


def test_r4_is_listed_beside_standard_not_held_in_review_notes_with_its_reason(switch):
    switch(True)
    rows, notes = compose(everything())
    assert "API 993" not in {r.get("standard_reference") for r in rows}
    (note,) = [n for n in notes if n["standard"] == "API 993"]
    assert note["note"] == crs_routing.NOTE_NOT_APPLICABLE
    assert "it governs only an invented compressor" in note["detail"]
    data = crs_export.build_crs(
        rows, {"review_run_id": "run-1", "copy": "internal", "review_notes": notes}
    )
    sheet = openpyxl.load_workbook(io.BytesIO(data))[crs_export.REVIEW_NOTES_SHEET]
    listed = {(r[0], r[1]) for r in sheet.iter_rows(min_row=2, values_only=True)}
    assert (
        crs_mapping.NOTE_MISSING_STANDARD,
        "API 990",
    ) in listed  # the standard not held
    assert (crs_routing.NOTE_NOT_APPLICABLE, "API 993") in listed


def test_r1_stays_when_the_held_specification_requires_it_and_the_unsure_row_stays(
    switch, monkeypatch
):
    switch(True)
    monkeypatch.setattr(
        crs_routing, "_spec_requires", lambda run_id, allowed: lambda i: i == "API 991"
    )
    rows, notes = compose(everything())
    refs = {r.get("standard_reference") for r in rows}
    assert {"API 991", "API 992"} <= refs and "API 993" not in refs
    assert crs_routing.NOTE_NOT_REQUIRED not in {n["note"] for n in notes}


def test_a_decided_issued_or_confirmed_standards_row_stays(switch, monkeypatch):
    switch(True)
    keys = {
        r["standard_reference"]: r["comment_key"]
        for r in crs_mapping.standards_check_rows(CHECK, "D.pdf")
    }
    monkeypatch.setattr(
        crs_routing,
        "_kept_keys",
        lambda rows, run_id, scope: {keys["API 991"], keys["API 993"]},
    )
    rows, _notes = compose(everything())
    assert {"API 991", "API 993"} <= {r.get("standard_reference") for r in rows}
    row = {
        "row_kind": crs_routing.NOT_APPLICABLE,
        "standard_reference": "API 993",
        "engineer_confirmed": True,
    }
    assert crs_routing.moved_note(row, CHECK, lambda i: False) is None


def _parts(data: bytes) -> dict:
    """Every part of the workbook but its creation time."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n) for n in z.namelist() if n != "docProps/core.xml"}


def _workbook(findings, monkeypatch):
    monkeypatch.setattr(cl, "_stored", lambda run_id: findings)
    rows, notes = compose(findings)
    return crs_export.build_crs(
        rows, {"review_run_id": "run-1", "copy": "internal", "review_notes": notes}
    )


@pytest.mark.parametrize("compliance", [False, True])
def test_switch_off_the_crs_is_byte_identical_to_the_one_without_routing(
    switch, monkeypatch, compliance
):
    switch(False, compliance)
    off = _parts(_workbook(everything(), monkeypatch))
    with monkeypatch.context() as m:  # main: neither hook existed
        m.setattr(crs_routing, "rule", lambda f: None)
        m.setattr(crs_routing, "standards", lambda rows, notes, *a: (rows, notes))
        m.setattr(crs_routing, "enabled", lambda: False)
        main = _parts(_workbook(everything(), monkeypatch))
    assert off == main
    switch(True, compliance)
    assert (
        _parts(_workbook(everything(), monkeypatch)) != main
    )  # not vacuous: the switch changes it


# ------------------------------------------------------------------ R1 on a database


from tests.test_633_honest_exports import _doc, _user, temp_storage  # noqa: E402,F401


def _requirement(req_id, spec, quote):
    from app import db

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO standard_requirements (id, standard_document_id, chunk_id, requirement_text,"
            " source_text, created_at, updated_at) VALUES (?,?,?,?,?,'2026-11-10','2026-11-10')",
            (req_id, spec, f"{spec}-c1", quote, quote),
        )


def test_r1_reads_only_a_verified_quote_of_the_held_project_specification(temp_storage):
    from app import project_specification as ps

    sub = _doc("sub_r1", "CONTRACTOR_SUBMITTAL", "Invented pump datasheet.")
    spec = _doc(
        "spec_r1",
        "CONTRACT_DOCUMENT",
        "The invented pump shall comply with API 991 in full.",
    )
    _user("own_r1", [sub, spec])
    scope = frozenset({sub, spec})
    _requirement("q-ok", spec, "The invented pump shall comply with API 991 in full.")
    _requirement(
        "q-not-on-page", spec, "The invented pump shall comply with API 995 throughout."
    )
    assert crs_routing.spec_quotes(sub, scope) == []  # nothing marked: none held
    assert ps.mark(sub, spec, "own_r1") == (True, "")
    quotes = crs_routing.spec_quotes(sub, scope)
    assert quotes == ["The invented pump shall comply with API 991 in full."]
    assert crs_routing.requires("API 991", quotes)
    assert not crs_routing.requires(
        "API 995", quotes
    )  # named, but its quote is not on the page
    assert not crs_routing.requires("API 99", quotes)
    assert crs_routing.spec_quotes(sub, frozenset({sub})) == []  # a filter only narrows


def test_kept_keys_are_issued_or_decided_never_a_draft_number(temp_storage):
    from app import crs_numbers

    sub = _doc("sub_k", "CONTRACTOR_SUBMITTAL", "x")
    rows = [
        {"row_kind": crs_routing.NOT_CITED, "comment_key": "k-issued"},
        {"row_kind": crs_routing.NOT_APPLICABLE, "comment_key": "k-draft"},
        {"row_kind": crs_routing.NOT_CITED, "comment_key": "k-new"},
    ]
    assert crs_routing._kept_keys(rows, "run-k", "scope-k") == set()
    crs_numbers.assign(
        "scope-k", "LBL", ["k-issued"], document_id=sub, review_run_id="run-k"
    )
    crs_numbers.assign(
        "scope-k",
        "LBL",
        ["k-draft"],
        document_id=sub,
        review_run_id="run-k",
        issued=False,
    )
    assert crs_routing._kept_keys(rows, "run-k", "scope-k") == {"k-issued"}
