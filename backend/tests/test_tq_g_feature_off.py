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
        and fresh.technical_query_draft_engine == "local"
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


def test_no_code_can_send_and_the_send_route_only_refuses(monkeypatch):
    """Reviewer's B2: sending is not approved and no setting lifts it, because the code that sends is gone."""
    on(monkeypatch)
    from app import gmail_client, gmail_worker

    assert not hasattr(GmailApiClient, "send") and not hasattr(gmail_worker, "send_approved")
    app_dir = Path(api.__file__).resolve().parent.parent
    for path in app_dir.rglob("*.py"):
        text = path.read_text()
        assert "messages/send" not in text, path.name  # no send request can be built
        assert "gmail.send" not in text.replace("gmail.send is not asked for", ""), path.name
    assert "send" not in gmail_client.BASE
    item, _ = tq.import_message(envelope("lock"), "u1", False, False)
    scope = AccessScope("u1", frozenset(), capabilities=REVIEWER)
    for who in (scope, AccessScope("u1", frozenset(), unrestricted=True)):
        with pytest.raises(HTTPException) as refused:
            api.prepare_query_send(item["id"], api.SendIn(draft_id="d", mailbox_id="m", idempotency_key=IDEMPOTENCY), who)
        assert refused.value.status_code == 409 and "not approved by the owner" in str(refused.value.detail)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM query_sends").fetchone()[0] == 0


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


# ---------------------------------------------------------------- F5: Claude for the draft: the owner's lane, its own consent record


def draft_ready(monkeypatch, docs=("d1", "d2")):
    """A query with a confirmed question and verified, current evidence in contract documents `docs`."""
    on(monkeypatch)
    item, _ = tq.import_message(envelope("draft-" + "-".join(docs)), "u1", False, False)
    tq.confirm_question(item["id"], "What applies?", "u1", True, False, "u1", reviewer=True)
    with db.connect() as conn:
        for n, d in enumerate(docs):
            hold_contract(d)
            conn.execute(
                "INSERT INTO query_evidence(id,query_id,document_id,page_start,page_end,exact_quote,quote_hash,supersession_state,evidence_state,created_at) VALUES (?,?,?,1,1,'q',?,'current','verified','x')",
                (f"e{n}", item["id"], d, f"h{n}"),
            )
    return item, AccessScope("u1", frozenset(docs), capabilities=REVIEWER)


def test_claude_for_the_draft_is_refused_while_the_engine_setting_is_local_and_for_any_other_vendor(monkeypatch):
    item, scope = draft_ready(monkeypatch)
    monkeypatch.setattr("app.api.technical_queries.answer.answer", lambda *a, **k: pytest.fail("no answer is asked"))
    assert settings.technical_query_draft_engine == "local"
    with pytest.raises(HTTPException) as local_only:
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="claude", document_ids=["d1"]))
    assert local_only.value.status_code == 409 and "not enabled on this server" in str(local_only.value.detail)
    with pytest.raises(HTTPException) as other:
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="some-other-vendor"))
    assert "not approved by the owner" in str(other.value.detail)
    assert "per_request_consent" not in Path(api.__file__).read_text()  # chat's lane is chat's only


def test_the_default_draft_runs_on_the_local_model(monkeypatch):
    item, scope = draft_ready(monkeypatch)
    seen = []

    def fake(*a, **k):
        seen.append((k["model"], k["allowed_document_ids"]))
        raise RuntimeError("stop here")

    monkeypatch.setattr("app.api.technical_queries.answer.answer", fake)
    with pytest.raises(HTTPException):
        api.generate_query_draft(item["id"], scope)
    assert seen == [("local", frozenset({"d1", "d2"}))]


def test_a_claude_draft_needs_the_chosen_documents_records_the_choice_first_and_sends_only_those(monkeypatch):
    item, scope = draft_ready(monkeypatch)
    monkeypatch.setattr(settings, "technical_query_draft_engine", "claude")
    seen = []

    def fake(*a, **k):
        from app import claude_approved

        seen.append((k["model"], k["allowed_document_ids"], claude_approved._consented(frozenset({"d1", "d2"}))))
        with db.connect() as conn:  # the consent record already exists when the call is made
            from app import technical_query_claude as C

            assert [e["document_ids"] for e in C.entries(conn, item["id"])] == [["d1"]]
        raise RuntimeError("stop here")

    monkeypatch.setattr("app.api.technical_queries.answer.answer", fake)
    with pytest.raises(HTTPException) as nothing_chosen:
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="claude"))
    assert "choose the contract documents" in str(nothing_chosen.value.detail) and seen == []
    with pytest.raises(HTTPException) as not_evidence:
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="claude", document_ids=["elsewhere"]))
    assert "not verified, current evidence" in str(not_evidence.value.detail) and seen == []
    with pytest.raises(HTTPException):  # the fake stops it after the checks
        api.generate_query_draft(item["id"], scope, api.GenerateDraftIn(engine="claude", document_ids=["d1"]))
    # only the chosen document is passed to the answer lane and only it is consented; the other one is not
    assert seen == [("technical_query_draft", frozenset({"d1"}), frozenset({"d1"}))]


def test_the_gate_lets_the_chosen_contract_go_but_the_client_register_block_and_other_documents_still_stop_it(monkeypatch):
    from app import claude_approved as CA

    on(monkeypatch)
    hold_contract("chosen")
    hold_contract("other")
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    with CA.carrying(["chosen"]):
        assert CA.refusal() is not None  # a contract without a yes is refused outside the lane
    with CA.technical_query_lane(["chosen"]), CA.carrying(["chosen"]):
        assert CA.refusal() is None
    with CA.technical_query_lane(["chosen"]), CA.carrying(["chosen", "other"]):
        assert CA.refusal() is not None  # a document the engineer did not choose is still refused
    monkeypatch.setattr(CA, "_block_stop", lambda ids: (CA.NOT_APPROVED, "blocked"))
    with CA.technical_query_lane(["chosen"]), CA.carrying(["chosen"]):
        assert CA.refusal() == (CA.NOT_APPROVED, "blocked")  # the register block wins over the choice


def test_the_draft_provider_is_claude_only_when_its_own_engine_setting_and_the_lane_say_so(monkeypatch):
    from app import chat_model
    from app import reasoning_provider as rp

    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "technical_query_draft_engine", "local")
    assert isinstance(chat_model.provider(chat_model.TQ_DRAFT), rp.OllamaProvider)
    monkeypatch.setattr(rp, "_lane_unavailable", lambda: (None, "claude"))
    monkeypatch.setattr(settings, "technical_query_draft_engine", "claude")
    assert isinstance(chat_model.provider(chat_model.TQ_DRAFT), rp.ClaudeProvider)
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert isinstance(chat_model.provider(chat_model.TQ_DRAFT), rp.OllamaProvider)  # the master switch still keeps everything local


# ---------------------------------------------------------------- F6: a query by hand, with its papers


def scope_of(*caps, unrestricted=False):
    return AccessScope(
        "u1", frozenset(), capabilities=frozenset(caps), unrestricted=unrestricted
    )


def pdf_bytes(active: bool = False) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    if active:
        doc.xref_set_key(doc.pdf_catalog(), "OpenAction", "<</S/JavaScript/JS(app.alert(1))>>")
    data = doc.tobytes()
    doc.close()
    return data


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
    PDF = pdf_bytes()

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
        [UploadFile(filename="a.pdf", file=BytesIO(PDF))],
    )
    assert out["uploaded"] == 1 and ingested == [("a.pdf", PDF)]
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
    drafted = tq.add_draft(
        item["id"], "Answer", [], [], "u1", "u1", True, False, citations=[{"evidence_id": evidence["id"], "label": "S1"}]
    )
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


# ---------------------------------------------------------------- reviewer's M9: the safety check runs BEFORE a paper enters the library


def test_a_paper_with_active_content_is_never_ingested(monkeypatch):
    on(monkeypatch)
    monkeypatch.setattr("app.api.technical_queries.upload_mod.ingest", lambda *a: pytest.fail("a flagged file must not be ingested"))
    scope = scope_of("admin", tq.REVIEWER_CAPABILITY, unrestricted=True)
    with pytest.raises(HTTPException) as refused:
        make(scope, [UploadFile(filename="bad.pdf", file=BytesIO(pdf_bytes(active=True)))])
    assert refused.value.status_code == 422 and "active content" in str(refused.value.detail)
    with db.connect() as conn:
        row = conn.execute("SELECT scan_status,scan_detail,document_id FROM query_attachments").fetchone()
    assert row["scan_status"] == "static_check_flagged" and row["document_id"] is None and "/JavaScript" in row["scan_detail"]


def test_a_mailbox_attachment_with_active_content_is_marked_and_not_ingested(monkeypatch):
    on(monkeypatch)
    from app import gmail_worker
    from app.gmail_client import GmailMessage

    bad = pdf_bytes(active=True)
    message = GmailMessage(
        provider_message_id="m1", thread_id="t1", from_address="a@b.example", to_addresses=[], cc_addresses=[], subject="s", body="b",
        received_at="2026-01-01T00:00:00Z",
        attachments=[{"filename": "bad.pdf", "media_type": "application/pdf", "size_bytes": len(bad), "attachment_id": "a1"}],
        label_ids=("L",),
    )

    class Client:
        def message(self, _id):
            return message

        def raw_message(self, _id):
            return b"From: a@b.example\n\nbody"

        def attachment(self, *_a):
            return bad

    monkeypatch.setattr("app.gmail_worker.upload_mod.ingest", lambda *a: pytest.fail("a flagged file must not be ingested"))
    out = gmail_worker.process_history(Client(), "h", "u1", mailbox_id="mb", message_ids=["m1"], label_id="L")
    assert len(out) == 1
    with db.connect() as conn:
        row = conn.execute("SELECT scan_status,document_id FROM query_attachments").fetchone()
    assert row["scan_status"] == "static_check_flagged" and row["document_id"] is None


# ---------------------------------------------------------------- reviewer's M3: one bad message must not block a mailbox for ever


def test_a_message_that_keeps_failing_is_tried_three_times_then_marked_and_stepped_over(monkeypatch):
    on(monkeypatch)
    from app import gmail_worker

    calls = []

    def boom(client, message_id, **kw):
        calls.append(message_id)
        if message_id == "bad":
            raise ValueError("size mismatch")
        return {"query_id": "q", "duplicate": False}

    monkeypatch.setattr(gmail_worker, "_process_message", boom)

    class Client:
        pass

    for _ in range(2):  # the first two polls fail and are retried from the same cursor
        with pytest.raises(ValueError):
            gmail_worker.process_history(Client(), "h", "u1", mailbox_id="mb", message_ids=["bad", "good"])
    out = gmail_worker.process_history(Client(), "h", "u1", mailbox_id="mb", message_ids=["bad", "good"])
    assert out == [{"query_id": "q", "duplicate": False}]  # the third time the bad one is stepped over, the good one imported
    with db.connect() as conn:
        row = conn.execute("SELECT tries,state,reason FROM gmail_failed_messages WHERE provider_message_id='bad'").fetchone()
    assert (row["tries"], row["state"]) == (3, "failed") and "ValueError" in row["reason"] and "size mismatch" not in row["reason"]


def test_a_draft_that_cites_no_verified_current_evidence_cannot_be_approved(monkeypatch):
    item = query_with_question(monkeypatch)
    bare = tq.add_draft(item["id"], "Answer", [], [], "u1", "u1", True, False)
    with pytest.raises(ValueError, match="cites no verified, current evidence"):
        tq.decide(item["id"], "approve", "u1", None, bare["drafts"][-1]["id"], "u1", True, False, reviewer=True)
    other, _ = tq.import_message(envelope("c2"), "u1", False, False)
    with pytest.raises(ValueError, match="cites no verified, current evidence"):  # a citation that resolves to nothing is no citation
        made = tq.add_draft(other["id"], "Answer 2", [], [], "u1", "u1", True, False, citations=[{"evidence_id": "nothing"}])
        tq.decide(other["id"], "approve", "u1", None, made["drafts"][-1]["id"], "u1", True, False, reviewer=True)


# ---------------------------------------------------------------- reviewer's M4, M5, M1/M2, M8


def test_the_access_log_stays_on_except_for_the_one_gmail_return_line():
    import importlib.util
    import logging

    spec = importlib.util.spec_from_file_location("run_under_test", Path(__file__).resolve().parents[1] / "run.py")
    run = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run)
    assert "access_log=False" not in Path(run.__file__).read_text()
    logger = logging.getLogger("uvicorn.access")
    before = list(logger.filters)
    run._keep_oauth_code_out_of_the_access_log()
    added = [f for f in logger.filters if f not in before]
    try:
        keep = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "GET /api/documents HTTP/1.1", None, None)
        drop = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "GET /api/technical-queries/providers/gmail/oauth/callback?code=x HTTP/1.1", None, None)
        assert all(f.filter(keep) for f in added) and not any(f.filter(drop) for f in added)
    finally:
        for f in added:
            logger.removeFilter(f)


def test_the_gmail_return_needs_the_person_who_started_the_connection_and_then_redirects(monkeypatch):
    on(monkeypatch)
    monkeypatch.setenv("GMAIL_CLIENT_ID", "invented-client")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "http://127.0.0.1:8000/cb")
    state = gmail_auth.start("u1").split("state=")[1].split("&")[0]
    completed = []
    monkeypatch.setattr("app.api.technical_queries.gmail_auth.complete", lambda code, st: completed.append((code, st)) or {})
    monkeypatch.setattr("app.api.technical_queries.gmail_sync.start", lambda: None)
    other = AccessScope("someone-else", frozenset(), capabilities=frozenset({"admin"}))
    with pytest.raises(HTTPException) as refused:
        api.gmail_oauth_callback("code", state, other)
    assert refused.value.status_code == 403 and completed == []
    owner = AccessScope("u1", frozenset(), capabilities=frozenset({"admin"}))
    response = api.gmail_oauth_callback("code", state, owner)
    assert response.status_code == 303 and response.headers["location"] == "/technicalQueries" and completed == [("code", state)]


def test_attachment_text_original_email_and_word_file_need_the_grant_on_the_attachment(monkeypatch):
    item = attachment_query(monkeypatch, "Q1 What is the minimum coating thickness for the tank?")
    monkeypatch.setattr("app.technical_query_questions._ask", lambda text: ["Q1 What is the minimum coating thickness for the tank?"])
    tq.prepare_evidence(item["id"], frozenset({"att"}), "u1", True, False, "u1")
    full = tq.get(item["id"], "u1", True, False)
    assert full["attachment_context"] and full["proposed_questions"]
    reader = AccessScope("u1", frozenset({"att"}), capabilities=REVIEWER)
    blind = AccessScope("u1", frozenset(), capabilities=REVIEWER)
    assert api._safe_item(full, reader)["attachment_context"] == full["attachment_context"]
    hidden = api._safe_item(full, blind)
    assert hidden["attachment_context"] == [] and hidden["proposed_questions"] == [] and hidden["proposed_question"] is None
    assert hidden["attachment_text_hidden"] is True
    message = full["messages"][0]
    with db.connect() as conn:
        conn.execute("UPDATE query_messages SET raw_storage_ref=? WHERE id=?", ("/nowhere.eml", message["id"]))
    with pytest.raises(HTTPException) as no_email:
        api.download_original_query_email(item["id"], message["id"], blind)
    assert no_email.value.status_code == 403
    with pytest.raises(HTTPException) as no_word:
        api.query_response_docx(item["id"], blind)
    assert no_word.value.status_code == 403


def test_a_draft_word_file_says_ai_to_be_checked_until_a_reviewer_approves(monkeypatch, tmp_path):
    from zipfile import ZipFile

    from app.technical_query_docx import render

    item = query_with_question(monkeypatch)
    drafted = tq.add_draft(item["id"], "Draft answer", [], [], "u1", "u1", True, False)
    path = render(tq.get(item["id"], "u1", True, False), tmp_path / "d.docx")
    assert "AI, to be checked" in ZipFile(path).read("word/document.xml").decode()
    assert drafted["drafts"]
