"""Owner on #1584: the review code waits for the engineer's tick. One path with the owner-approved
rule's hold (`rule_trust.hold_open_ticks`). Invented rows only; no model."""

from __future__ import annotations

import json
import uuid

import pytest

from app import comparison, db, review, rule_trust, submittal_review, tick_code
from app.config import settings

CODES = comparison.review_codes()
APPROVED, WITH_COMMENTS, REJECTED, MANUAL = CODES
ENOUGH = {"sufficient": True, "extraction_coverage": 1.0}
NOW = "2026-11-02T00:00:00Z"


def _tick(**extra):
    return {
        "compliance_status": "COMPLIANT",
        "trust_label": rule_trust.TESTED_CARD,
        "show_for_engineer_tick": 1,
        **extra,
    }


def _code(*findings):
    rows = [{"compliance_status": "COMPLIANT"}, *findings]
    return comparison.recommend_code(rows, ENOUGH, codes=CODES)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "tick_holds_review_code_enabled", True)


def test_switch_off_an_open_tick_changes_nothing_byte_for_byte():
    assert settings.tick_holds_review_code_enabled is False
    with_tick = _code(_tick())
    without = _code()
    assert with_tick == without
    assert with_tick["code"] == APPROVED
    assert "open_safety_ticks" not in with_tick


def test_an_open_tick_of_any_label_holds_an_approval(on):
    for label in (
        rule_trust.TESTED_CARD,
        rule_trust.AUTO_PROVEN,
        rule_trust.OWNER_APPROVED,
    ):
        out = _code(_tick(trust_label=label))
        assert out["code"] == MANUAL
        assert out["open_safety_ticks"] == 1
        assert "1 safety value" in out["reason"]


def test_an_open_tick_holds_approved_with_comments_too(on):
    gap = {"compliance_status": comparison.MISSING_INFORMATION}
    assert _code(gap)["code"] == WITH_COMMENTS
    assert _code(gap, _tick())["code"] == MANUAL


def test_a_breach_stays_rejected_beside_an_open_tick(on):
    breach = {"compliance_status": "NON_COMPLIANT"}
    assert _code(breach, _tick())["code"] == REJECTED


def test_all_ticked_gives_the_code_the_rows_support(on):
    assert (
        _code(_tick(confirmed_by="eng"), _tick(approval_status="accepted"))["code"]
        == APPROVED
    )
    gap = {"compliance_status": comparison.MISSING_INFORMATION}
    assert _code(gap, _tick(confirmed_by="eng"))["code"] == WITH_COMMENTS
    # one still open holds it
    assert _code(_tick(confirmed_by="eng"), _tick())["code"] == MANUAL


def test_an_edited_comment_is_not_a_tick_and_still_holds(on):
    edited = _tick(confirmed_by="eng", engineer_comment="Invented objection.")
    assert _code(edited)["code"] == MANUAL


def test_one_path_the_owner_rule_holds_with_this_switch_off():
    owner = _tick(trust_label=rule_trust.OWNER_APPROVED)
    assert _code(owner)["code"] == MANUAL
    assert "an owner-approved rule" in _code(owner)["reason"]
    assert _code({**owner, "confirmed_by": "eng"})["code"] == APPROVED
    assert _code(_tick())["code"] == APPROVED, "other labels: as they were"


def test_a_row_not_flagged_for_a_tick_does_not_hold(on):
    assert (
        _code({"compliance_status": "COMPLIANT", "show_for_engineer_tick": 0})["code"]
        == APPROVED
    )


# ------------------------------------------------------------ the stored code


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "tick.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('sub','sub.pdf','s',1,'s','ready',1,?)",
            (NOW,),
        )
    yield
    db.reset_connection()


def _run(*tick_ids, final=None, code=MANUAL):
    run = str(uuid.uuid4())
    outcome = {
        "recommended_code": code,
        "reason": "stored words",
        "details": "stored",
        "completeness": ENOUGH,
    }
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at,"
            "outcome_json,engineer_final_code,override_reason) VALUES (?,'sub','completed',?,?,?,?,?)",
            (run, NOW, NOW, json.dumps(outcome), final, "typed" if final else None),
        )
        for fid in tick_ids:
            conn.execute(
                "INSERT INTO review_findings (id,document_id,category,severity,requirement,finding,"
                "required_action,created_at,updated_at,review_run_id,compliance_status,origin,"
                "show_for_engineer_tick,trust_label) VALUES (?,'sub','c','low','r','f','a',?,?,?,"
                "'COMPLIANT','datasheet_check',1,?)",
                (fid, NOW, NOW, run, rule_trust.TESTED_CARD),
            )
    return run


def _outcome(run):
    row = (
        db.connect()
        .execute(
            "SELECT outcome_json, engineer_final_code, override_reason FROM review_runs WHERE id = ?",
            (run,),
        )
        .fetchone()
    )
    return json.loads(row[0]), row[1], row[2]


def test_the_last_tick_works_the_stored_code_out_again(stored, on):
    run = _run("t1", "t2")
    review.update("t1", {"confirmed_by": "eng"}, actor_user_id="eng")
    out, _f, _r = _outcome(run)
    assert out["recommended_code"] == MANUAL and out["reason"] == "stored words", (
        "a tick that leaves another open leaves the code and its reason"
    )
    review.update("t2", {"confirmed_by": "eng"}, actor_user_id="eng")
    out, final, _r = _outcome(run)
    assert out["recommended_code"] == APPROVED
    assert out["reason"] != "stored words"
    assert final is None, "a tick records no final code"
    audit = (
        db.connect()
        .execute(
            "SELECT actor_user_id, detail FROM audit_events WHERE action = 'review.code_rechecked_after_tick'"
        )
        .fetchone()
    )
    assert audit[0] is None, (
        "no user row: the tick still stands, the record names no one"
    )
    assert audit[1] == f"{MANUAL} -> {APPROVED}"


def test_the_audit_names_a_known_engineer(stored, on):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('u1','u1@invented.test','U','x',?)",
            (NOW,),
        )
    _run("t1")
    review.update("t1", {"confirmed_by": "u1"}, actor_user_id="u1")
    audit = (
        db.connect()
        .execute(
            "SELECT actor_user_id FROM audit_events"
            " WHERE action = 'review.code_rechecked_after_tick'"
        )
        .fetchone()
    )
    assert audit[0] == "u1"


def test_the_engineers_typed_final_code_stays_theirs(stored, on):
    run = _run("t1", final="Typed code")
    review.update("t1", {"confirmed_by": "eng"}, actor_user_id="eng")
    out, final, reason = _outcome(run)
    assert final == "Typed code" and reason == "typed"
    assert out["recommended_code"] == MANUAL, (
        "what they decided beside is not rewritten"
    )


def test_switch_off_a_tick_does_not_touch_the_stored_code(stored):
    run = _run("t1")
    before = _outcome(run)
    review.update("t1", {"confirmed_by": "eng"}, actor_user_id="eng")
    assert _outcome(run) == before


def test_a_change_to_another_row_does_not_look_again(stored, on):
    run = _run("t1")
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET show_for_engineer_tick = 0 WHERE id = 't1'"
        )
    review.update("t1", {"confirmed_by": "eng"}, actor_user_id="eng")
    assert _outcome(run)[0]["recommended_code"] == MANUAL


def test_the_stored_inputs_reach_the_function(stored, on):
    """A stored gate still holds after the last tick: the code the OTHER rows support."""
    run = _run("t1")
    with db.connect() as conn:
        outcome = _outcome(run)[0]
        outcome["completeness"] = {"sufficient": False, "basis": "x"}
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), run),
        )
    review.update("t1", {"confirmed_by": "eng"}, actor_user_id="eng")
    assert _outcome(run)[0]["recommended_code"] == MANUAL
    assert tick_code.after_change(None) is None


def test_the_setting_is_off_by_default():
    from app.config import Settings

    assert Settings.model_fields["tick_holds_review_code_enabled"].default is False
