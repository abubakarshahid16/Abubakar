"""The four cards of master plan section 20, and what each one counts.

CLAUDE.md RULE 10 NAMES THIS SCREEN'S CONTENTS EXACTLY: Contractor Submittals,
Active Standards, Reviews in Progress, Needs Attention, one button, one Recent
Reviews table. So the endpoint behind it is not a metrics dump - it answers
four questions, and this file asserts what each answer is counted over.

RULE 4 IS WHY THE PAIRS EXIST. `submittals_awaiting_review` is meaningless
without `submittals_total`, and `standards_referenced_missing` without
`standards_referenced_total`: a tile reading "21" with no population is the
percentage-without-a-denominator defect. Both halves are returned together,
and a test here fails if one is dropped.

NEEDS ATTENTION SAYS WHY. The breakdown is not decoration - it is the only
thing that makes the number checkable, and it must sum to the number.

AND IT IS SCOPED LIKE EVERYTHING ELSE. The dashboard counts documents; a
caller who may not read a submittal must not learn it exists by watching a
tile go up (rule 5: a filter may only narrow).

Mutations: M216-M219, `python scripts/mutation_check.py --phase 19`.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import access, comparison, db, submittal_review
from app.config import settings
from app.main import app

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "dash.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    app.dependency_overrides.clear()
    access.set_user_resolver(None)
    db.reset_connection()


def _document(doc_id: str, role: str) -> str:
    """A document with the role the dashboard counts by.

    `document_role` says what part the document plays in a review and grants
    nothing (rule 5); the scope below is the authorisation decision.
    """
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"/tmp/{doc_id}", NOW))
        conn.execute(
            "INSERT INTO document_classification (document_id,document_role,"
            "suggested_by) VALUES (?,?,'test')", (doc_id, role))
    return doc_id


def _run(doc_id: str, status: str, recommended: str | None = None) -> str:
    run_id = str(uuid.uuid4())
    outcome = json.dumps(
        {"recommended_code": recommended, "reason": "measured"}
    ) if recommended else None
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,"
            "refusal_reason,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (run_id, doc_id, status, outcome, NOW, NOW))
    return run_id


def _engineer() -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "created_at) VALUES ('eng','eng@e.test','Eng','h',?)", (NOW,))
    return "eng"


def _dashboard(*allowed: str) -> dict:
    """Read the endpoint under an EXPLICIT scope.

    The dependency is overridden rather than left unrestricted so that the
    scoping test below has something real to narrow - an unrestricted scope
    would make every count pass whether the filter is there or not.
    """
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed))
    # NO LIFESPAN, DELIBERATELY. `with TestClient(app)` runs startup, and
    # startup sweeps every run still marked `running` to `failed` - correct
    # behaviour (test_orphaned_review_runs.py), and it would silently rewrite
    # this file's fixtures between the seed and the request, so a test about a
    # review in progress would be measuring a failed one.
    client = TestClient(app)
    response = client.get("/api/reviews/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------- card 1: contractor submittals

def test_a_submittal_with_no_completed_run_is_awaiting_review():
    """AND THE TILE CARRIES ITS OWN DENOMINATOR. "1 awaiting" answers
    nothing; "1 of 2" is a fact somebody can check."""
    reviewed, waiting = _document("doc_a", "CONTRACTOR_SUBMITTAL"), \
        _document("doc_b", "CONTRACTOR_SUBMITTAL")
    _run(reviewed, "completed")

    body = _dashboard(reviewed, waiting)

    assert body["submittals_total"] == 2
    assert body["submittals_awaiting_review"] == 1


def test_a_run_that_is_still_running_does_not_count_as_reviewed():
    """Started is not finished. Counting a running review as done would
    report work that has not happened."""
    doc = _document("doc_a", "CONTRACTOR_SUBMITTAL")
    _run(doc, "running")

    body = _dashboard(doc)

    assert body["submittals_awaiting_review"] == 1
    assert body["reviews_running"] == 1


# ------------------------------------------------- card 2: active standards

def test_standards_are_counted_by_role_not_by_being_a_document():
    standard = _document("doc_std", "COMPANY_STANDARD")
    submittal = _document("doc_sub", "CONTRACTOR_SUBMITTAL")

    body = _dashboard(standard, submittal)

    assert body["standards_available"] == 1
    assert body["submittals_total"] == 1


# --------------------------------------- card 3: reviews awaiting a decision

def test_a_completed_run_with_no_engineer_code_is_awaiting_a_decision():
    doc = _document("doc_a", "CONTRACTOR_SUBMITTAL")
    _run(doc, "completed", comparison.CODE_APPROVED)

    body = _dashboard(doc)

    assert body["reviews_awaiting_decision"] == 1
    assert body["reviews_total"] == 1


def test_recording_the_engineer_code_takes_the_run_off_the_waiting_list():
    """THE WHOLE POINT OF THE COLUMN. "Which reviews are waiting for an
    engineer" is asked in SQL over `engineer_final_code`; if the decision
    lived in a JSON blob this tile could not be computed at all."""
    doc = _document("doc_a", "CONTRACTOR_SUBMITTAL")
    run_id = _run(doc, "completed", comparison.CODE_APPROVED)
    scope = frozenset({doc})
    assert _dashboard(doc)["reviews_awaiting_decision"] == 1

    comparison.record_engineer_code(
        run_id, code=comparison.CODE_APPROVED, reviewer=_engineer(),
        allowed_document_ids=scope)

    body = _dashboard(doc)
    assert body["reviews_awaiting_decision"] == 0
    assert body["reviews_total"] == 1, "the run itself disappeared"


# ------------------------------------------------- card 4: needs attention

def test_needs_attention_says_why_and_the_reasons_sum_to_the_number():
    """A BARE TILE READING "3" IS A NUMBER A READER HAS TO TRUST. The
    breakdown is what makes it auditable, and a breakdown that does not add
    up to the total is worse than none."""
    doc = _document("doc_a", "CONTRACTOR_SUBMITTAL")
    _run(doc, "failed")
    _run(doc, "completed", comparison.CODE_MANUAL)
    _run(doc, "completed", comparison.CODE_REJECTED)
    _run(doc, "completed", comparison.CODE_APPROVED)

    body = _dashboard(doc)

    assert body["needs_attention"] == 3, "an approved run needs no attention"
    assert sum(body["needs_attention_reasons"].values()) == body["needs_attention"]
    assert set(body["needs_attention_reasons"]) == {
        "the run failed", "rejected", "not enough was read to recommend a code"}


def test_the_engineers_decision_is_what_counts_not_the_recommendation():
    """The engineer overrode "manual review required" with a reason. The
    tile must follow the decision, or it keeps reporting a question that has
    already been answered."""
    doc = _document("doc_a", "CONTRACTOR_SUBMITTAL")
    run_id = _run(doc, "completed", comparison.CODE_MANUAL)
    assert _dashboard(doc)["needs_attention"] == 1

    comparison.record_engineer_code(
        run_id, code=comparison.CODE_APPROVED, reviewer=_engineer(),
        override_reason="every open item was checked by hand",
        allowed_document_ids=frozenset({doc}))

    assert _dashboard(doc)["needs_attention"] == 0


# ------------------------------------------------------------- and scoped

def test_a_document_outside_the_grant_set_is_counted_nowhere():
    """RULE 5. A tile that went up for a document the caller may not read
    would leak that it exists - and the recent table would name it."""
    mine = _document("doc_mine", "CONTRACTOR_SUBMITTAL")
    theirs = _document("doc_theirs", "CONTRACTOR_SUBMITTAL")
    _document("doc_std_theirs", "COMPANY_STANDARD")
    _run(theirs, "completed", comparison.CODE_MANUAL)
    _run(mine, "running")

    body = _dashboard(mine)

    assert body["submittals_total"] == 1
    assert body["standards_available"] == 0
    assert body["reviews_total"] == 1
    assert body["needs_attention"] == 0, "another caller's run raised my tile"
    assert [run["submittal_document_id"] for run in body["recent"]] == [mine]


def test_an_empty_grant_set_counts_nothing():
    """Not an error and not everything: the empty set is a real answer, and
    `WHERE 1 = 0` is what makes it one."""
    doc = _document("doc_a", "CONTRACTOR_SUBMITTAL")
    _run(doc, "completed", comparison.CODE_MANUAL)

    body = _dashboard()

    assert body["submittals_total"] == 0
    assert body["reviews_total"] == 0
    assert body["needs_attention"] == 0
    assert body["recent"] == []


# ------------------------------------------- the recent table, not a dump

def test_the_recent_table_stays_compact():
    """Rule 10 says ONE COMPACT TABLE. Six runs, five rows - a dashboard
    that grows without bound is the metrics dump the rule forbids."""
    doc = _document("doc_a", "CONTRACTOR_SUBMITTAL")
    for _ in range(6):
        _run(doc, "completed", comparison.CODE_APPROVED)

    body = _dashboard(doc)

    assert body["reviews_total"] == 6
    assert len(body["recent"]) == 5


def test_a_cited_standard_the_library_holds_is_not_counted_missing():
    """THE TILE READ "21 OF 21 CITED STANDARDS ARE NOT IN THE LIBRARY" -
    because its check compared identifiers against document ids and called
    everything missing. One held, one not: the tile must say 1 of 2."""
    submittal = _document("doc_sub", "CONTRACTOR_SUBMITTAL")
    held = _document("doc_l132", "COMPANY_STANDARD")
    with db.connect() as conn:
        conn.execute("UPDATE documents SET filename='SAES-L-132.pdf'"
                     " WHERE id='doc_l132'")
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
            "page_end,text,token_count,content_hash)"
            " VALUES ('c1',?,'sub.pdf',0,1,1,?,10,'h1')",
            (submittal, "Design per SAES-L-132 and 32-SAMSS-004."))

    body = _dashboard(submittal, held)

    assert body["standards_referenced_total"] == 2
    assert body["standards_referenced_missing"] == 1
