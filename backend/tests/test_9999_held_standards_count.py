"""A-9999: standards held for the engineer because the equipment type is unsure
are counted where the checked ones are, with the boundary, and never as 0.

The marker is the stored `held_reason` code, never the words of
`exclusion_reason` (order 143). Invented documents only.
"""

from __future__ import annotations

from app import access, applicability, db, held_standards, submittal_review
from app.api import run_standards
from tests.test_142a_declared_design_code import (
    _scope_says_not_applicable,
    _sheet,
)
from tests.test_applicability import _doc, _run, _scope, temp_storage  # noqa: F401


def _standards():
    std_660 = _doc(
        "std_660", "API-660.pdf", "COMPANY_STANDARD",
        document_number="API 660", equipment_type="Heat Exchanger",
    )
    std_asme = _doc(
        "std_asme", "ASME-VIII.pdf", "COMPANY_STANDARD",
        document_number="ASME BPVC Section VIII Division 1",
    )
    return std_660, std_asme


def _unsure_run():
    std_660, std_asme = _standards()
    sub = _sheet()
    ids = _scope(sub, std_660, std_asme)
    run = _run(sub)
    applicability.select(sub, allowed_document_ids=ids, review_run_id=run)
    return sub, run, ids, std_660, std_asme


def _held_reason(run, std):
    return db.connect().execute(
        "SELECT held_reason FROM review_applicable_standards"
        " WHERE review_run_id = ? AND standard_document_id = ?", (run, std),
    ).fetchone()["held_reason"]


def test_held_rows_are_flagged_and_counted():
    _sub, run, ids, std_660, std_asme = _unsure_run()
    assert _held_reason(run, std_660) == held_standards.HELD_UNSURE_TYPE
    assert _held_reason(run, std_asme) is None
    note = held_standards.note(run, ids)
    assert note["count"] == 1 and note["standard_document_ids"] == [std_660]
    for words in ("1 standard was held", "equipment type is unsure", "not checked"):
        assert words in note["sentence"]


def test_a_scope_excluded_or_unmatched_row_is_not_counted_as_held(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "applicability_reasoning_enabled", True)
    std_svc = _doc(
        "std_svc", "svc.pdf", "COMPANY_STANDARD",
        document_number="XQ-9001", service="Hydrogen",
    )
    unmatched = _doc("std_other", "other.pdf", "COMPANY_STANDARD", document_number="ZZ-1")
    sub = _doc(
        "sub", "plain.pdf", "CONTRACTOR_SUBMITTAL", text="Design code: API 660.",
        equipment_type="Heat Exchanger", service="Hydrogen",
    )
    _scope_says_not_applicable(monkeypatch, std_svc)
    ids = _scope(sub, std_svc, unmatched)
    run = _run(sub)
    applicability.select(sub, allowed_document_ids=ids, review_run_id=run)
    rows = db.connect().execute(
        "SELECT standard_document_id, included FROM review_applicable_standards"
        " WHERE review_run_id = ?", (run,)).fetchall()
    assert {r["standard_document_id"] for r in rows if not r["included"]}
    assert held_standards.note(run, ids) is None


def test_a_sure_sheet_has_no_note():
    std_660, _asme = _standards()
    sub = _doc(
        "sub", "sure.pdf", "CONTRACTOR_SUBMITTAL", text="Design code: API 660.",
        equipment_type="Heat Exchanger",
    )
    ids = _scope(sub, std_660)
    run = _run(sub)
    applicability.select(sub, allowed_document_ids=ids, review_run_id=run)
    assert held_standards.note(run, ids) is None
    scope = access.AccessScope(user_id="u", allowed_document_ids=ids)
    payload = run_standards._run_standards_payload(run, scope, False)
    assert "held_for_engineer" in payload and payload["held_for_engineer"] is None


def test_old_run_without_flag_is_null():
    _sub, run, ids, std_660, _asme = _unsure_run()
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_applicable_standards SET held_reason = NULL"
            " WHERE review_run_id = ?", (run,))
        reason = conn.execute(
            "SELECT exclusion_reason FROM review_applicable_standards"
            " WHERE review_run_id = ? AND standard_document_id = ?", (run, std_660),
        ).fetchone()["exclusion_reason"]
    assert reason.startswith("held for the engineer to check")
    assert held_standards.note(run, ids) is None


def test_override_clears_the_flag():
    _sub, run, ids, std_660, std_asme = _unsure_run()
    assert _held_reason(run, std_660) == held_standards.HELD_UNSURE_TYPE
    applicability.override(
        run, std_660, include=True, reason="checked by hand", allowed_document_ids=ids)
    assert _held_reason(run, std_660) is None
    assert held_standards.note(run, ids) is None
    # an engineer's own excluded row is never flagged, even if named to mark()
    applicability.override(
        run, std_asme, include=False, reason="not for this job", allowed_document_ids=ids)
    held_standards.mark(run, [std_asme])
    assert _held_reason(run, std_asme) is None


def test_note_is_intersection_with_grants():
    sub, run, _ids, std_660, _asme = _unsure_run()
    blind = _scope(sub)
    assert held_standards.note(run, blind) is None
    scope = access.AccessScope(user_id="u", allowed_document_ids=blind)
    assert run_standards._run_standards_payload(run, scope, False)["held_for_engineer"] is None
    seen = held_standards.note(run, _scope(sub, std_660))
    assert seen["count"] == 1 and seen["standard_document_ids"] == [std_660]


def test_an_unknown_code_never_borrows_the_unsure_wording():
    _sub, run, ids, std_660, _asme = _unsure_run()
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_applicable_standards SET held_reason = 'some_future_cause'"
            " WHERE review_run_id = ? AND standard_document_id = ?", (run, std_660))
    sentence = held_standards.note(run, ids)["sentence"]
    assert "held for the engineer" in sentence and "unsure" not in sentence


def test_payload_and_other_numbers_unchanged():
    from app import main

    _sub, run, ids, std_660, std_asme = _unsure_run()
    scope = access.AccessScope(user_id="u", allowed_document_ids=ids)
    payload = run_standards._run_standards_payload(run, scope, False)
    assert [s["standard_document_id"] for s in payload["standards"]] == [std_asme]
    assert payload["total"] == 1
    assert payload["held_for_engineer"]["count"] == 1
    everything = run_standards._run_standards_payload(run, scope, True)
    assert std_660 in {s["standard_document_id"] for s in everything["standards"]}
    run_row = submittal_review.get_review_run(run, allowed_document_ids=ids)
    assert main._run_summary(run_row, scope)["standards_in_scope"] == 1
