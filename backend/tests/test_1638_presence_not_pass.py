"""#1638: a checklist `required` row only asks that a field is stated, so it is no Pass
toward an approval and no decided rule. Invented sheets and made-up rows only."""

from __future__ import annotations

import copy
import sqlite3

import pytest
from tools import crs_bench
from tools import planted_defects as pd

from app import (
    access,
    checklist_scope,
    clause_coverage,
    comparison,
    coverage_pair,
    db,
    main,
    presence_check,
    review_trace,
    scope_ledger,
    submittal_review,
)
from app import datasheet_checks as dc
from app.config import settings
from tests.test_746_checklist_governs import _review, temp_storage  # noqa: F401

PSV = "Pressure Safety Valve"
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
    assert not {i for _, i in REQUIRED} & presence_check.compared_ids()
    assert {i for _, i in COMPARED} <= presence_check.compared_ids()


def test_a_compared_row_still_counts(on):
    assert presence_check.is_stated_only(_row(A_COMPARED)) is False
    assert _code([_row(A_COMPARED)])["code"] == APPROVED


def test_any_stated_row_caps_the_recommendation_below_approved(on):
    """Owner's reviewer's decision: 17 presence rows plus 1 real Pass is Manual, not Approved."""
    got = _code([_row(A_REQUIRED)] * 17 + [_row(A_COMPARED)])
    assert got["code"] == MANUAL
    assert "17 checklist item(s) were stated, not checked" in got["reason"]


def test_real_rows_alone_still_approve(on):
    assert _code([_row(A_COMPARED)] * 2)["code"] == APPROVED


def test_a_real_fail_still_wins_and_the_reason_counts_the_rest(on):
    got = _code([_row(A_REQUIRED)] * 3 + [_row(A_COMPARED, "NON_COMPLIANT")])
    assert got["code"] == REJECTED
    assert "3 checklist item(s) were stated, not checked" in got["reason"]


def test_a_real_pass_a_blank_and_a_stated_row_is_no_approval_with_comments(on):
    got = _code(
        [_row(A_COMPARED), _row(A_REQUIRED), _row(A_REQUIRED, "MISSING_INFORMATION")]
    )
    assert got["code"] == MANUAL


@pytest.mark.parametrize(
    "rows,code",
    [
        ([_row(A_REQUIRED)] * 17 + [_row(A_COMPARED)], MANUAL),
        ([_row(A_REQUIRED)] * 3, MANUAL),
        ([_row(A_REQUIRED)] * 2 + [_row(A_COMPARED, "NON_COMPLIANT")], REJECTED),
    ],
)
def test_the_plain_reason_the_engineer_reads_says_how_many(on, rows, code):
    got = comparison.recommend_code(rows, ENOUGH, codes=CODES)
    stated = sum(r["requirement_source_text"].find(A_REQUIRED) > 0 for r in rows)
    assert got["code"] == code
    assert f"{stated} checklist item(s) were stated, not checked" in got["reason"]
    assert got["reason"].count("stated, not checked") == 1


def test_a_gated_run_says_it_too(on):
    """The not-enough-coverage reason is rewritten plainly: the count must survive that."""
    got = comparison.recommend_code(
        [_row(A_REQUIRED)] * 2, {"sufficient": False}, codes=CODES
    )
    assert got["code"] == MANUAL
    assert "2 checklist item(s) were stated, not checked" in got["reason"]


def test_a_row_with_no_item_id_fails_closed(on):
    row = {**_row(A_REQUIRED), "requirement_source_text": "some other words"}
    assert presence_check.is_stated_only(row) is True
    assert _code([row])["code"] == MANUAL
    blank = {**_row(A_REQUIRED), "requirement_source_text": None}
    assert presence_check.is_stated_only(blank) is True


def test_an_item_id_nobody_lists_fails_closed(on):
    assert presence_check.is_stated_only(_row("NOT-A-KNOWN-ITEM")) is True


def test_the_datasheets_own_arithmetic_still_counts(on):
    consistency = dc.load_rules()["consistency"][0]["id"]
    assert presence_check.is_stated_only(_row(consistency)) is False


def test_an_overlay_edited_in_place_is_read_without_a_restart(
    on, tmp_path, monkeypatch
):
    """The folder's mtime does not move when a file in it is rewritten."""
    import os

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    folder = tmp_path / dc.LOCAL_DIR_NAME
    folder.mkdir()
    overlay = folder / "centrifugal_pump.json"
    body = (
        '{"items": [{"id": "LOCAL-2", "text": "t", "source": {"standard": "s", "clause": "c"},'
        ' "rule": {"kind": "%s", "field": "rated_flow", "op": ">=", "value": 1}}]}'
    )
    overlay.write_text(body % "constant")
    assert presence_check.is_stated_only(_row("LOCAL-2")) is False
    before = folder.stat().st_mtime_ns
    overlay.write_text(body % "required")
    os.utime(overlay, ns=(1, overlay.stat().st_mtime_ns + 1_000_000))
    os.utime(folder, ns=(1, before))
    assert folder.stat().st_mtime_ns == before
    assert presence_check.is_stated_only(_row("LOCAL-2")) is True


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


def test_the_bench_fingerprint_says_the_switch_only_when_on(monkeypatch):
    assert "presence_not_pass_enabled" not in crs_bench.fingerprint()
    monkeypatch.setattr(settings, "presence_not_pass_enabled", True)
    assert "presence_not_pass_enabled=True" in crs_bench.fingerprint()


def test_the_scorer_does_not_call_it_a_pass_on_the_field():
    assert pd.STATED == presence_check.STATUS
    answer = {"fields": ["rated_flow"], "wanted": "query", "defect": "over_limit"}
    stated = {
        "key": "k",
        "status": pd.STATED,
        "roles": {"rated_flow"},
        "tier": "checklist",
    }
    assert pd.judge(answer, [stated], [])["got"] == "missed"


def test_stated_rows_on_a_deferred_value_are_said(on, tmp_path, monkeypatch):
    """Why the decided count falls by less than the stated count: D2 Passes were never credited."""
    monkeypatch.setattr(
        coverage_pair, "value_is_deferred", lambda _c, f: f.get("deferred_row", False)
    )
    rows = [{**_row(A_REQUIRED), "deferred_row": True}, _row(A_REQUIRED)]
    checklist = _pair(tmp_path, rows)["checklist"]
    assert checklist["stated"] == 2 and checklist["stated_deferred"] == 1


def test_the_one_count_a_tick_row_is_in_neither(on, tmp_path):
    """`_tally` and `finding_source` give one count: an engineer's tick row is that, in both."""
    tick = {**_row(A_REQUIRED), "show_for_engineer_tick": 1}
    rows = [tick, _row(A_REQUIRED), _row(A_REQUIRED)]
    pair = _pair(tmp_path, rows)
    sources = [crs_bench.finding_source(r, set(), [])[0] for r in rows]
    assert pair["checklist"]["stated"] == sources.count(crs_bench.SRC_STATED) == 2


def test_the_trace_and_the_audit_do_not_call_it_meets(on):
    from app import review_audit

    rows = [{**_row(A_REQUIRED), "id": "a"}, {**_row(A_COMPARED), "id": "b"}]
    counts = review_trace._status_counts(rows)
    assert counts["COMPLIANT"] == 1 and counts[presence_check.STATUS] == 1
    section = review_audit._rules_section(rows)
    assert section["verdict_counts"][presence_check.WORDS] == 1
    assert sum(section["verdict_counts"].values()) == 2
    assert section["rows"][0]["verdict"] == presence_check.WORDS
    assert section["rows"][1]["verdict"] != presence_check.WORDS


def test_a_deferred_stated_row_is_not_said_of_the_passes(on):
    from app import review_audit

    deferred = {
        **_row(A_REQUIRED),
        "id": "a",
        "contractor_evidence_text": "By Contractor",
    }
    section = review_audit._rules_section([deferred, {**_row(A_COMPARED), "id": "b"}])
    assert section["pass_on_deferred"] == 0
    assert "0 of 1 Pass rows" in section["pass_on_deferred_note"]


def test_the_run_counts_move_the_stated_rows(on):
    by_status = {"COMPLIANT": 3, "NON_COMPLIANT": 1}
    got = presence_check.moved_counts(by_status, [_row(A_REQUIRED), _row(A_COMPARED)])
    assert got == {"COMPLIANT": 2, "NON_COMPLIANT": 1, presence_check.STATUS: 1}


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


# ------------------------------------------------------------------ the unchecked-share gate


def _only_stated_rules() -> dict:
    """The relief valve checklist as if every item only asked that a field is stated."""
    rules = copy.deepcopy(dc.load_rules())
    for item in rules["checklists"][PSV]["items"]:
        item["rule"] = {
            "kind": "required",
            "field": item["rule"].get("field") or "set_pressure",
        }
        item.pop("condition", None)
    return rules


@pytest.fixture
def only_stated(monkeypatch):
    rules = _only_stated_rules()
    monkeypatch.setattr(dc, "load_rules", lambda *a, **k: rules)
    presence_check._compared.cache_clear()
    yield rules
    presence_check._compared.cache_clear()


def test_off_an_only_stated_checklist_still_sets_its_standards_aside(only_stated):
    _result, stored, ids = _review(PSV)
    assert stored[ids["cited_1"]]["reason_code"] == "covered_by_checklist"


def test_on_an_only_stated_checklist_does_not_govern(on, only_stated):
    """Its rules are back in what the #633 gate counts: compared, or applies but not checked."""
    result, stored, ids = _review(PSV)
    assert not any(d["state"] == scope_ledger.NOT_USED for d in stored.values())
    assert stored[ids["cell"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED
    assert result["requirement_split"]["not_used"] == 0
    assert result["requirement_split"]["applies_not_checked"] >= 1


def test_on_a_checklist_with_compared_items_still_governs(on):
    _result, stored, ids = _review(PSV)
    assert stored[ids["cited_1"]]["state"] == scope_ledger.NOT_USED


def test_the_rules_it_gives_back_can_stop_an_approval_at_the_gate(on):
    got = comparison.recommend_code(
        [_row(A_COMPARED)],
        ENOUGH,
        codes=CODES,
        unchecked_counts={"not_compared": 9, "checked": 1, "not_applied": 0},
    )
    assert got["code"] == MANUAL and "9 of 10" in got["reason"]


def test_with_lock_2_every_cited_standard_stays_kept_and_labelled(
    on, only_stated, monkeypatch
):
    """Lock 2 keeps what the checklist cites, under its trust label. This switch must not
    narrow that list, or a rule back in scope would decide with no label."""
    monkeypatch.setattr(settings, "draft_checklist_keeps_standards_enabled", True)
    entry = dc.checklist_sources(PSV, only_stated)
    assert entry["standards"] and set(entry["stated_only"]) == set(entry["standards"])
    _result, stored, ids = _review(PSV)
    assert not any(d["state"] == scope_ledger.NOT_USED for d in stored.values())
    assert stored[ids["cell"]]["state"] == scope_ledger.APPLIES_NOT_CHECKED


def test_set_aside_gives_back_only_the_only_stated_standards(on, monkeypatch):
    def named(ids, cited):
        return {i for i in ids if i in cited}

    monkeypatch.setattr(comparison, "governed_standards", named)
    governing = {"key": "T", "items": 2, "standards": ["a", "b"], "stated_only": ["a"]}
    rows = [{"standard_document_id": "a"}, {"standard_document_id": "b"}]
    gated = {"not_compared_items": []}
    items, left, _gated, note = checklist_scope.set_aside(
        governing, {"a", "b"}, rows, gated
    )
    assert [i["requirement"]["standard_document_id"] for i in items] == ["b"]
    assert [r["standard_document_id"] for r in left] == ["a"]
    assert note["standards"] == 1
    all_back = {**governing, "stated_only": ["a", "b"]}
    assert checklist_scope.set_aside(all_back, {"a", "b"}, rows, gated) == (
        [],
        rows,
        gated,
        None,
    )
