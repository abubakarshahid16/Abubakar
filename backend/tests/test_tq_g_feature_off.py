"""Technical queries brought live as its own update, sending OFF (order 14, planner 25 Nov 2026). The one way-back switch, the read-only Gmail
scope, the send lock, the per-contract evidence search with its coverage line, the questions proposed one by one, the refused Claude draft and
the query entered by hand. No Gmail call and no paid call: every transport is a fake that fails the test if it is reached. Invented values."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app import db, gmail_auth, gmail_sync
from app import technical_queries as tq
from app.access import AccessScope
from app.api import technical_queries as api
from app.config import Settings, settings
from app.gmail_client import GmailApiClient
from app.main import app
from tests.test_technical_queries import envelope, hold_contract

IDEMPOTENCY = "-".join(["send", "once", "please"])
REVIEWER = frozenset({"admin", tq.REVIEWER_CAPABILITY})


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "q.sqlite")
    monkeypatch.setattr(tq, "_READY_FOR", None)
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users(id,email,display_name,password_hash,created_at) VALUES ('u1','u1@example.test','U','x','2026-01-01T00:00:00Z')"
        )
    yield
    db.reset_connection()


def on(monkeypatch):
    monkeypatch.setattr(settings, "technical_queries_enabled", True)
    tq.ensure_schema()


def no_socket(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("a socket would have been opened")

    monkeypatch.setattr(httpx, "request", boom)
    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx, "Client", boom)


def tables(name="technical_queries") -> bool:
    with db.connect() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = ?", (name,)
            ).fetchone()
            is not None
        )


# ---------------------------------------------------------------- F2: the one way-back switch


def test_both_switches_are_off_by_default():
    fresh = Settings()
    assert (
        fresh.technical_queries_enabled is False
        and fresh.technical_query_claude_draft_enabled is False
    )


def test_switched_off_every_route_answers_not_found_and_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "technical_queries_enabled", False)
    client = TestClient(app)
    for method, path in (
        ("get", "/api/technical-queries"),
        ("get", "/api/technical-queries/metrics"),
        ("get", "/api/technical-queries/providers/gmail/oauth/start"),
        ("get", "/api/technical-queries/providers/gmail/mailboxes"),
        ("post", "/api/technical-queries/providers/gmail/webhook"),
        ("post", "/api/technical-queries/manual"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 404 and tq.OFF_WORDS in response.text, path
    assert not tables()  # not even the tables are made


def test_the_menu_is_told_by_the_servers_own_answer(monkeypatch):
    client = TestClient(app)
    monkeypatch.setattr(settings, "technical_queries_enabled", False)
    assert client.get("/api/auth/me").json()["technical_queries"] is False
    monkeypatch.setattr(settings, "technical_queries_enabled", True)
    assert client.get("/api/auth/me").json()["technical_queries"] is True


def test_switched_off_no_poller_starts_and_no_mailbox_is_read(monkeypatch):
    on(monkeypatch)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO gmail_mailboxes(id,owner_user_id,email,last_history_id,label_id,connection_state,connected_at,updated_at) VALUES ('mb','u1','e@example.test','h1','L','active','x','x')"
        )
    monkeypatch.setattr(settings, "technical_queries_enabled", False)
    monkeypatch.setattr(gmail_sync, "_thread", None)
    gmail_sync.start()
    assert gmail_sync._thread is None and gmail_sync.run_once() == 0


def test_switched_off_a_gmail_call_opens_no_socket(monkeypatch):
    monkeypatch.setattr(settings, "technical_queries_enabled", False)
    no_socket(monkeypatch)
    with pytest.raises(tq.FeatureOff):
        GmailApiClient("token")._request("GET", "/profile")
    with pytest.raises(tq.FeatureOff):
        gmail_auth._exchange({"code": "x"})


def test_switched_on_the_same_call_reaches_the_transport(monkeypatch):
    monkeypatch.setattr(settings, "technical_queries_enabled", True)
    reached = []

    def fake(method, url, **_k):
        reached.append(url)
        return httpx.Response(
            200, json={"ok": True}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", fake)
    assert (
        GmailApiClient("token")._request("GET", "/profile") == {"ok": True}
        and len(reached) == 1
    )


# ---------------------------------------------------------------- F1: read only; sending is a later, separate consent


def test_google_is_asked_for_read_only_never_for_send(monkeypatch):
    assert gmail_auth.SCOPES == ("https://www.googleapis.com/auth/gmail.readonly",)
    monkeypatch.setenv("GMAIL_CLIENT_ID", "invented-client")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "http://127.0.0.1:8000/cb")
    on(monkeypatch)
    url = gmail_auth.start("u1")
    assert "gmail.readonly" in url and "send" not in url.replace("state=", "")


def test_sending_is_locked_in_the_route_the_worker_and_the_client(monkeypatch):
    on(monkeypatch)
    assert tq.SENDING_APPROVED is False
    no_socket(monkeypatch)
    with pytest.raises(PermissionError, match="not approved by the owner"):
        GmailApiClient("t", transport=lambda *a, **k: None).send("raw")
    from app.gmail_worker import send_approved

    scope = AccessScope("u1", frozenset(), capabilities=REVIEWER)
    with pytest.raises(PermissionError, match="not approved by the owner"):
        send_approved(
            GmailApiClient("t", transport=lambda *a, **k: None),
            "q",
            "d",
            scope,
            IDEMPOTENCY,
            "e@example.test",
        )
    item, _ = tq.import_message(envelope("lock"), "u1", False, False)
    with pytest.raises(HTTPException) as refused:
        api.prepare_query_send(
            item["id"],
            api.SendIn(mailbox_id="m", draft_id="d", idempotency_key=IDEMPOTENCY),
            scope,
        )
    assert refused.value.status_code == 409 and "not approved by the owner" in str(
        refused.value.detail
    )


# ---------------------------------------------------------------- F3: every contract the caller may read, with its coverage


def query_with_question(monkeypatch, body="Does clause 4 allow a coating change?"):
    on(monkeypatch)
    monkeypatch.setattr("app.technical_query_questions._ask", lambda text: [])
    item, _ = tq.import_message(
        {**envelope("c1"), "body": body, "question": body}, "u1", False, False
    )
    return item


def test_each_readable_contract_is_searched_on_its_own_with_dense_and_rerank_and_the_coverage_is_stored(
    monkeypatch,
):
    item = query_with_question(monkeypatch)
    for d in ("con-a", "con-b", "con-c"):
        hold_contract(d)
    hold_contract(
        "con-not-readable"
    )  # a contract the caller may not read: never searched, never counted
    calls = []

    def fake_search(question, **kw):
        calls.append(kw)
        d = kw["document_id"]
        if d == "con-c":
            raise RuntimeError("the reranker is down")
        return {
            "hits": [
                {
                    "document_id": d,
                    "page_start": 1,
                    "page_end": 1,
                    "text": "x",
                    "score": 1.0,
                }
            ]
            if d == "con-a"
            else []
        }

    monkeypatch.setattr("app.search.search", fake_search)
    result = tq.prepare_evidence(
        item["id"], frozenset({"con-a", "con-b", "con-c"}), "u1", True, False, "u1"
    )
    assert [c["document_id"] for c in calls] == ["con-a", "con-b", "con-c"]
    assert all(
        c["rerank"] is True
        and c["dense"] is True
        and c["allowed_document_ids"] == frozenset({c["document_id"]})
        for c in calls
    )
    assert result["evidence_coverage"] == {
        "searched": 2,
        "of": 3,
        "hits_in": 1,
        "failed": 1,
        "line": "Searched 2 of 3 contracts, hits in 1. 1 could not be searched.",
    }


def test_no_readable_contract_is_said_not_passed_as_no_hit(monkeypatch):
    item = query_with_question(monkeypatch)
    monkeypatch.setattr(
        "app.search.search", lambda *a, **k: pytest.fail("nothing to search")
    )
    result = tq.prepare_evidence(item["id"], frozenset(), "u1", True, False, "u1")
    assert (
        result["evidence_coverage"]["of"] == 0
        and "nothing was searched" in result["evidence_coverage"]["line"]
    )


# ---------------------------------------------------------------- F4: the questions, one by one, with their page


def attachment_query(monkeypatch, page_text):
    on(monkeypatch)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('att','q.pdf',?,1,'q.pdf','ready','x')",
            ("a" * 64,),
        )
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('att',1,?,?,0,1)",
            (page_text, len(page_text)),
        )
    item, _ = tq.import_message(
        {**envelope("att-q"), "body": "See attached.", "question": None},
        "u1",
        False,
        False,
    )
    tq.link_attachment(
        item["id"],
        item["messages"][0]["attachments"][0]["id"],
        "att",
        "u1",
        "u1",
        True,
        False,
    )
    monkeypatch.setattr("app.search.search", lambda *a, **k: {"hits": []})
    return item


def test_the_attachment_pages_are_not_copied_in_bulk_and_an_invented_question_is_dropped(
    monkeypatch,
):
    page = "Contractor query form\nRef 12\nQ1 What is the minimum coating thickness for the tank?\nQ2 Is a holiday test required?\nThanks"
    item = attachment_query(monkeypatch, page)
    monkeypatch.setattr(
        "app.technical_query_questions._ask",
        lambda text: [
            "Q1 What is the minimum coating thickness for the tank?",
            "Is the vendor insured?",
        ],  # the second is not on the page
    )
    result = tq.prepare_evidence(
        item["id"], frozenset({"att"}), "u1", True, False, "u1"
    )
    assert result["proposed_questions"] == [
        {
            "question": "Q1 What is the minimum coating thickness for the tank?",
            "filename": "query.pdf",
            "page": 1,
        }
    ]
    for stray in ("Contractor query form", "Ref 12", "Thanks", "insured", "holiday"):
        assert stray not in result["proposed_question"]
    assert (
        result["proposed_question"]
        == "See attached.\n1. Q1 What is the minimum coating thickness for the tank?"
    )
    assert (
        result["confirmed_question"] is None
    )  # the engineer confirms; nothing is decided here


def test_a_model_that_cannot_answer_proposes_nothing_and_says_so(monkeypatch):
    item = attachment_query(
        monkeypatch, "Q1 What is the minimum coating thickness for the tank?"
    )

    def down(text):
        raise RuntimeError("no model")

    monkeypatch.setattr("app.technical_query_questions._ask", down)
    result = tq.prepare_evidence(
        item["id"], frozenset({"att"}), "u1", True, False, "u1"
    )
    assert (
        result["proposed_questions"] == []
        and result["proposal_note"] == "model_unavailable"
    )
    assert result["proposed_question"] == "See attached."


# ---------------------------------------------------------------- F5: Claude for the draft is built and refused


def test_claude_for_the_draft_is_refused_unless_its_own_switch_is_on(monkeypatch):
    on(monkeypatch)
    item, _ = tq.import_message(envelope("draft"), "u1", False, False)
    scope = AccessScope("u1", frozenset(), capabilities=REVIEWER)
    seen = []
    monkeypatch.setattr(
        "app.api.technical_queries.answer.answer",
        lambda *a, **k: seen.append(k) or pytest.fail("no answer is asked"),
    )
    with pytest.raises(HTTPException) as refused:
        api.generate_query_draft(
            item["id"], scope, api.GenerateDraftIn(engine="claude")
        )
    assert (
        refused.value.status_code == 409
        and "Claude for the draft is not approved by the owner"
        in str(refused.value.detail)
    )
    assert seen == []
    # chat's per-request consent is chat's lane only
    assert "per_request_consent" not in Path(api.__file__).read_text()


def test_the_default_engine_of_the_draft_is_the_local_model_and_claude_with_its_switch_uses_the_apps_own_gated_engine(
    monkeypatch,
):
    on(monkeypatch)
    item, _ = tq.import_message(envelope("draft2"), "u1", False, False)
    scope = AccessScope("u1", frozenset(), capabilities=REVIEWER)
    models = []

    def fake_answer(*a, **k):
        models.append(k.get("model"))
        raise RuntimeError("stop here")

    monkeypatch.setattr("app.api.technical_queries.answer.answer", fake_answer)
    with (
        db.connect() as conn
    ):  # a verified, current evidence row and a confirmed question, so the call is reached
        tq.confirm_question(
            item["id"], "What applies?", "u1", True, False, "u1", reviewer=True
        )
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('d1','c.pdf',?,1,'c.pdf','ready','x')",
            ("b" * 64,),
        )
        conn.execute(
            "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,supersession_state,evidence_state,created_at) VALUES ('e1',?,'d1',1,1,'q','h','current','verified','x')",
            (item["id"],),
        )
    scope = AccessScope("u1", frozenset({"d1"}), capabilities=REVIEWER)
    with pytest.raises(HTTPException):
        api.generate_query_draft(item["id"], scope)
    monkeypatch.setattr(settings, "technical_query_claude_draft_enabled", True)
    with pytest.raises(HTTPException):
        api.generate_query_draft(
            item["id"], scope, api.GenerateDraftIn(engine="claude")
        )
    assert models == ["local", None]


# ---------------------------------------------------------------- F6: a query by hand, with its papers


def scope_of(*caps, unrestricted=False):
    return AccessScope(
        "u1", frozenset(), capabilities=frozenset(caps), unrestricted=unrestricted
    )


def make(scope, files=(), **kw):
    return asyncio.run(
        api.new_query_by_hand(
            subject=kw.get("subject", "Coating question"),
            body=kw.get("body", "Please confirm the coating."),
            contractor_name=None,
            from_address="engineer@contractor.example",
            question=None,
            files=list(files),
            scope=scope,
        )
    )


def test_a_reviewer_enters_a_query_by_hand_with_no_mailbox(monkeypatch):
    on(monkeypatch)
    out = make(scope_of(tq.REVIEWER_CAPABILITY))
    assert out["uploaded"] == 0 and out["item"]["subject"] == "Coating question"
    assert (
        tq.get(out["item"]["id"], "u1", False, True)["messages"][0]["provider"]
        == "manual"
    )


def test_nobody_else_enters_a_query_and_only_an_administrator_uploads_its_papers(
    monkeypatch,
):
    on(monkeypatch)
    with pytest.raises(HTTPException) as nobody:
        make(scope_of())
    assert nobody.value.status_code == 403
    with pytest.raises(HTTPException) as no_files:
        make(
            scope_of(tq.REVIEWER_CAPABILITY),
            [UploadFile(filename="a.pdf", file=BytesIO(b"%PDF"))],
        )
    assert no_files.value.status_code == 403


def test_each_uploaded_paper_goes_through_the_one_guarded_ingest_and_safety_check(
    monkeypatch,
):
    on(monkeypatch)
    ingested = []

    def fake_ingest(file, name):
        ingested.append((name, file.read()))
        return {"id": "doc-by-hand"}, "job-1", None

    monkeypatch.setattr("app.api.technical_queries.upload_mod.ingest", fake_ingest)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at) VALUES ('doc-by-hand','a.pdf',?,5,'a.pdf','ready','x')",
            ("c" * 64,),
        )
    out = make(
        scope_of("admin", tq.REVIEWER_CAPABILITY, unrestricted=True),
        [UploadFile(filename="a.pdf", file=BytesIO(b"%PDF-"))],
    )
    assert out["uploaded"] == 1 and ingested == [("a.pdf", b"%PDF-")]
    attachment = tq.get(out["item"]["id"], "u1", True, False)["messages"][0][
        "attachments"
    ][0]
    assert (
        attachment["document_id"] == "doc-by-hand" and attachment["scan_status"]
    )  # the safety check ran when it was linked


# ---------------------------------------------------------------- reviewer's B5: a passage the search found is a guess until a reviewer keeps it


def test_a_passage_the_search_found_blocks_approval_until_a_reviewer_keeps_it(
    monkeypatch,
):
    item = query_with_question(monkeypatch)
    with db.connect() as conn:
        hold_contract("con-a")
        conn.execute(
            "INSERT INTO pages(document_id,page_no,text,char_count,needs_ocr,batch_no) VALUES ('con-a',1,'The limit is 12 bar.',20,0,1)"
        )
    monkeypatch.setattr(
        "app.search.search",
        lambda q, **k: {
            "hits": [
                {
                    "document_id": "con-a",
                    "page_start": 1,
                    "page_end": 1,
                    "text": "The limit is 12 bar.",
                    "score": 1.0,
                }
            ]
        },
    )
    prepared = tq.prepare_evidence(
        item["id"], frozenset({"con-a"}), "u1", True, False, "u1"
    )
    evidence = prepared["evidence"][0]
    assert evidence["evidence_state"] == "proposed"
    drafted = tq.add_draft(item["id"], "Answer", [], [], "u1", "u1", True, False)
    draft_id = drafted["drafts"][-1]["id"]
    with pytest.raises(ValueError, match="not yet kept as evidence"):
        tq.decide(
            item["id"],
            "approve",
            "u1",
            None,
            draft_id,
            "u1",
            True,
            False,
            reviewer=True,
        )
    tq.update_evidence(
        item["id"],
        evidence["id"],
        "verified",
        "current",
        None,
        "u1",
        "u1",
        True,
        False,
        reviewer=True,
    )
    tq.decide(
        item["id"], "approve", "u1", None, draft_id, "u1", True, False, reviewer=True
    )
