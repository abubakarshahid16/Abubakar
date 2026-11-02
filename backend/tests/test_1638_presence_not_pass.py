"""#1638: a checklist `required` row only asks that a field is stated, so it is no Pass
toward an approval and no decided rule. Invented sheets and made-up rows only."""

from __future__ import annotations

import sqlite3

import pytest
from tools import crs_bench
from tools import planted_defects as pd

from app import (
    access,
    clause_coverage,
    comparison,
    coverage_pair,
    db,
    main,
    presence_check,
    review_trace,
    submittal_review,
)
from app import datasheet_checks as dc
from app.config import settings

ENOUGH = {"sufficient": True, "extraction_coverage": 1.0}
CODES = comparison.DEFAULT_CODES
APPROVED, WITH_COMMENTS, REJECTED, MANUAL = CODES


def _items(kind: str) -> list[tuple[str, str]]:
    rules = dc.load_rules()
    return [
        (name, item["id"])
        for name, entry in rules["checklists"].items()
        if not name.startswith("_")
        for item in entry["items"]
        if item["rule"]["kind"] == kind
    ]


def _row(item: str, status: str = "COMPLIANT", section: str = "Some field") -> dict:
    return {
        "origin": "datasheet_check",
        "compliance_status": status,
        "requirement_source_text": f"Datasheet check {item}: words",
        "contractor_section": section,
    }


REQUIRED = _items("required")
A_REQUIRED = next(i for t, i in REQUIRED if t == "Centrifugal Pump")
COMPARED = _items("compare") or _items("constant")
A_COMPARED = COMPARED[0][1]


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "presence_not_pass_enabled", True)


def _code(findings):
    return comparison._recommend_code(findings, ENOUGH, codes=CODES)


def test_the_switch_defaults_off_and_then_nothing_changes():
    assert settings.presence_not_pass_enabled is False
    assert _code([_row(A_REQUIRED)] * 17)["code"] == APPROVED
    assert presence_check.is_stated_only(_row(A_REQUIRED)) is False
    assert presence_check.review_notes([_row(A_REQUIRED)]) == []


def test_only_presence_rows_with_sufficient_coverage_never_reach_approved(on):
    got = _code([_row(A_REQUIRED)] * 17)
    assert got["code"] == MANUAL
    assert "17 checklist item(s) were stated, not checked" in got["reason"]


@pytest.mark.parametrize("kind,item", REQUIRED[:: max(1, len(REQUIRED) // 12)])
def test_true_of_every_equipment_type(on, kind, item):
    assert presence_check.is_stated_only(_row(item)), kind
    assert _code([_row(item)])["code"] == MANUAL


def test_every_checklist_with_required_rows_is_covered():
    types = {t for t, _ in REQUIRED}
    assert {"Centrifugal Pump", "Pressure Vessel", "Heat Exchanger"} <= types
    assert {i for _, i in REQUIRED} <= presence_check.item_ids()


def test_a_compared_row_still_counts(on):
    assert presence_check.is_stated_only(_row(A_COMPARED)) is False
    assert _code([_row(A_COMPARED)])["code"] == APPROVED


def test_an_approval_on_real_rows_says_what_was_only_stated(on):
    got = _code([_row(A_COMPARED), _row(A_REQUIRED), _row(A_REQUIRED)])
    assert got["code"] == APPROVED
    assert "2 checklist item(s) were stated, not checked" in got["reason"]


def test_a_blank_beside_stated_rows_is_no_approval_with_comments(on):
    """Stated rows must not be the 'confirmed as met' that lets a blank pass with comments."""
    got = _code([_row(A_REQUIRED), _row(A_REQUIRED, "MISSING_INFORMATION")])
    assert got["code"] == MANUAL


def test_a_fail_is_still_a_rejection_and_not_every_row_of_the_item_is_stated(on):
    assert (
        _code([_row(A_REQUIRED), _row(A_COMPARED, "NON_COMPLIANT")])["code"] == REJECTED
    )
    assert (
        presence_check.is_stated_only(_row(A_REQUIRED, "MISSING_INFORMATION")) is False
    )
    other = {**_row(A_REQUIRED), "origin": None}
    assert presence_check.is_stated_only(other) is False


def test_the_plain_reason_stays_true(on):
    got = comparison.recommend_code([_row(A_REQUIRED)] * 3, ENOUGH, codes=CODES)
    assert got["code"] == MANUAL
    assert "can't be suggested" in got["reason"]
    assert "stated, not checked" in got["details"]


def test_an_overlay_item_is_read_too(on, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    folder = tmp_path / dc.LOCAL_DIR_NAME
    folder.mkdir()
    (folder / "centrifugal_pump.json").write_text(
        '{"items": [{"id": "LOCAL-1", "text": "t", "source": {"standard": "s", "clause": "c"},'
        ' "rule": {"kind": "required", "field": "rated_flow"}}]}'
    )
    assert presence_check.is_stated_only(_row("LOCAL-1"))


# ------------------------------------------------------------------ the counts


def _conn(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "x.sqlite")
    conn.execute(
        "CREATE TABLE submittal_facts (id, submittal_document_id, field_name, page,"
        " equipment_tag, value_note, superseded_at)"
    )
    return conn


def _pair(tmp_path, findings, matchers=None):
    run = {"id": "r", "submittal_document_id": "d", "outcome_json": "{}"}
    return coverage_pair.compute(
        _conn(tmp_path), run, findings, matchers=matchers, equipment_type="T"
    )


def test_a_presence_row_is_not_decided_in_the_one_definition(on, tmp_path):
    pair = _pair(tmp_path, [_row(A_REQUIRED), _row(A_COMPARED)])
    assert pair["checklist"]["rows"] == 2
    assert pair["checklist"]["decided"] == 1 and pair["checklist"]["pass"] == 1
    assert pair["checklist"]["stated"] == 1
    assert "1 stated, not checked" in pair["checklist_line"]


def test_with_the_switch_off_the_pair_is_as_it_was(tmp_path):
    pair = _pair(tmp_path, [_row(A_REQUIRED)])
    assert pair["checklist"]["decided"] == 1 and "stated" not in pair["checklist"]
    assert "stated, not checked" not in pair["checklist_line"]


def test_a_truth_hit_on_a_stated_row_stays_on_the_headline_count(on, tmp_path):
    """A row the truth set names wrong is not lost by no longer being decided."""
    pair = _pair(
        tmp_path,
        [_row(A_REQUIRED)],
        matchers=[{"check": A_REQUIRED, "status": "COMPLIANT"}],
    )
    assert pair["checklist"]["wrong"] == 0
    assert pair["wrong_verdicts"] == {"all": 1, "outside": 1}


def test_the_bench_names_it_apart_and_does_not_credit_it(on):
    row = _row(A_REQUIRED)
    assert crs_bench.finding_source(row, set(), []) == (
        crs_bench.SRC_STATED,
        crs_bench.TICK,
    )
    assert (
        crs_bench.finding_source(_row(A_COMPARED), set(), [])[0]
        == crs_bench.SRC_CHECKLIST
    )


def test_the_scorer_does_not_call_it_a_pass_on_the_field():
    answer = {"fields": ["rated_flow"], "wanted": "query", "defect": "over_limit"}
    stated = {
        "key": "k",
        "status": pd.STATED,
        "roles": {"rated_flow"},
        "tier": "checklist",
    }
    assert pd.judge(answer, [stated], [])["got"] == "missed"


def test_the_review_note_names_the_fields_and_counts(on):
    rows = [
        _row(A_REQUIRED, section="NPSH required"),
        _row(A_REQUIRED, section="Rated flow"),
    ]
    note = next(
        n
        for n in clause_coverage.outcome_notes({}, rows)
        if n["note"] == presence_check.WORDS
    )
    assert note["note"] == "Stated, not checked" and note["count"] == 2
    assert "NPSH required, Rated flow" in note["detail"]


def test_the_finding_as_the_api_hands_it_on_says_so(on):
    assert submittal_review._finding_item(_row(A_REQUIRED))["stated_only"] is True
    assert submittal_review._finding_item(_row(A_COMPARED))["stated_only"] is False


# ------------------------------------------------------------------ the real path


@pytest.fixture
def copy_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "source.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    db.reset_connection()
    return tmp_path / "source.sqlite"


def _pump() -> dict:
    """A small invented base: the checklist reads what it finds."""
    return {
        "format": "planted-base/1",
        "source": "invented",
        "name": "invented_pump",
        "equipment_type": "Centrifugal Pump",
        "title": "CENTRIFUGAL PUMP DATA SHEET",
        "doc_prefix": "SYN-PMP",
        "pages": [
            {
                "heading": "DATA",
                "rows": [
                    {
                        "role": "npsh_required",
                        "field": "NPSH required",
                        "value": "7",
                        "unit": "m",
                    },
                    {
                        "role": "npsh_available",
                        "field": "NPSH available",
                        "value": "6",
                        "unit": "m",
                    },
                ],
            }
        ],
        "controls": [{"name": "clean", "set": {}}],
        "plants": [],
    }


def test_from_the_printed_value_to_the_cell_the_engineer_reads(on, copy_db, tmp_path):
    """The value goes through upload, facts, checks and findings to the CRS's note and code
    cells, on a real run: the row stays stored as it was, and counts for nothing."""
    pdf = tmp_path / "invented.pdf"
    base = _pump()
    work = tmp_path / "w"
    work.mkdir()
    with pd._settings_for_copy(work), pd.no_claude("rules"):
        pd.render_pdf(base, pdf, doc_no="SYN-PMP-0001")
        with pd._reader_mode("rules", [], [0]):
            run_id, why = pd._review(pdf)
        assert why is None
        scope = access.unrestricted_scope()
        findings = submittal_review.list_run_findings(
            run_id, allowed_document_ids=scope.allowed_document_ids
        )
        stated = [f for f in findings if f["stated_only"]]
        assert any(f["contractor_section"] == "NPSH required" for f in stated)
        assert all(f["compliance_status"] == "COMPLIANT" for f in stated), (
            "stored as it was"
        )
        rows, meta, *_ = main._crs_content(run_id, scope)
        note = next(
            n for n in meta["review_notes"] if n["note"] == presence_check.WORDS
        )
        assert note["count"] == len(stated) and "NPSH required" in note["detail"]
        assert meta["recommended_code"] != APPROVED
        assert not {f["id"] for f in stated} & {r.get("finding_id") for r in rows}
        trace = review_trace.build(run_id, scope)
        step = next(s for s in trace["steps"] if s["step"] == "CHECKLIST")
        assert step["counts"]["stated_not_checked"] == len(stated)
        pair = coverage_pair.for_run(db.connect(), run_id, case=None)
        assert pair["checklist"]["stated"] == len(stated)
        assert pair["checklist"]["decided"] == pair["checklist"]["rows"] - len(
            stated
        ) - sum(
            f["compliance_status"] not in ("COMPLIANT", "NON_COMPLIANT")
            for f in findings
            if f["origin"] == "datasheet_check"
        )
