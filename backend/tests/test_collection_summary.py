"""The chat collection path must account for every selected document."""

import logging
import re

import pytest

from app import analysis, chat, db, intent, synthesis
from app.config import settings
from app.schemas import AnswerResult


@pytest.fixture(autouse=True)
def private_database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "summary.sqlite")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def put_document(doc_id: str, text: list[str], *, status: str = "ready") -> None:
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, sha256, size_bytes, stored_path, uploaded_at,
                status, chunk_count_total)
               VALUES (?, ?, ?, 1, ?, '2026-10-16T00:00:00Z', ?, ?)""",
            (doc_id, f"{doc_id}.pdf", doc_id, f"{doc_id}.pdf", status, len(text)),
        )
        for i, passage in enumerate(text):
            conn.execute(
                """INSERT INTO chunks
                   (id, document_id, filename, ordinal, page_start, page_end,
                    text, token_count, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 10, ?)""",
                (f"{doc_id}-{i}", doc_id, f"{doc_id}.pdf", i,
                 i + 1, i + 1, passage, f"hash-{doc_id}-{i}"),
            )


class Reader:
    def __init__(self, final: str | None = None):
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.final = final

    def __call__(self, system: str, prompt: str) -> synthesis.Generation:
        self.prompts.append(prompt)
        self.systems.append(system)
        if (system.startswith("You write an overview")
                or system.startswith("Write the requested overview")) and self.final is not None:
            return synthesis.Generation(self.final, truncated=False)
        markers = re.findall(r"(\[S\d+\]) \(", prompt)
        return synthesis.Generation(
            "Inspection is scheduled " + " ".join(markers) + ".", truncated=False)


def test_ten_document_request_reads_every_selected_document_and_cites_original_pages():
    for n in range(10):
        put_document(f"d{n}", ["Inspection is scheduled.",
                                "Inspection is scheduled for the next visit."])
    reader = Reader()
    ids = frozenset(f"d{n}" for n in range(10))
    result = analysis.collection_summary(
        "Summarize these ten documents in one page", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer_type"] == "generated", result["reason"]
    assert result["summary_coverage"]["requested"] == 10
    assert result["summary_coverage"]["processed"] == 10
    assert result["summary_coverage"]["cited_documents"] == 10
    assert result["summary_coverage"]["target_words"] == 450
    assert result["summary_coverage"]["actual_words"] == len(result["answer"].split())
    assert "shorter than the requested" in result["notices"][0]
    assert all(d["chunks_used"] == 2 for d in result["summary_coverage"]["documents"])
    assert result["passages"]
    assert all(p["document_id"] in ids and p["page_start"] >= 1 for p in result["passages"])
    assert "[S1]" in result["answer"]
    AnswerResult.model_validate(result)
    assert len(reader.prompts) >= 11  # per-document work, then cross-document reduction


def test_claude_choice_uses_existing_provider_for_approved_collection(monkeypatch):
    from app import chat_model, claude_approved, reasoning_provider

    ids = frozenset({"one", "two"})
    for doc_id in ids:
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    reader = Reader()
    reader_model = "claude-sonnet-test"
    observed_scopes = []
    provider = reasoning_provider.ClaudeProvider(reader_model, step=chat_model.CHAT_STEP)
    monkeypatch.setattr(chat_model, "provider", lambda preference=None: provider)
    monkeypatch.setattr(claude_approved, "local_instead", lambda: None)

    def fake_claude(system, prompt, *, target_words):
        observed_scopes.append(claude_approved.carried())
        generated = reader(system, prompt)
        return synthesis.Generation(generated.text, generated.truncated, reader_model)

    monkeypatch.setattr(analysis, "collection_claude_generate", fake_claude)
    result = analysis.collection_summary(
        "Summarize these two documents in one page", ids,
        allowed_document_ids=ids, model="claude",
        explicit_document_selection=True)

    assert result["answer_type"] == "generated", result["reason"]
    assert result["provider"] == "claude"
    assert result["model"] == reader_model
    assert observed_scopes and all(scope == ids for scope in observed_scopes)


def test_explicit_claude_selection_sends_only_selected_documents(monkeypatch):
    from app import chat_model, claude_approved, reasoning_provider

    ids = frozenset({"one", "two"})
    other = "older-conversation-document"
    for doc_id in ids:
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    put_document(other, ["Unselected historical content."])
    reader = Reader()
    provider = reasoning_provider.ClaudeProvider(
        "claude-sonnet-test", step=chat_model.CHAT_STEP)
    monkeypatch.setattr(chat_model, "provider", lambda preference=None: provider)
    observed_scopes = []

    def fake_claude(system, prompt, *, target_words):
        observed_scopes.append(claude_approved.carried())
        assert "Unselected historical content." not in prompt
        generated = reader(system, prompt)
        return synthesis.Generation(generated.text, False, "claude-sonnet-test")

    monkeypatch.setattr(analysis, "collection_claude_generate", fake_claude)

    with claude_approved.carrying({other}):
        result = analysis.collection_summary(
            "Summarize these two documents", ids,
            allowed_document_ids=ids | {other}, model="claude",
            explicit_document_selection=True)

    assert result["answer_type"] == "generated", result["reason"]
    assert result["provider"] == "claude"
    assert observed_scopes and set(observed_scopes) == {ids}
    assert claude_approved.carried() is None


def test_claude_without_explicit_document_selection_stays_local(monkeypatch):
    from app import chat_model

    ids = frozenset({"one", "two"})
    for doc_id in ids:
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    reader = Reader()
    monkeypatch.setattr(analysis, "collection_generate", lambda system, prompt, *, target_words:
                        synthesis.Generation(reader(system, prompt).text, False, "local-test"))
    monkeypatch.setattr(analysis, "collection_claude_generate",
                        lambda *args, **kwargs: pytest.fail("implicit document scope reached Claude"))
    monkeypatch.setattr(chat_model, "provider", lambda *args, **kwargs:
                        pytest.fail("Claude provider should not be selected without consent"))

    result = analysis.collection_summary(
        "Summarize these two documents", ids,
        allowed_document_ids=ids, model="claude",
        explicit_document_selection=False)

    assert result["answer_type"] == "generated", result["reason"]
    assert result["provider"] == "ollama"
    assert "Choose one or more documents" in result["provider_note"]


def test_claude_summary_adapter_uses_metered_chat_provider_and_output_budget(monkeypatch):
    from app import chat_model, reasoning_provider

    provider = reasoning_provider.ClaudeProvider(
        "claude-sonnet-test", step=chat_model.CHAT_STEP)
    seen = {}

    def fake_reason(packet):
        seen["packet"] = packet
        return reasoning_provider.Response(
            text="A supported summary [S1].", provider="claude",
            model_tag="claude-sonnet-test", digest="response-hash",
            finish_reason="end_turn", prompt_sha256=packet.sha256)

    monkeypatch.setattr(provider, "reason", fake_reason)
    monkeypatch.setattr(
        chat_model, "provider", lambda preference=None: provider)

    generated = analysis.collection_claude_generate(
        "You write an overview using the sources", "[S1] (source)", target_words=450)

    assert generated.text == "A supported summary [S1]."
    assert generated.model == "claude-sonnet-test"
    assert not generated.truncated
    assert seen["packet"].step == chat_model.CHAT_STEP
    assert seen["packet"].num_predict == 1280
    assert seen["packet"].prompt_version == "collection-summary-v1"


def test_twenty_selected_documents_use_the_same_chat_summary_engine():
    ids = frozenset(f"d{n}" for n in range(20))
    for doc_id in ids:
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    reader = Reader()
    result = analysis.collection_summary(
        "Summarize these 20 documents in two pages", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer_type"] == "generated", result["reason"]
    assert result["summary_coverage"]["cited_documents"] == 20
    assert any("about 900 words" in system for system in reader.systems)
    assert "[S20]" in reader.prompts[-1], "the final call should see every document note"


def test_same_filename_uploads_remain_distinct_documents():
    ids = frozenset({"first", "second"})
    for doc_id in ids:
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET filename = 'report.pdf' WHERE id IN ('first', 'second')")
        conn.execute("UPDATE chunks SET filename = 'report.pdf' WHERE document_id IN ('first', 'second')")
    result = analysis.collection_summary(
        "Summarize these two documents", ids,
        allowed_document_ids=ids, generate=Reader())
    assert result["answer_type"] == "generated", result["reason"]
    assert result["summary_coverage"]["cited_documents"] == 2


@pytest.mark.parametrize("question_text, expected", [
    ("Summarize these documents in 200 words", 200),
    ("Summarize these documents in one page", 450),
    ("Give a brief overview of these files", 150),
    ("Give a detailed overview of these files", 700),
])
def test_requested_length_changes_the_writing_target(question_text, expected):
    assert analysis.requested_summary_words(question_text) == expected


def test_final_and_final_retry_use_a_summary_sized_output_budget(monkeypatch):
    bodies = []
    monkeypatch.setattr(analysis.model_transport, "post_json",
                        lambda path, body, timeout: bodies.append(body) or
                        {"response": "OK", "done": True})
    analysis.collection_generate(synthesis.COLLECTION_FINAL_SYSTEM_PROMPT, "prompt",
                                 target_words=450)
    analysis.collection_generate(synthesis.COLLECTION_FINAL_RETRY_SYSTEM_PROMPT,
                                 "prompt", target_words=450)
    analysis.collection_generate(synthesis.COLLECTION_INTERMEDIATE_SYSTEM_PROMPT,
                                 "prompt", target_words=450)
    analysis.collection_generate(synthesis.COLLECTION_RETRY_SYSTEM_PROMPT,
                                 "prompt", target_words=450)
    assert bodies[0]["options"]["num_predict"] == 1280
    assert bodies[1]["options"]["num_predict"] == 1280
    assert bodies[2]["options"]["num_predict"] == 220
    assert bodies[3]["options"]["num_predict"] == 384


def test_known_unread_page_refuses_before_generation():
    put_document("one", ["Inspection is scheduled."])
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET page_count = 2 WHERE id = 'one'")
        conn.execute("""INSERT INTO page_ledger
                        (document_id, page_no, native_status, ocr_status, index_status, updated_at)
                        VALUES ('one', 1, 'text', 'not_required', 'retrievable', '2026-10-16'),
                               ('one', 2, 'needs_ocr', 'failed', 'no_chunk', '2026-10-16')""")
    reader = Reader()
    result = analysis.collection_summary(
        "Summarize this document", frozenset({"one"}),
        allowed_document_ids=frozenset({"one"}), generate=reader)
    assert result["answer"] is None
    assert result["summary_coverage"]["documents"][0]["pages_unread"] == [2]
    assert reader.prompts == []


def test_intentionally_excluded_page_is_reported_but_not_called_unread():
    for doc_id in ("one", "two"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET page_count = 3 WHERE id = 'one'")
        for page, status in ((1, "retrievable"), (2, "retrievable"), (3, "excluded")):
            conn.execute(
                """INSERT INTO page_ledger
                   (document_id, page_no, native_status, ocr_status, index_status, updated_at)
                   VALUES ('one', ?, 'text', 'not_required', ?, '2026-10-16')""",
                (page, status))
    ids = frozenset({"one", "two"})
    result = analysis.collection_summary(
        "Summarize these two documents", ids,
        allowed_document_ids=ids, generate=Reader())
    assert result["answer_type"] == "generated", result["reason"]
    assert result["summary_coverage"]["documents"][0]["pages_excluded"] == [3]
    assert "1 intentionally excluded page" in result["notices"][0]


def test_local_work_limit_is_reported_not_presented_as_a_complete_summary(monkeypatch):
    for doc_id in ("one", "two"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    monkeypatch.setattr(synthesis, "COLLECTION_MAX_CALLS", 1)
    ids = frozenset({"one", "two"})
    result = analysis.collection_summary(
        "Summarize these two documents", ids,
        allowed_document_ids=ids, generate=Reader())
    assert result["answer"] is None
    assert "work limit" in result["reason"]
    assert result["summary_coverage"]["processed"] == 0


def test_unsupported_requested_length_is_named_before_generation():
    put_document("one", ["Inspection is scheduled."])
    reader = Reader()
    result = analysis.collection_summary(
        "Summarize this document in 1500 words", frozenset({"one"}),
        allowed_document_ids=frozenset({"one"}), generate=reader)
    assert result["answer"] is None
    assert "900 words" in result["reason"]
    assert reader.prompts == []


def test_partial_final_citation_is_not_presented_as_complete():
    for doc_id in ("first", "second"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    ids = frozenset({"first", "second"})
    result = analysis.collection_summary(
        "Summarize these documents", ids, allowed_document_ids=ids,
        generate=Reader("Inspection is scheduled [S1]."))
    assert result["answer"] is None
    assert "omitted citations" in result["reason"]


def test_original_page_gate_keeps_supported_sentences_and_drops_unsupported_claims():
    ledger = {
        "one": {"evidence_id": "one", "document_id": "d1", "filename": "one.pdf",
                "page_start": 1, "page_end": 1, "text": "Inspection is scheduled."},
        "two": {"evidence_id": "two", "document_id": "d2", "filename": "two.pdf",
                "page_start": 1, "page_end": 1, "text": "Valve is tagged."},
    }
    draft = synthesis.Summary(
        text="Inspection is scheduled. Valve is compliant.", truncated=False,
        positional_evidence_ids=("one", "two"), cited_evidence_ids=("one", "two"),
        findings=(
            synthesis.CitedSentence("Inspection is scheduled [S1].", ("one",), "extracted"),
            synthesis.CitedSentence("Valve is compliant [S2].", ("two",), "extracted"),
        ),
    )
    checked, originals = synthesis.original_citations(draft, ledger)
    assert checked.refusal is None
    assert checked.text == "Inspection is scheduled [S1]."
    assert len(checked.dropped_sentences) == 1
    assert {item["document_id"] for item in originals} == {"d1", "d2"}


def test_synthesis_logs_neither_client_filename_nor_completion(caplog):
    with caplog.at_level(logging.DEBUG, logger="nabaa.synthesis"):
        synthesis._Call(stage="collection_map", document="private-client.pdf",
                        raw_completion="secret-document-prose").record()
    assert "private-client.pdf" not in caplog.text
    assert "secret-document-prose" not in caplog.text


def test_scope_is_checked_before_any_document_text_reaches_the_model():
    put_document("allowed", ["Inspection is scheduled.", "Inspection is scheduled."])
    put_document("secret", ["TOP_SECRET_SENTINEL", "TOP_SECRET_SENTINEL"])
    reader = Reader()
    result = analysis.collection_summary(
        "Summarize these documents", frozenset({"allowed", "secret"}),
        allowed_document_ids=frozenset({"allowed"}), generate=reader)
    assert result["answer"] is None
    assert result["summary_coverage"]["processed"] == 0
    assert reader.prompts == []


def test_named_document_count_does_not_silently_expand_to_entire_library():
    for doc_id in ("one", "two", "three"):
        put_document(doc_id, ["Inspection is scheduled."])
    reader = Reader()
    ids = frozenset({"one", "two", "three"})
    result = analysis.collection_summary(
        "Summarize these two documents in one page", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer"] is None
    assert "2 documents" in result["reason"]
    assert reader.prompts == []


def test_unfinished_document_prevents_a_complete_looking_summary():
    put_document("ready", ["Inspection is scheduled.", "Inspection is scheduled."])
    put_document("waiting", [], status="extracting")
    reader = Reader()
    ids = frozenset({"ready", "waiting"})
    result = analysis.collection_summary(
        "Summarize these documents", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer_type"] == "insufficient_evidence"
    assert result["answer"] is None
    assert "Ready" in result["reason"]
    assert reader.prompts == []


def test_unsupported_final_number_is_refused():
    for doc_id in ("first", "second"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    reader = Reader("Inspection is scheduled at 999 bar [S1].")
    ids = frozenset({"first", "second"})
    result = analysis.collection_summary(
        "Summarize these documents", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer"] is None
    assert result["answer_type"] == "insufficient_evidence"
    assert reader.prompts


def test_collection_intent_is_explicit_and_does_not_capture_ordinary_questions():
    assert intent.is_collection_summary("Summarize these ten documents in one page")
    assert intent.is_collection_summary("Give me an overview of the selected PDFs")
    assert intent.is_collection_summary("read all document and summariee them")
    assert intent.is_collection_summary("summarize them in one page", selected_document_count=10)
    assert intent.is_collection_summary("make a short summary", selected_document_count=10)
    assert not intent.is_collection_summary(
        "what does the summary section say?", selected_document_count=10)
    assert not intent.is_collection_summary("Summarize this document")
    assert not intent.is_collection_summary("Summarize this file")
    assert not intent.is_collection_summary("What is the pressure limit in API 610?")
    assert not intent.is_collection_summary("What does the summary section say?")


@pytest.mark.parametrize("first_draft", [
    "INSUFFICIENT EVIDENCE",
    "The schedule is ready.",
])
def test_rejected_model_draft_gets_one_citation_checked_retry(first_draft):
    for doc_id in ("one", "two"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    ids = frozenset({"one", "two"})

    class RetryReader(Reader):
        def __init__(self):
            super().__init__()
            self.intermediate_calls = 0

        def __call__(self, system: str, prompt: str) -> synthesis.Generation:
            self.prompts.append(prompt)
            self.systems.append(system)
            if system == synthesis.COLLECTION_INTERMEDIATE_SYSTEM_PROMPT:
                self.intermediate_calls += 1
                if self.intermediate_calls == 1:
                    return synthesis.Generation(first_draft, truncated=False)
            markers = re.findall(r"(\[S\d+\]) \(", prompt)
            return synthesis.Generation(
                "Inspection is scheduled " + " ".join(markers) + ".", truncated=False)

    reader = RetryReader()
    result = analysis.collection_summary(
        "Summarize these two documents in one page", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer_type"] == "generated", result["reason"]
    assert synthesis.COLLECTION_RETRY_SYSTEM_PROMPT in reader.systems
    assert result["summary_coverage"]["cited_documents"] == 2


def test_truncated_intermediate_draft_gets_a_bounded_citation_checked_retry():
    for doc_id in ("one", "two"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    ids = frozenset({"one", "two"})

    class TruncateFirstMap(Reader):
        def __init__(self):
            super().__init__()
            self.did_truncate = False

        def __call__(self, system: str, prompt: str) -> synthesis.Generation:
            if system == synthesis.COLLECTION_INTERMEDIATE_SYSTEM_PROMPT and not self.did_truncate:
                self.did_truncate = True
                self.prompts.append(prompt)
                self.systems.append(system)
                return synthesis.Generation("Inspection is scheduled", truncated=True)
            return super().__call__(system, prompt)

    reader = TruncateFirstMap()
    result = analysis.collection_summary(
        "Summarize these two documents in one page", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer_type"] == "generated", result["reason"]
    assert synthesis.COLLECTION_RETRY_SYSTEM_PROMPT in reader.systems
    assert result["summary_coverage"]["processed"] == 2
    assert result["summary_coverage"]["cited_documents"] == 2


def test_truncated_final_draft_gets_a_coverage_checked_retry():
    for doc_id in ("one", "two"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    ids = frozenset({"one", "two"})

    class TruncateFirstFinal(Reader):
        def __init__(self):
            super().__init__()
            self.did_truncate = False

        def __call__(self, system: str, prompt: str) -> synthesis.Generation:
            if system.startswith("You write an overview") and not self.did_truncate:
                self.did_truncate = True
                self.prompts.append(prompt)
                self.systems.append(system)
                return synthesis.Generation("Inspection is scheduled", truncated=True)
            return super().__call__(system, prompt)

    reader = TruncateFirstFinal()
    result = analysis.collection_summary(
        "Summarize these two documents in one page", ids,
        allowed_document_ids=ids, generate=reader)
    assert result["answer_type"] == "generated", result["reason"]
    assert any(system.startswith("Write the requested overview") for system in reader.systems)
    assert result["summary_coverage"]["cited_documents"] == 2


def test_existing_chat_routes_collection_request_through_its_selected_scope(monkeypatch):
    put_document("one", ["Inspection is scheduled.", "Inspection is scheduled."])
    convo = chat.create_conversation()
    seen = {}

    def fake_summary(question, ids, *, allowed_document_ids, model=None,
                     explicit_document_selection=False):
        seen["ids"] = ids
        seen["allowed"] = allowed_document_ids
        seen["model"] = model
        seen["explicit_document_selection"] = explicit_document_selection
        return {"question": question, "answer_type": "insufficient_evidence",
                "answer": None, "reason": "test refusal", "passages": [], "cited": [],
                "summary_coverage": {"requested": 1, "processed": 0,
                                     "cited_documents": 0, "documents": []},
                "retrieval_mode": "collection", "reranked": False,
                "candidates_considered": 0, "seconds": 0.0, "timings": {}}

    monkeypatch.setattr(analysis, "collection_summary", fake_summary)
    result = chat.ask(convo["id"], "summarize them in one page",
                      allowed_document_ids=frozenset({"one"}),
                      document_ids=frozenset({"one"}), model="claude")
    assert seen["ids"] == frozenset({"one"})
    assert seen["model"] == "claude"
    assert seen["explicit_document_selection"] is True
    assert result["answer_type"] == "insufficient_evidence"
    assert result["used_line"].startswith("Collection summary incomplete")


def test_claude_chat_consent_is_per_request_and_filters_old_document_history(monkeypatch):
    from app import chat_claude_first, claude_approved

    put_document("selected", ["Selected source text."])
    put_document("older", ["Older private source text."])
    seen = []

    def route(question, **_kwargs):
        return {"kind": intent.DOCUMENT, "text": question, "styles": [],
                "small_talk": None, "compliance": False}

    def answer(question, *, history, allowed_document_ids, preference, **_kwargs):
        seen.append({"history": history, "allowed": allowed_document_ids,
                     "carried": claude_approved.carried(), "preference": preference})
        if preference == "local":
            return None
        return {"question": question, "answer_type": "general", "answer": "A chat answer.",
                "reason": None, "passages": [], "cited": [], "provider": "claude",
                "model": "claude-test", "seconds": 0.0, "retrieval_mode": "claude_tools",
                "reranked": False, "candidates_considered": 0, "timings": {},
                "steps": [], "claims": [], "notices": []}

    monkeypatch.setattr(intent, "route", route)
    monkeypatch.setattr(chat_claude_first, "answer", answer)
    local_calls = []

    def local_document_answer(_conversation_id, resolved, _understood, **kwargs):
        local_calls.append(kwargs)
        return ({"question": resolved, "answer_type": "general", "answer": "Local answer.",
                 "reason": None, "passages": [], "cited": [], "provider": "ollama",
                 "seconds": 0.0, "retrieval_mode": "keyword", "reranked": False,
                 "candidates_considered": 0, "timings": {}, "notices": []}, resolved)

    monkeypatch.setattr(chat, "_document_answer", local_document_answer)

    def add_old_turn(conversation_id):
        conn = db.connect()
        chat._insert_message(conn, conversation_id, role="user", text="Earlier question",
                             carried_terms=[])
        chat._insert_message(conn, conversation_id, role="assistant",
                             text="Older private source text.", answer_type="generated",
                             payload={"document_ids": ["older"]})

    selected_conversation = chat.create_conversation()
    add_old_turn(selected_conversation["id"])
    selected_result = chat.ask(
        selected_conversation["id"], "What does the selected file say?",
        allowed_document_ids=frozenset({"selected", "older"}),
        document_ids=frozenset({"selected"}), model="claude")

    assert seen[-1]["allowed"] == frozenset({"selected"})
    assert seen[-1]["carried"] == frozenset({"selected"})
    assert "Older private source text." not in seen[-1]["history"]
    assert selected_result["provider"] == "claude"

    no_selection_conversation = chat.create_conversation()
    add_old_turn(no_selection_conversation["id"])
    chat.ask(no_selection_conversation["id"], "What does the file say?",
             allowed_document_ids=frozenset({"selected", "older"}), model="claude")
    assert seen[-1]["allowed"] == frozenset()
    assert seen[-1]["carried"] == frozenset()
    assert "Older private source text." not in seen[-1]["history"]
    assert seen[-1]["preference"] == "local"
    assert local_calls[-1]["model"] == "local"


def test_chat_does_not_silently_drop_a_selected_document_after_access_revocation(monkeypatch):
    put_document("allowed", ["Inspection is scheduled."])
    put_document("revoked", ["Inspection is scheduled."])
    convo = chat.create_conversation()
    reader = Reader()
    monkeypatch.setattr(analysis, "collection_generate",
                        lambda system, prompt, *, target_words: reader(system, prompt))
    result = chat.ask(
        convo["id"], "Summarize these documents",
        allowed_document_ids=frozenset({"allowed"}),
        document_ids=frozenset({"allowed", "revoked"}),
    )
    assert result["answer"] is None
    assert result["summary_coverage"]["requested"] == 2
    assert result["summary_coverage"]["processed"] == 0
    assert reader.prompts == []


def test_completed_chat_summary_reopens_with_coverage_and_obeys_revoked_access(monkeypatch):
    for doc_id in ("one", "two"):
        put_document(doc_id, ["Inspection is scheduled.", "Inspection is scheduled."])
    reader = Reader()
    monkeypatch.setattr(analysis, "collection_generate",
                        lambda system, prompt, *, target_words: reader(system, prompt))
    ids = frozenset({"one", "two"})
    convo = chat.create_conversation()
    answer = chat.ask(convo["id"], "Summarize these two documents in one page",
                      allowed_document_ids=ids, document_ids=ids)
    assert answer["answer_type"] == "generated", answer["reason"]
    assert "2 of 2 selected documents" in answer["used_line"]
    reopened = chat.get_messages(convo["id"], allowed_document_ids=ids)[-1]
    assert reopened["payload"]["summary_coverage"]["cited_documents"] == 2
    revoked = chat.get_messages(convo["id"], allowed_document_ids=frozenset({"one"}))[-1]
    assert revoked["payload"] == {"withheld": True}

