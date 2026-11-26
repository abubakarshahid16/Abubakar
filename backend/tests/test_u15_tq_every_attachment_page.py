"""Every page of a query's attachment is read for questions, up to ATTACHMENT_PAGES_READ (lead-4, 26 Nov 2026: 5 pages left half of the
found-question attachments' pages unread); past it the page says which pages were not read AND why. Invented pages only."""

from __future__ import annotations

from app import db, technical_queries
from app.technical_queries import import_message, link_attachment, prepare_evidence

from .test_technical_queries import (  # noqa: F401 - the fixture is used by name
    envelope,
    hold_contract,
    temp_storage,
)


def _query_with_pages(monkeypatch, pages: int):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at,page_count) VALUES (?,?,?,?,?,?,?,?)",
            ("form-pdf", "form.pdf", "d" * 64, 1, "form.pdf", "ready", "2026-01-01T00:00:00Z", pages),
        )
        for n in range(1, pages + 1):
            text = f"Invented request {n}: please confirm the invented value on page {n}?"
            conn.execute(
                "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES (?,?,?,?,?,?)",
                ("form-pdf", n, text, len(text), 0, 1),
            )
    payload = envelope("form-pages")
    payload["body"] = "Please see attached."
    payload["question"] = None
    item, _ = import_message(payload, "u1", False, False)
    link_attachment(item["id"], item["messages"][0]["attachments"][0]["id"], "form-pdf", "u1", "u1", True, False)
    hold_contract("contract-1")
    # the model lists the request printed on the page it reads
    monkeypatch.setattr("app.technical_query_questions._ask", lambda page_text: [page_text])
    monkeypatch.setattr("app.search.search", lambda question, **kwargs: {"hits": []})
    return prepare_evidence(item["id"], frozenset({"form-pdf", "contract-1"}), "u1", True, False, "u1")


def test_a_seven_page_form_is_read_to_its_last_page_and_its_page_seven_request_is_proposed(monkeypatch):
    result = _query_with_pages(monkeypatch, 7)
    assert [p["page"] for p in result["attachment_context"]] == [1, 2, 3, 4, 5, 6, 7]
    assert [p["page"] for p in result["proposed_questions"]] == [1, 2, 3, 4, 5, 6, 7]
    assert result["attachment_reading"][0]["line"] == "query.pdf: pages 1 to 7 of 7 read."


def test_past_the_limit_the_page_says_which_pages_were_not_read_and_why(monkeypatch):
    monkeypatch.setattr(technical_queries, "ATTACHMENT_PAGES_READ", 3)
    result = _query_with_pages(monkeypatch, 5)
    assert [p["page"] for p in result["attachment_context"]] == [1, 2, 3]
    assert result["attachment_reading"][0]["line"] == (
        "query.pdf: pages 1 to 3 of 5 read; pages 4 to 5 were not read: the reading stops at 3 pages per attachment."
    )
