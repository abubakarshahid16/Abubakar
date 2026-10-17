"""#196: what an SMTP notification may carry.

WHAT WAS WRONG. `notifications.py` is the fourth module that opens a socket
(CLAUDE.md rule 1), but nothing pinned what goes into a message. A sender that
began to include a finding's text, a document's filename or a page reference
would have sent it to the mail server with every test green.

THE RULE THIS FILE ENFORCES. Each sender builds its subject and body from a
FIXED TEMPLATE plus the fields it is given: counts, a date, an escalation
level, deliverable and risk titles. Nothing read from a document - chunk text,
a finding's requirement or evidence, a filename, a page number - is ever a
field. Two layers:

  1. per sender, the exact message for sentinel field values, so a new field
     or a changed template turns this red;
  2. one end-to-end detection run over a document whose filename, finding
     text and evidence are sentinels, with every message the run sends
     captured and searched for them.

Deliverable and risk titles DO go out: they are register metadata, entered or
imported as deliverable rows, not text read from a document page.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest

from app import db, deliverables, notifications, review, risks
from app.config import settings


class CapturingSMTP:
    """Stands in for `smtplib.SMTP`; keeps every message, sends nothing."""
    sent: ClassVar[list] = []

    def __init__(self, host, port, timeout):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self, context=None):
        pass

    def close(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        CapturingSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def smtp_on(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "bodies.sqlite")
    db.reset_connection()
    db.init_db()
    deliverables.ensure_schema()
    review.ensure_schema()
    risks.ensure_schema()
    for name, value in {
        "smtp_enabled": True, "smtp_host": "smtp.example.test", "smtp_port": 587,
        "smtp_username": "", "smtp_password": "", "smtp_from": "epc@example.test",
        "smtp_recipient": "controls@example.test", "smtp_starttls": True,
        "risk_digest_min_interval_seconds": 0,
    }.items():
        monkeypatch.setattr(settings, name, value)
    CapturingSMTP.sent = []
    monkeypatch.setattr(notifications.smtplib, "SMTP", CapturingSMTP)
    yield
    db.reset_connection()


def _only_message() -> tuple[str, str]:
    assert len(CapturingSMTP.sent) == 1
    message = CapturingSMTP.sent[0]
    return message["Subject"], message.get_content().rstrip("\n")


# ----------------------------------------------- 1. one template per sender


def test_reminder_is_its_template_and_the_given_fields_only():
    notifications.send_reminder(deliverable_id="d-1", title="TITLE-A",
                                due_date="2026-01-02")
    assert _only_message() == (
        "EPC deliverable reminder: TITLE-A",
        "Deliverable TITLE-A is due or overdue (2026-01-02).",
    )


def test_escalation_is_its_template_and_the_given_fields_only():
    notifications.send_escalation(deliverable_id="d-1", title="TITLE-B", level=3)
    assert _only_message() == (
        "EPC escalation level 3: TITLE-B",
        "Deliverable TITLE-B has reached escalation level 3.",
    )


def test_daily_summary_is_three_counts_and_drops_every_other_key():
    notifications.send_daily_summary({
        "deliverables_total": 4, "overdue_alerts": 1, "escalated_findings": 2,
        # a caller handing over more than counts must not widen the message
        "finding_text": "SENTINEL-FINDING", "filename": "SENTINEL.pdf",
    })
    assert _only_message() == (
        "EPC daily management summary",
        "EPC daily management summary\nDeliverables: 4\nOverdue alerts: 1\n"
        "Escalated findings: 2",
    )


def test_risk_digest_is_counts_and_titles_and_drops_every_other_key():
    created = [
        {"risk_type": "schedule", "title": "TITLE-C",
         "description": "SENTINEL-DESCRIPTION", "document_id": "SENTINEL-DOC"},
        {"risk_type": "review", "title": "TITLE-D",
         "description": "SENTINEL-DESCRIPTION", "document_id": "SENTINEL-DOC"},
    ]
    assert notifications.send_risk_digest(created) == "sent"
    assert _only_message() == (
        "EPC risk digest: 2 new",
        "EPC risk detection: 2 new risk(s)\nreview: 1\nschedule: 1\n\n"
        "- TITLE-C\n- TITLE-D",
    )


# --------------------------------------- 2. a real run over a real document


def test_a_detection_run_sends_nothing_read_from_a_document():
    """Every message a full detection run sends, searched for the document's
    filename and the finding's text. The run must actually send (a reminder
    and a digest), or "nothing leaked" would pass on silence."""
    filename = "SENTINEL-FILENAME-Q7.pdf"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES ('doc', ?, 'hash', 1, 'x', 'ready', '2020-01-01')", (filename,))
    overdue = (datetime.now(UTC).date() - timedelta(days=8)).isoformat()
    deliverables.create({"wbs_code": "1.1", "title": "Pump datasheet",
                         "deliverable_type": "PDF", "due_date": overdue,
                         "document_id": "doc"}, created_by=None)
    finding = review.create({
        "document_id": "doc", "category": "requirement_deviation", "severity": "major",
        "requirement": "SENTINEL-REQUIREMENT on page 14",
        "finding": "SENTINEL-FINDING quoted from the sheet",
        "required_action": "SENTINEL-ACTION",
        "unresolved_evidence": ["SENTINEL-EVIDENCE p.14"],
    }, created_by=None)
    with db.connect() as conn:
        conn.execute("UPDATE review_findings SET updated_at='2020-01-01' WHERE id=?",
                     (finding["id"],))

    result = risks.run_detection()

    assert result["digest"] == "sent"
    assert len(CapturingSMTP.sent) >= 2, "the run sent nothing; the check below would be vacuous"
    for message in CapturingSMTP.sent:
        text = f"{message['Subject']}\n{message.get_content()}"
        for leaked in ("SENTINEL", filename, "page 14", "p.14", ".pdf"):
            assert leaked not in text, f"{leaked!r} went out by SMTP:\n{text}"
