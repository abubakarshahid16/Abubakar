"""The engineer's final review code, and what it protects.

MASTER PLAN SECTION 15. The AI performs the review and recommends a code; the
engineer's final action is GOVERNANCE, not the initial review. So both are
stored - the recommendation where `_store_run_outcome` wrote it, the decision
in columns of its own - and a screen can show what the machine said beside
what the engineer signed.

THE DECISION IS IN COLUMNS ON PURPOSE. "Which reviews are waiting for an
engineer" is a question the dashboard asks in SQL, and it cannot be asked of a
JSON blob.

A REASON IS REQUIRED WHEN THE TWO DIFFER and optional when they agree, which
is the difference between overriding a judgement and confirming one.

AND A DECIDED RUN IS NOT RE-RUN UNDERNEATH ITS SIGNATURE. `replace=True`
deletes a run's unconfirmed findings and writes new ones - that is how every
fix reaches the corpus - but doing it to a run somebody signed would leave the
code attached to findings it was never made about.

AND AN ENGINEER IS NOT AN ADMIN. The route depended on
`admin.current_admin` for the audit actor, and that dependency is a GATE: it
raises the admin surface's deliberately silent 404 for anyone who is not an
admin. So every ordinary engineer pressing "Record final code" was told "not
found" about a run the same screen had just listed. Nothing caught it, because
every test here called the function directly and the suite runs with
`AUTH_MODE=disabled`, where `current_admin` lets an anonymous caller through.
The last section signs in as a real non-admin and presses the button.

Mutations: M211-M215, `python scripts/mutation_check.py --phase 18`.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import access, auth, comparison, db, submittal_review
from app.config import settings
from app.main import app

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "code.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _run(recommended: str | None = comparison.CODE_MANUAL) -> tuple[str, frozenset]:
    doc = "doc_sub"
    with db.connect() as conn:
        # A REAL ENGINEER. `decided_by` references `users(id)`: the schema
        # itself refuses a decision signed by nobody, the same rule
        # `confirmed_by` follows, and a fixture that dodged it would be
        # testing a table shape production does not have.
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,"
            "password_hash,created_at) VALUES ('eng','eng@e.test','Eng','h',?)",
            (NOW,))
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc, "sheet.pdf", "sha-sub", "sheet.pdf", NOW))
    run_id = str(uuid.uuid4())
    outcome = json.dumps({
        "recommended_code": recommended,
        "reason": "the review examined 48 fields; the denominator is a "
                  "NOMINAL ESTIMATE of 385",
    }) if recommended else None
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,"
            "refusal_reason,created_at,updated_at) VALUES (?,?,'completed',?,?,?)",
            (run_id, doc, outcome, NOW, NOW))
    return run_id, frozenset({doc})


def _row(run_id: str) -> dict:
    return dict(db.connect().execute(
        "SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone())


def test_agreeing_with_the_recommendation_needs_no_reason():
    run_id, scope = _run()

    comparison.record_engineer_code(
        run_id, code=comparison.CODE_MANUAL, reviewer="eng",
        allowed_document_ids=scope)

    row = _row(run_id)
    assert row["engineer_final_code"] == comparison.CODE_MANUAL
    assert row["override_reason"] is None
    assert row["decided_by"] == "eng"
    assert row["decided_at"]


def test_overriding_the_recommendation_requires_a_reason():
    """THE GOVERNANCE RULE. Changing the machine's answer is a judgement
    somebody has to own in words."""
    run_id, scope = _run()

    with pytest.raises(comparison.ComparisonError) as caught:
        comparison.record_engineer_code(
            run_id, code=comparison.CODE_APPROVED_WITH_COMMENTS,
            reviewer="eng", allowed_document_ids=scope)

    assert "requires a reason" in str(caught.value)
    assert _row(run_id)["engineer_final_code"] is None, "it was written anyway"


def test_an_override_with_a_reason_is_recorded_with_it():
    run_id, scope = _run()

    comparison.record_engineer_code(
        run_id, code=comparison.CODE_APPROVED_WITH_COMMENTS, reviewer="eng",
        override_reason="both open items are lookup tables, not breaches",
        allowed_document_ids=scope)

    row = _row(run_id)
    assert row["engineer_final_code"] == comparison.CODE_APPROVED_WITH_COMMENTS
    assert row["override_reason"] == "both open items are lookup tables, not breaches"


def test_the_recommendation_survives_the_decision():
    """NEVER INSTEAD OF, ALWAYS BESIDE. An auditor asks what the machine
    said; a screen that could only show the final code could not answer."""
    run_id, scope = _run()

    comparison.record_engineer_code(
        run_id, code=comparison.CODE_APPROVED, reviewer="eng",
        override_reason="every open item was checked by hand",
        allowed_document_ids=scope)

    outcome = comparison.run_outcome(run_id, allowed_document_ids=scope)
    assert outcome["recommended_code"] == comparison.CODE_MANUAL
    assert "NOMINAL ESTIMATE" in outcome["reason"], \
        "the recommendation's own words were overwritten"


def test_a_code_that_is_not_a_review_code_is_refused():
    """AND REFUSED ON ITS OWN TERMS. This once answered "a reason is
    required", which sends the caller to fix the wrong field."""
    run_id, scope = _run()

    with pytest.raises(comparison.ComparisonError) as caught:
        comparison.record_engineer_code(
            run_id, code="Looks fine to me", reviewer="eng",
            allowed_document_ids=scope)

    assert "is not one of the review codes" in str(caught.value)
    assert "reason" not in str(caught.value)


def test_a_run_the_caller_cannot_read_is_not_found():
    """Scoped like everything else: the refusal is indistinguishable from a
    run that does not exist, because a different answer confirms it does."""
    run_id, _scope = _run()

    with pytest.raises(comparison.ComparisonError):
        comparison.record_engineer_code(
            run_id, code=comparison.CODE_MANUAL, reviewer="eng",
            allowed_document_ids=frozenset())


# ============================================ the decision is protected

def test_re_running_a_decided_run_is_refused():
    """THE POINT OF THE GUARD. Re-running underneath a signature would leave
    the code attached to findings it was never made about."""
    run_id, scope = _run()
    comparison.record_engineer_code(
        run_id, code=comparison.CODE_MANUAL, reviewer="eng",
        allowed_document_ids=scope)

    with pytest.raises(comparison.ComparisonError) as caught:
        comparison.run_comparison(run_id, allowed_document_ids=scope)

    assert "final code" in str(caught.value)
    assert "start a new review" in str(caught.value)


def test_a_run_without_a_decision_still_re_runs():
    """The guard on the guard: re-running is how every fix reaches the
    corpus, and only a DECIDED run is protected."""
    run_id, scope = _run()

    result = comparison.run_comparison(run_id, allowed_document_ids=scope)

    assert result["review_run_id"] == run_id


def test_a_new_run_is_never_blocked_by_another_runs_decision():
    """A new review is a new row. The decision protects the run it was made
    about, not the document forever."""
    run_id, scope = _run()
    comparison.record_engineer_code(
        run_id, code=comparison.CODE_MANUAL, reviewer="eng",
        allowed_document_ids=scope)

    second = submittal_review.create_review_run(
        submittal_document_id="doc_sub", allowed_document_ids=scope)
    result = comparison.run_comparison(second, allowed_document_ids=scope)

    assert result["review_run_id"] == second
    assert _row(run_id)["engineer_final_code"] == comparison.CODE_MANUAL, \
        "the first run's decision was disturbed"


# ============================== the name, not the primary key (phase 7, 0a)

def test_a_decided_run_carries_the_name_and_not_only_the_id():
    """THE SCREEN SHOWED `decided by user_phase6_demo`. An engineer knows
    their name; nobody knows their own row id. Both travel - the id for the
    audit trail and the tooltip, the name for the sentence."""
    run_id, scope = _run()
    comparison.record_engineer_code(
        run_id, code=comparison.CODE_MANUAL, reviewer="eng",
        allowed_document_ids=scope)

    run = submittal_review.get_review_run(run_id, allowed_document_ids=scope)

    assert run["decided_by"] == "eng"
    assert run["decided_by_name"] == "Eng"


def test_the_name_arrives_with_the_run_rather_than_a_lookup_per_row():
    """RESOLVED IN THE JOIN. Listing runs must not cost one user query per
    row, so the loader itself carries the name - asserted on the LIST path,
    which is the one that would have multiplied."""
    run_id, scope = _run()
    comparison.record_engineer_code(
        run_id, code=comparison.CODE_MANUAL, reviewer="eng",
        allowed_document_ids=scope)

    listed = submittal_review.list_review_runs(allowed_document_ids=scope)

    assert [r["decided_by_name"] for r in listed] == ["Eng"]


def test_an_undecided_run_has_no_name_rather_than_a_placeholder():
    """Null renders as nothing (CLAUDE.md rule 4). Not "unknown", and not the
    empty string dressed as a person."""
    run_id, scope = _run()

    run = submittal_review.get_review_run(run_id, allowed_document_ids=scope)

    assert run["decided_by"] is None
    assert run["decided_by_name"] is None


def test_a_decision_outlives_the_engineer_who_made_it():
    """`decided_by` is ON DELETE SET NULL, so a departed engineer's decision
    stays on the run with no name to show. The LEFT join is what keeps the
    run readable at all - an inner one would make it vanish."""
    run_id, scope = _run()
    comparison.record_engineer_code(
        run_id, code=comparison.CODE_APPROVED, reviewer="eng",
        override_reason="checked by hand", allowed_document_ids=scope)
    with db.connect() as conn:
        conn.execute("DELETE FROM users WHERE id = 'eng'")

    run = submittal_review.get_review_run(run_id, allowed_document_ids=scope)

    assert run is not None, "the run vanished with its author"
    assert run["engineer_final_code"] == comparison.CODE_APPROVED
    assert run["override_reason"] == "checked by hand"
    assert run["decided_by_name"] is None


# ================================ through the route, as a real engineer

def _signed_in_engineer(monkeypatch) -> tuple[TestClient, dict]:
    """A REAL, NON-ADMIN ENGINEER WITH A REAL TOKEN.

    Not `set_user_resolver`, and not the suite's default `AUTH_MODE=disabled`:
    the defect this section exists for lives in `admin.current_admin`, which
    reads the request's own token and waves an ANONYMOUS caller through under
    `disabled`. A test that skipped the login would therefore pass against the
    broken route, which is how it got in.
    """
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "is_active,created_at) VALUES ('eng','eng@e.test','Eng',?,1,?)",
            (auth._hasher.hash("engineer-pass"), NOW))
        # `_run` already inserted this user with a placeholder hash, and
        # INSERT OR IGNORE leaves it there - so set the real one either way.
        conn.execute("UPDATE users SET password_hash = ?, is_active = 1"
                     " WHERE id = 'eng'", (auth._hasher.hash("engineer-pass"),))
        conn.execute(
            "INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
            " VALUES ('role_eng','eng','engineers','discipline',?)", (NOW,))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,"
                     "granted_at) VALUES ('eng','role_eng',?)", (NOW,))
        conn.execute(
            "INSERT OR IGNORE INTO document_role_access (document_id,role_id,"
            "permission,granted_at) VALUES ('doc_sub','role_eng','read',?)",
            (NOW,))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    client = TestClient(app)
    login = client.post("/api/auth/login",
                        json={"email": "eng@e.test", "password": "engineer-pass"})
    assert login.status_code == 200, login.text
    return client, {"Authorization": f"Bearer {login.json()['token']}"}


def test_an_engineer_who_is_not_an_admin_can_record_the_final_code(monkeypatch):
    """THE DEFECT THIS SECTION EXISTS FOR. Section 15 gives the final code to
    the ENGINEER; the route gave it to admins and answered everyone else with
    the admin surface's silent 404 - about a run the same screen had listed."""
    run_id, _scope = _run()
    client, headers = _signed_in_engineer(monkeypatch)

    response = client.post(f"/api/reviews/runs/{run_id}/code",
                           json={"code": comparison.CODE_MANUAL,
                                 "override_reason": None}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["engineer_final_code"] == comparison.CODE_MANUAL
    assert _row(run_id)["decided_by"] == "eng", "signed by nobody"
    # And the wire carries the name, not only the id the column holds.
    assert response.json()["decided_by_name"] == "Eng"


def test_the_route_still_refuses_an_override_with_no_reason(monkeypatch):
    """The governance rule reaches the wire, and as a 422 about the reason -
    not the 404 that hid the whole route."""
    run_id, _scope = _run()
    client, headers = _signed_in_engineer(monkeypatch)

    response = client.post(
        f"/api/reviews/runs/{run_id}/code",
        json={"code": comparison.CODE_APPROVED_WITH_COMMENTS,
              "override_reason": None}, headers=headers)

    assert response.status_code == 422, response.text
    assert "requires a reason" in response.json()["detail"]["message"]
    assert _row(run_id)["engineer_final_code"] is None


def test_an_engineer_cannot_decide_a_run_they_may_not_read(monkeypatch):
    """Scoped on the wire too, and 404 rather than 403: a different answer
    would confirm the run exists."""
    run_id, _scope = _run()
    client, headers = _signed_in_engineer(monkeypatch)
    with db.connect() as conn:
        conn.execute("DELETE FROM document_role_access WHERE role_id='role_eng'")

    response = client.post(f"/api/reviews/runs/{run_id}/code",
                           json={"code": comparison.CODE_MANUAL,
                                 "override_reason": None}, headers=headers)

    assert response.status_code == 404
    assert _row(run_id)["engineer_final_code"] is None
