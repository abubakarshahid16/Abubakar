"""Order 224 item 4: the AI checks' drafts carry a status and a repeat is one row.

On the owner's I-06 run (four relief valves, one per page) the AI engineering
check wrote "valve size is blank" once per page, each with an EMPTY status.
Now every draft ends with "engineer to check", the same observation on several
pages is ONE row listing the pages and tags, and a draft can still never move
the suggested review code. Invented text, a throwaway database, no model.
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
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET review_run_id = ?, origin = ?, contractor_page = ?,"
            " contractor_section = ?, ai_rationale = 'AI engineering check.' WHERE id = ?",
            (RUN, origin, page, field, made["id"]),
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


def test_every_status_less_draft_ends_with_engineer_to_check():
    _draft(1, text="One thing.")
    _draft(2, text="Another thing.", field="Other")
    out = ai_check_drafts.settle(RUN)
    assert out == {"statused": 2, "merged": 0}
    assert {r["compliance_status"] for r in _rows()} == {"NEEDS_ENGINEER_REVIEW"}
    assert ai_check_drafts.settle(RUN) == {
        "statused": 0,
        "merged": 0,
    }  # a second call changes nothing


def test_the_web_checks_drafts_get_a_status_too():
    _draft(1, origin=ai_check_drafts.WEB_ORIGIN)
    ai_check_drafts.settle(RUN)
    assert [r["compliance_status"] for r in _rows(ai_check_drafts.WEB_ORIGIN)] == [
        "NEEDS_ENGINEER_REVIEW"
    ]


def test_four_pages_with_the_same_observation_become_one_row_listing_pages_and_tags():
    for page, tag in ((1, "PSV-1"), (2, "PSV-2"), (3, "PSV-3"), (4, "PSV-4")):
        _draft(page)
        _tag(page, tag)
    out = ai_check_drafts.settle(RUN)
    rows = _rows()
    assert out["merged"] == 3 and len(rows) == 1
    assert rows[0]["contractor_page"] == 1
    assert (
        "Same observation on pages 1, 2, 3, 4 (tags PSV-1, PSV-2, PSV-3, PSV-4)."
        in rows[0]["ai_rationale"]
    )
    assert rows[0]["compliance_status"] == "NEEDS_ENGINEER_REVIEW"


def test_different_observations_stay_separate():
    _draft(1, text="The valve size is blank.")
    _draft(2, text="The fluid phase is blank.", field="Fluid phase")
    _draft(
        3, text="The valve size is blank.", field="Other field"
    )  # same words, another field
    ai_check_drafts.settle(RUN)
    assert len(_rows()) == 3


def test_a_draft_an_engineer_decided_is_never_merged_or_removed():
    keep = _draft(1)
    decided = _draft(2)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET approval_status = 'approved', approved_by = 'eng' WHERE id = ?",
            (decided,),
        )
    ai_check_drafts.settle(RUN)
    ids = {r["id"] for r in _rows()}
    assert ids == {keep, decided}


def test_a_pile_of_drafts_never_moves_the_suggested_code():
    """The rule that mattered before the status: a draft cannot change the code."""
    met = {"compliance_status": "COMPLIANT", "origin": None}
    drafts = [
        {"compliance_status": "NEEDS_ENGINEER_REVIEW", "origin": "ai_engineering_check"}
    ] * 40
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
