"""Order 224.1: the AI checks' drafts keep NO status, sit in their own bucket and an exact repeat is marked, never deleted.

On the owner's I-06 run (four relief valves, one per page) the AI engineering
check wrote "valve size is blank" once per page, each with an EMPTY status.
The status stays empty (a draft is not a verdict), the drafts are counted as
"AI observations (draft, no verdict)", exact repeats are marked and every row
keeps its page, tag and quote; a draft can never move the suggested code. Invented text, a throwaway database, no model.
"""

from __future__ import annotations

import pytest

from app import ai_check_drafts, comparison, db, review, submittal_review
from app.config import settings

RUN = "run_1"
SUB = "doc_sub"


@pytest.fixture(autouse=True)
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "drafts.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    review.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,'s.pdf','sha',1,'s.pdf','ready',4,'2026-10-18T00:00:00Z')",
            (SUB,),
        )
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,?,'completed','2026-10-18T00:00:00Z','2026-10-18T00:00:00Z')",
            (RUN, SUB),
        )
    yield
    db.reset_connection()


def _draft(
    page,
    quote="340 psig",
    standard="API 520",
    text="The valve size is blank.",
    action="State the valve size.",
    field="Valve size",
    origin=ai_check_drafts.AI_ORIGIN,
):
    made = review.create(
        {
            "document_id": SUB,
            "category": "technical_query",
            "severity": "minor",
            "requirement": "valve size",
            "finding": text,
            "required_action": action,
            "status": "open",
            "approval_status": "pending",
        },
        created_by=None,
    )
    # the sentence the check really writes (`ai_engineering_check`): the standard
    # a draft relates to is named in its reason, never stored as a document id
    rationale = (
        f"AI engineering check. Relates to: {standard}. Written by a local model."
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET review_run_id = ?, origin = ?, contractor_page = ?,"
            " contractor_section = ?, contractor_evidence_text = ?, ai_rationale = ? WHERE id = ?",
            (RUN, origin, page, field, quote, rationale, made["id"]),
        )
    return made["id"]


def _tag(page, tag):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO submittal_facts (id,review_run_id,submittal_document_id,field_name,field_label,"
            "page,equipment_tag,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'t','t')",
            (f"fact_{page}_{tag}", RUN, SUB, "size", "Size", page, tag),
        )


def _rows(origin=ai_check_drafts.AI_ORIGIN):
    return [
        dict(r)
        for r in db.connect().execute(
            "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = ? ORDER BY contractor_page",
            (RUN, origin),
        )
    ]


def test_a_draft_never_gets_a_status_and_is_counted_in_its_own_bucket():
    _draft(1, text="One thing.")
    _draft(2, text="Another thing.", field="Other")
    _draft(3, origin=ai_check_drafts.WEB_ORIGIN)
    ai_check_drafts.settle(RUN)
    assert {r["compliance_status"] for r in _rows()} == {None}
    assert {r["compliance_status"] for r in _rows(ai_check_drafts.WEB_ORIGIN)} == {None}
    from app import main

    total, by_status, _tags, drafts = main._finding_counts(RUN)
    assert (total, by_status, drafts) == (3, {}, 3)  # the bucket, not a status
    assert ai_check_drafts.BUCKET_LABEL == "AI observations (draft, no verdict)"


def test_exact_repeats_are_marked_and_every_row_keeps_its_page_tag_and_quote():
    for page, tag in ((1, "PSV-1"), (2, "PSV-2"), (3, "PSV-3")):
        _draft(page)
        _tag(page, tag)
    assert ai_check_drafts.settle(RUN) == {"marked": 2}
    rows = _rows()
    assert [r["contractor_page"] for r in rows] == [1, 2, 3]  # nothing deleted
    assert "Exact repeat" not in rows[0]["ai_rationale"]
    assert all(
        "Exact repeat of the observation on page 1." in r["ai_rationale"]
        for r in rows[1:]
    )
    assert {r["contractor_evidence_text"] for r in rows} == {"340 psig"}


def test_a_second_call_changes_nothing():
    _draft(1)
    _draft(2)
    ai_check_drafts.settle(RUN)
    before = [r["ai_rationale"] for r in _rows()]
    assert ai_check_drafts.settle(RUN) == {"marked": 0}
    assert [r["ai_rationale"] for r in _rows()] == before


def test_a_different_quoted_value_or_standard_or_field_is_not_a_repeat():
    _draft(1)
    _draft(2, quote="130 psig")
    _draft(3, standard="API 526")
    _draft(4, field="Other field")
    _draft(5, text="The fluid phase is blank.")
    assert ai_check_drafts.settle(RUN) == {"marked": 0}
    assert all("Exact repeat" not in r["ai_rationale"] for r in _rows())


def test_a_draft_an_engineer_decided_is_never_touched():
    keep = _draft(1)
    decided = _draft(2)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET approval_status = 'approved', approved_by = 'eng' WHERE id = ?",
            (decided,),
        )
    ai_check_drafts.settle(RUN)
    rows = {r["id"]: r for r in _rows()}
    assert set(rows) == {keep, decided}
    assert "Exact repeat" not in rows[decided]["ai_rationale"]


def test_a_pile_of_drafts_never_moves_the_suggested_code():
    """The rule that mattered before the status: a draft cannot change the code."""
    met = {"compliance_status": "COMPLIANT", "origin": None}
    drafts = [{"compliance_status": None, "origin": "ai_engineering_check"}] * 40
    drafts += [
        {"compliance_status": "NON_COMPLIANT", "origin": "web_standard_check"}
    ] * 3
    completeness = {"extraction_coverage": 1.0}
    alone = comparison._recommend_code([met], completeness)
    with_drafts = comparison._recommend_code([met, *drafts], completeness)
    assert with_drafts["code"] == alone["code"]
    assert with_drafts.get("unresolved") == alone.get("unresolved")
    # a real engineer-to-check finding still counts
    real = {"compliance_status": "NEEDS_ENGINEER_REVIEW", "origin": None}
    assert comparison._recommend_code([met, real], completeness).get("unresolved") == 1


def test_the_review_job_settles_the_drafts_after_the_ai_check_and_never_fails_on_it(
    monkeypatch,
):
    from app import ai_engineering_check, review_jobs

    calls = []
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(
        ai_engineering_check, "run_check", lambda *a, **k: {"ran": False}
    )
    monkeypatch.setattr(
        ai_engineering_check, "run_datasheet_opinion", lambda *a, **k: {}
    )
    monkeypatch.setattr(ai_check_drafts, "settle", lambda run_id: calls.append(run_id))
    review_jobs._ai_check(RUN, frozenset({SUB}), [])
    assert calls == [RUN]

    def boom(run_id):
        raise RuntimeError("database locked")

    monkeypatch.setattr(ai_check_drafts, "settle", boom)
    review_jobs._ai_check(RUN, frozenset({SUB}), [])  # the review stands


def test_the_decide_step_counts_drafts_in_their_own_bucket_not_as_engineer_to_check():
    from app import review_trace

    findings = [
        {"compliance_status": None, "origin": "ai_engineering_check"},
        {"compliance_status": None, "origin": "web_standard_check"},
        {"compliance_status": "NEEDS_ENGINEER_REVIEW", "origin": None},
        {"compliance_status": None, "origin": None},
    ]
    counts = review_trace._status_counts(findings)
    assert counts["NEEDS_ENGINEER_REVIEW"] == 1
    assert counts[ai_check_drafts.DRAFT_BUCKET] == 2
    assert (ai_check_drafts.DRAFT_BUCKET, ai_check_drafts.BUCKET_LABEL) in (
        review_trace._DECISIONS
    )


def test_the_two_claude_api_routes_settle_the_drafts_too(monkeypatch):
    """/ai-check and /web-check ran the checks but never settled them, so a
    run re-checked there kept its repeats unmarked."""
    from app import access, ai_engineering_check, claude_api, web_standards

    seen = []
    monkeypatch.setattr(ai_check_drafts, "settle", lambda run_id: seen.append(run_id))
    monkeypatch.setattr(ai_engineering_check, "available", lambda: (True, ""))
    monkeypatch.setattr(
        ai_engineering_check, "run_check", lambda *a, **k: {"ran": True}
    )
    monkeypatch.setattr(web_standards, "available", lambda: (True, ""))
    monkeypatch.setattr(web_standards, "run_check", lambda *a, **k: {"ran": True})
    monkeypatch.setattr("app.main._missing_references", lambda *a, **k: [])
    from app import market_transport

    monkeypatch.setattr(market_transport, "transport", lambda: None)
    scope = access.AccessScope(
        unrestricted=True, user_id="u", allowed_document_ids=frozenset({SUB})
    )
    request = type("R", (), {"query_params": {}})()
    claude_api.review_ai_check(RUN, request, scope)
    claude_api.review_web_check(RUN, request, scope)
    assert seen == [RUN, RUN]


def test_a_repeat_with_no_page_is_marked_once_and_a_rerun_adds_nothing():
    """The no-page note lacked the mark the skip check looks for, so every
    re-run appended it again."""
    _draft(None)
    _draft(None)
    assert ai_check_drafts.settle(RUN) == {"marked": 1}
    once = [r["ai_rationale"] for r in _rows()]
    assert ai_check_drafts.settle(RUN) == {"marked": 0}
    assert [r["ai_rationale"] for r in _rows()] == once
    assert sum(r.count("Exact repeat of") for r in once) == 1  # one mark, in total


def test_the_web_checks_exact_repeats_are_marked_by_their_source_address():
    def web(page, url):
        made = _draft(page, origin=ai_check_drafts.WEB_ORIGIN)
        with db.connect() as conn:
            conn.execute(
                "UPDATE review_findings SET ai_rationale = ? WHERE id = ?",
                (
                    f"Edition not confirmed. Source: Some page (2025), {url}. Quote: x",
                    made,
                ),
            )

    web(1, "https://example.test/a")
    web(2, "https://example.test/a")
    web(3, "https://example.test/b")  # same words, another source
    assert ai_check_drafts.settle(RUN) == {"marked": 1}
    rows = _rows(ai_check_drafts.WEB_ORIGIN)
    assert [("Exact repeat" in r["ai_rationale"]) for r in rows] == [False, True, False]
