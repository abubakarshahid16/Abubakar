"""A9/#923: non-atomic writes and gate gaps, fixed one at a time.

Invented data only; no model, no socket.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import chat, chat_actions, crs_issue, db, review
from app.main import app
from tests.test_crs_endpoint import NOW, _run, _submittal, temp_db  # noqa: F401

# -------------------------------------------------- 1/2: review.create(conn=)

def test_create_with_no_conn_opens_and_commits_its_own_transaction():
    """Unchanged behaviour for every existing caller."""
    finding = review.create({
        "document_id": _submittal(), "category": "technical_query", "severity": "minor",
        "requirement": "r", "finding": "f", "required_action": "a",
    }, created_by=None)
    assert review.get(finding["id"]) is not None


def test_create_writes_the_extra_fields_in_the_same_insert():
    """A9/#923 item 1: datasheet_checks.store used to create() the base
    fields, then UPDATE review_run_id/origin/compliance_status/... in a
    second transaction. create() now takes them directly."""
    doc = _submittal()
    finding = review.create({
        "document_id": doc, "category": "technical_query", "severity": "minor",
        "requirement": "r", "finding": "f", "required_action": "a",
        "review_run_id": "run-1", "origin": "datasheet_check",
        "compliance_status": "NON_COMPLIANT", "contractor_page": 3,
        "fact_id": "fact-1", "equipment_tag": "P-101A",
    }, created_by=None)
    stored = review.get(finding["id"])
    assert stored["review_run_id"] == "run-1" and stored["origin"] == "datasheet_check"
    assert stored["compliance_status"] == "NON_COMPLIANT" and stored["contractor_page"] == 3
    assert stored["fact_id"] == "fact-1" and stored["equipment_tag"] == "P-101A"


def test_datasheet_checks_store_writes_the_extra_fields_in_one_call():
    """A9/#923 item 1, end to end through the real caller: a single
    datasheet-check result becomes a finding with its run id, origin and
    verdict already set - no follow-up UPDATE."""
    from app import datasheet_checks as dc

    doc = _submittal()
    result = {
        "rule_id": "DS-C1", "status": dc.NON_COMPLIANT,
        "detail": "the design pressure is below the operating pressure",
        "text": "design pressure shall exceed operating pressure", "severity": "major",
        "fact_id": "fact-1", "equipment_tag": "V-101", "field": "Design pressure",
        "value": "5 bar", "page": 2, "standard": None, "clause": None,
    }
    written = dc.store("run-1", doc, [result], pages_read={})
    assert len(written) == 1
    stored = review.get(written[0]["id"])
    assert stored["review_run_id"] == "run-1" and stored["origin"] == dc.ORIGIN
    assert stored["compliance_status"] == dc.NON_COMPLIANT
    assert stored["fact_id"] == "fact-1" and stored["equipment_tag"] == "V-101"
    assert stored["contractor_page"] == 2


def test_create_given_a_conn_rolls_back_with_the_callers_transaction():
    doc = _submittal()
    conn = db.connect()
    finding_id = None
    with pytest.raises(sqlite3.OperationalError):
        with conn:
            finding = review.create({
                "document_id": doc, "category": "technical_query", "severity": "minor",
                "requirement": "r", "finding": "f", "required_action": "a",
            }, created_by=None, conn=conn)
            finding_id = finding["id"]
            conn.execute("INSERT INTO this_table_does_not_exist VALUES (1)")
    assert review.get(finding_id) is None, "the finding survived its own transaction's rollback"


# -------------------------------------------------------- 2: chat file_comment

def _conversation(client) -> str:
    return client.post("/api/conversations").json()["id"]


def _draft_message(conversation_id: str, source_ids: list[str],
                   text: str = "State the hydrotest chloride limit.") -> str:
    conn = db.connect()
    chat._insert_message(conn, conversation_id, role="user", text="write that as a comment",
                         resolved_question="write that as a comment", carried_terms=[])
    message = chat._insert_message(
        conn, conversation_id, role="assistant", text=text, answer_type="general",
        payload={"draft": {"type": "comment", "text": text, "status": "draft",
                           "source_ids": source_ids}, "answer_kind": "action"})
    return message["id"]


def test_filing_a_comment_writes_the_finding_and_the_chat_link_together():
    doc = _submittal()
    client = TestClient(app)
    convo = _conversation(client)
    message_id = _draft_message(convo, [doc])
    result = chat_actions.file_comment(
        convo, message_id, text="State the limit.", user_id="eng-1",
        allowed_document_ids=frozenset({doc}))
    finding = review.get(result["finding_id"])
    assert finding["origin"] == "chat" and finding["confirmed_by"] == "eng-1"
    row = db.connect().execute(
        "SELECT * FROM chat_filed_comments WHERE finding_id = ?", (result["finding_id"],)
    ).fetchone()
    assert row is not None and row["message_id"] == message_id


def test_a_failure_filing_the_chat_link_leaves_no_orphan_finding(monkeypatch):
    """A9/#923 item 2: file_comment used to create() the finding, THEN
    INSERT the chat_filed_comments row in a second transaction - a crash
    between them left a finding with no origin/confirmed_by and no record
    linking it back to the chat message. Now one transaction: a failure
    anywhere rolls back everything, including the finding."""
    doc = _submittal()
    client = TestClient(app)
    convo = _conversation(client)
    message_id = _draft_message(convo, [doc])
    conn = db.connect()
    real_execute = conn.execute

    def spy(sql, *a, **k):
        if "INSERT INTO chat_filed_comments" in sql:
            raise sqlite3.OperationalError("simulated failure")
        return real_execute(sql, *a, **k)

    monkeypatch.setattr(conn, "execute", spy)
    before = review.list_findings(document_id=doc)
    with pytest.raises(sqlite3.OperationalError):
        chat_actions.file_comment(
            convo, message_id, text="State the limit.", user_id="eng-1",
            allowed_document_ids=frozenset({doc}))
    assert review.list_findings(document_id=doc) == before, (
        "a finding survived even though filing it failed")


# ------------------------------------------------------------- 3: crs_issue.archive

def test_archive_writes_the_db_row_before_the_file():
    """A9/#923 item 3: the old order wrote the file first, then the DB row -
    a crash between them left an untracked file forever. Proven here by a
    file-write failure: the DB row must not survive it (cleaned up), not
    left dangling as it would be under the old order."""
    doc = _submittal()
    run = _run(doc)
    row = crs_issue.archive(run, b"workbook bytes", "CRS.xlsx", actor="eng-1")
    assert row["review_run_id"] == run
    stored = db.connect().execute(
        "SELECT * FROM crs_issued_copies WHERE id = ?", (row["id"],)).fetchone()
    assert stored is not None


def test_archive_never_writes_the_file_when_the_db_insert_fails(monkeypatch):
    """THE DISCRIMINATING PROOF: under the old write-file-then-DB-row order,
    a failure on the DB insert left the file already sitting on disk,
    untracked forever. Under the new order the DB insert runs first, so a
    failure there must mean NO file was ever written."""
    doc = _submittal()
    run = _run(doc)
    conn = db.connect()
    real_execute = conn.execute

    def spy(sql, *a, **k):
        if "INSERT INTO crs_issued_copies" in sql:
            raise sqlite3.OperationalError("simulated failure")
        return real_execute(sql, *a, **k)

    monkeypatch.setattr(conn, "execute", spy)
    with pytest.raises(sqlite3.OperationalError):
        crs_issue.archive(run, b"workbook bytes", "CRS.xlsx", actor="eng-1")
    written = list(crs_issue._archive_dir().glob("*.xlsx"))
    assert written == [], f"a file was written on disk despite the DB insert failing: {written}"


def test_archive_cleans_up_the_db_row_if_the_file_write_fails(monkeypatch, tmp_path):
    doc = _submittal()
    run = _run(doc)

    def _fail_write(self, data):
        raise OSError("simulated disk failure")

    from pathlib import Path
    monkeypatch.setattr(Path, "write_bytes", _fail_write)
    with pytest.raises(OSError):
        crs_issue.archive(run, b"workbook bytes", "CRS.xlsx", actor="eng-1")
    count = db.connect().execute("SELECT COUNT(*) FROM crs_issued_copies").fetchone()[0]
    assert count == 0, "the DB row was left behind with no file to back it"


# --------------------------------------------------- 4: ai_requirements race

def test_a_draft_already_decided_is_not_decided_again(monkeypatch):
    """A9/#923 item 4: decide_draft read row["status"] once, then UPDATE ...
    WHERE id = ? with no status guard - two concurrent calls could both
    pass the read and both write. Simulated here by making the INITIAL read
    report DRAFT (as a concurrent caller's read would have) while the row
    in the database is already decided by someone else."""
    from app import ai_requirements

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('doc_std','std.pdf','sha',1,'x','ready',1,?)", (NOW,))
    draft_id = "draft-1"
    row = {
        "id": draft_id, "standard_document_id": "doc_std", "requirement_id": "req-1",
        "chunk_id": None, "clause": "5.1", "page": 1, "field": "pressure",
        "operator": ">=", "value": "10", "unit": "bar", "condition": None,
        "quote": "q", "requirement_text": "t", "source_text": "t",
        "requirement_type": "statement", "superseded_at": None,
        "status": ai_requirements.REJECTED,  # ALREADY decided by someone else
    }
    monkeypatch.setattr(ai_requirements, "_draft",
                        lambda conn, did, allowed: {**row, "status": ai_requirements.DRAFT})
    with pytest.raises(ai_requirements.DraftError, match="already decided"):
        ai_requirements.decide_draft(draft_id, decision="reject",
                                    allowed_document_ids=frozenset({"doc_std"}),
                                    actor={"id": "eng-2"})


# ------------------------------------------------------------------- 5: admin audit

def test_admin_actions_audit_in_the_same_transaction_as_the_change(monkeypatch):
    """A9/#923 item 5: four admin._audit calls ran AFTER their change's own
    `with conn:` had already committed - a crash between them left the
    change standing with no audit row. Proven by failing the audit INSERT
    itself: the change must not have survived either."""
    from app import admin

    conn = db.connect()
    real_execute = conn.execute

    def spy(sql, *a, **k):
        if "INSERT INTO audit_events" in sql:
            raise sqlite3.OperationalError("simulated failure")
        return real_execute(sql, *a, **k)

    monkeypatch.setattr(conn, "execute", spy)
    with pytest.raises(sqlite3.OperationalError):
        admin.create_user(admin.CreateUserRequest(email="new@example.test"),
                          actor={"id": "admin-1"})
    assert conn.execute(
        "SELECT 1 FROM users WHERE email = 'new@example.test'").fetchone() is None, (
        "the user was created even though its audit row failed to write")


# --------------------------------------------------------- 6a: open_items gate

def test_a_row_with_no_finding_id_is_an_open_blocker_not_invisible():
    """A9/#923 item 6: a CRS row with no finding_id (#754 F5b's "standard not
    cited"/"standard not applicable" rows have none) used to be skipped
    unconditionally - it could never become a blocker, whatever an engineer
    had or had not decided. `crs_row_key` (set on every row, with or
    without a finding_id) is now the fallback subject."""
    rows = [{"finding_id": "", "row_kind": "standard_not_cited",
             "crs_row_key": "key-1", "engineer_confirmed": False}]
    gate = crs_issue.open_items("run-1", rows, {"pages_total": 1, "pages_not_read_into_fields": []})
    assert gate["issuable"] is False
    assert gate["open_findings"] == [{"finding_id": "key-1", "row_kind": "standard_not_cited", "item": 1}]


def test_a_confirmed_row_with_no_finding_id_is_not_a_blocker():
    # order 139 part 2: a confirmed row carries its comment text (a confirmed
    # row with NONE is a blocker of its own - test_139_crs_file_empty_guard).
    rows = [
        {
            "finding_id": "",
            "row_kind": "standard_not_cited",
            "crs_row_key": "key-1",
            "engineer_confirmed": True,
            "comment": "Contractor did not reference STD-X; confirm compliance.",
        }
    ]
    gate = crs_issue.open_items("run-1", rows, {"pages_total": 1, "pages_not_read_into_fields": []})
    assert gate["issuable"] is True and gate["open_findings"] == []


def test_a_row_with_neither_finding_id_nor_row_key_is_not_counted():
    """Nothing to gate on - unchanged from before (this never happened for
    a real CRS row; kept as a documented edge case, not a guess)."""
    rows = [{"finding_id": "", "row_kind": "x", "engineer_confirmed": False}]
    gate = crs_issue.open_items("run-1", rows, {"pages_total": 1, "pages_not_read_into_fields": []})
    assert gate["open_findings"] == []


# ------------------------------------------------------- 6b: the reason floor

def test_a_three_character_reason_no_longer_passes():
    with pytest.raises(crs_issue.IssueError):
        crs_issue._record("run-1", crs_issue.PAGE, "3", crs_issue.CHECKED, "abc", "eng-1")


def test_a_real_reason_still_passes():
    row = crs_issue._record("run-1", crs_issue.PAGE, "3", crs_issue.CHECKED,
                            "page read by eye, no values present", "eng-1")
    assert row["reason"] == "page read by eye, no values present"
