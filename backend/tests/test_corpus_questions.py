"""Questions about the library, and counts that pretend to be about it.

THE DEFECT. Asked how many standards there are, Document Q&A answered "there
are 12 distinct standards" - from three retrieved passages, of a library
holding 272. Two faults, and one half of this file for each:

  1. THE COUNT STATED AS A CORPUS FACT (CLAUDE.md rule 4). A generated answer
     sees a few passages, never the library, so a count of documents it gives
     is a count of those passages - and must SAY SO, in the word "retrieved".
     Enforced on the model's OUTPUT, because the model can ignore a prompt.

  2. THE QUESTION WENT TO THE WRONG PLACE. "How many standards do you have"
     asks about the library, and the library is a table: a scoped COUNT
     answers it exactly. Retrieval stays for content. A question that asks
     both - "how many standards cover X" - gets both, in separate fields.

Every routing test that expects RETRIEVAL matters as much as the ones that
expect the database: a false positive would answer "which standards cover
coating?" with a library total and never search, which is the worse failure.

Mutations: M251-M263, `python scripts/mutation_check.py --phase 25`.
"""

from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import access, answer, corpus, db, keyword, search
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

NOW = "2026-09-20T00:00:00Z"

VIBRATION = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow.",
    "Any exceedance shall be reported to the area engineer before the pump is",
    "returned to service under the procedure given in this specification.",
]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "c.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    app.dependency_overrides.clear()
    db.reset_connection()


def _doc(doc_id: str, role: str | None, status: str = "ready") -> str:
    """A document row with a role - enough for the database's half."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,page_count,uploaded_at) VALUES (?,?,?,1,?,?,1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", status, NOW))
        conn.execute(
            "INSERT INTO document_classification (document_id,document_role,"
            "suggested_by) VALUES (?,?,'test')", (doc_id, role))
    return doc_id


def _uploaded_standard(client) -> str:
    """A REAL, ingested, searchable standard - so retrieval and its lexical
    gate run for real, and only the model's reply is faked."""
    path = settings.data_dir / "spec.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    for i, line in enumerate(VIBRATION):
        page.insert_text((72, 100 + i * 16), line)
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": ("spec.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id,document_role,"
            "suggested_by) VALUES (?,'COMPANY_STANDARD','test')"
            " ON CONFLICT(document_id) DO UPDATE SET document_role="
            "'COMPANY_STANDARD'", (doc_id,))
    return doc_id


# ================================================= part 1: the routing rule


@pytest.mark.parametrize("question, kind, role", [
    ("how many standards are there?", "count", "COMPANY_STANDARD"),
    ("How many standards do you have?", "count", "COMPANY_STANDARD"),
    ("how many company standards are in the library", "count", "COMPANY_STANDARD"),
    ("number of submittals", "count", "CONTRACTOR_SUBMITTAL"),
    ("how many documents are uploaded?", "count", None),
    ("list all standards", "list", "COMPANY_STANDARD"),
    ("which standards do you have?", "list", "COMPANY_STANDARD"),
    ("what is loaded?", "list", None),
])
def test_a_question_about_the_library_goes_to_the_database(question, kind, role):
    q = corpus.classify(question)
    assert q is not None, f"{question!r} was sent to retrieval"
    assert (q.kind, q.role, q.qualified) == (kind, role, False)


@pytest.mark.parametrize("question", [
    "which standards apply to the drum?",
    "which standards cover coating?",
    "what does SAES-L-132 say about hydrotest",
    "how many nozzles does the vessel have",
    "how many valves are on the datasheet",
    "list the requirements of SAES-L-132",
    "what is the design pressure",
])
def test_a_content_question_stays_with_retrieval(question):
    """THE GUARD ON THE ROUTER. A false positive answers a real question with
    a library total and never searches - the worse of the two failures."""
    assert corpus.classify(question) is None


def test_a_question_about_both_is_marked_for_both():
    q = corpus.classify("how many standards cover hydrotesting?")

    assert q is not None and q.qualified
    assert "hydrotesting" in q.content


# ============================================ part 1: the database's answer


def test_the_count_comes_from_the_database_in_the_words_the_task_gives():
    for i in range(3):
        _doc(f"std{i}", "COMPANY_STANDARD")
    _doc("sub", "CONTRACTOR_SUBMITTAL")
    scope = frozenset({"std0", "std1", "std2", "sub"})

    fact = corpus.statement(corpus.classify("how many standards are there?"),
                            allowed_document_ids=scope)

    assert fact["text"] == "3 company standards are loaded and readable by you."
    assert fact["loaded"] == 3 and fact["source"] == "database"


def test_one_is_singular():
    _doc("sub", "CONTRACTOR_SUBMITTAL")

    fact = corpus.statement(corpus.classify("how many submittals"),
                            allowed_document_ids=frozenset({"sub"}))

    assert fact["text"] == "1 contractor submittal is loaded and readable by you."


def test_a_standard_outside_the_grant_set_is_not_counted():
    """RULE 5. A count must not become the cheapest way to learn how many
    documents exist that you cannot read."""
    _doc("mine", "COMPANY_STANDARD")
    _doc("theirs", "COMPANY_STANDARD")

    fact = corpus.statement(corpus.classify("how many standards"),
                            allowed_document_ids=frozenset({"mine"}))

    assert fact["loaded"] == 1


def test_an_empty_scope_says_what_you_can_read_not_what_exists():
    """Not "0 standards exist" - a claim about documents the caller cannot
    see. What is true is that they can read none."""
    _doc("hidden", "COMPANY_STANDARD")

    fact = corpus.statement(corpus.classify("how many standards"),
                            allowed_document_ids=frozenset())

    assert fact["text"] == "No company standards are loaded that you can read."


def test_a_standard_still_processing_is_not_counted_as_loaded():
    _doc("done", "COMPANY_STANDARD")
    _doc("busy", "COMPANY_STANDARD", status="extracting")

    fact = corpus.statement(corpus.classify("how many standards"),
                            allowed_document_ids=frozenset({"done", "busy"}))

    assert fact["loaded"] == 1 and fact["not_loaded"] == 1
    assert "1 more is not yet loaded" in fact["text"]


def test_what_is_loaded_is_broken_down_by_role():
    for i in range(2):
        _doc(f"std{i}", "COMPANY_STANDARD")
    _doc("sub", "CONTRACTOR_SUBMITTAL")

    fact = corpus.statement(corpus.classify("what is loaded?"),
                            allowed_document_ids=frozenset({"std0", "std1", "sub"}))

    assert fact["text"].startswith("3 documents are loaded and readable by you:")
    assert "2 company standards" in fact["text"]
    assert "1 contractor submittal" in fact["text"]


def test_list_all_points_at_the_full_list_rather_than_printing_a_partial_one():
    _doc("std0", "COMPANY_STANDARD")

    fact = corpus.statement(corpus.classify("list all standards"),
                            allowed_document_ids=frozenset({"std0"}))

    assert "Standards Library" in fact["text"]


# ======================================== part 1: answer() routes, for real


def test_a_library_question_is_answered_without_searching(monkeypatch):
    """NOTHING IS RETRIEVED. The defect was a library question answered from
    three passages; the fix is that no passage is ever fetched for one."""
    _doc("std0", "COMPANY_STANDARD")

    def no_search(*a, **k):
        raise AssertionError("a library question reached retrieval")

    monkeypatch.setattr(search, "search", no_search)
    result = answer.answer("how many standards are there?",
                           allowed_document_ids=frozenset({"std0"}))

    assert result["answer_type"] == "metadata"
    assert result["answer"] == "1 company standard is loaded and readable by you."
    assert result["corpus"]["source"] == "database"
    assert result["passages"] == []


def test_a_question_about_both_gets_both_in_separate_fields():
    """"How many standards cover vibration" - the library's count from the
    database AND retrieval for the part only documents can answer. Separate
    fields, so no screen can blend the two into one sentence."""
    client = TestClient(app)
    std = _uploaded_standard(client)

    result = answer.answer("how many standards cover vibration limits for pump P-101A?",
                           allowed_document_ids=frozenset({std}))

    assert result["corpus"]["text"] == "1 company standard is loaded and readable by you."
    assert result["corpus"]["qualified"] is True
    assert result["answer_type"] != "metadata", "retrieval never ran"
    assert result["candidates_considered"] > 0


def test_a_question_scoped_to_one_document_is_about_its_content():
    """"How many standards" asked OF one specification means the standards it
    cites - a content question, so the library is not consulted."""
    client = TestClient(app)
    std = _uploaded_standard(client)

    result = answer.answer("how many standards are there?", document_id=std,
                           allowed_document_ids=frozenset({std}))

    assert "corpus" not in result
    assert result["answer_type"] != "metadata"


# ==================================== part 2: a generated count is bounded


def test_a_counting_question_names_its_boundary(monkeypatch):
    """THE TEST THE TASK ASKS FOR, AND THE DEFECT ITSELF. The model is given
    the passages retrieval found and replies exactly as it did in production:
    "There are 12 distinct standards". The answer must name its boundary -
    the passages RETRIEVED - and must not present 12 as the library's size.
    """
    client = TestClient(app)
    std = _uploaded_standard(client)
    monkeypatch.setattr(
        answer, "_call_model",
        lambda prompt, timeout=180.0: {
            "response": "There are 12 distinct standards covering vibration [S1]."})

    result = answer.answer("how many standards cover vibration limits for pump P-101A?",
                           tier="generated", allowed_document_ids=frozenset({std}))

    assert result["answer_type"] == "generated", result.get("reason")
    text = result["answer"]
    assert "retrieved" in text, f"the count names no boundary: {text!r}"
    assert "12 distinct standards (counted in the" in text
    assert "not in the library" in text
    assert result["counts_bounded"] == 1
    # And the library's own answer sits beside it, from the database.
    assert result["corpus"]["text"] == "1 company standard is loaded and readable by you."


def test_a_count_that_already_names_its_boundary_is_left_as_written(monkeypatch):
    """The guard only acts on a count that does NOT say "retrieved" - a model
    that already states its boundary is not rewritten."""
    client = TestClient(app)
    std = _uploaded_standard(client)
    written = "The retrieved passages mention 1 standard and 2 procedures [S1]."
    monkeypatch.setattr(answer, "_call_model",
                        lambda prompt, timeout=180.0: {"response": written})

    result = answer.answer("what are the vibration limits for pump P-101A?",
                           tier="generated", allowed_document_ids=frozenset({std}))

    assert result["answer"] == written
    assert result["counts_bounded"] == 0


@pytest.mark.parametrize("sentence", [
    "There are 12 distinct standards [S1].",
    "The library contains twelve standards [S1].",
    "A total of 7 documents address this [S2].",
    "Across the corpus, 3 specifications apply [S1].",
])
def test_every_unbounded_count_of_documents_is_bounded(sentence):
    out, n = corpus.bound_counts(sentence, 3)

    assert n == 1
    assert "retrieved" in out
    assert "3 passages retrieved for this question, not in the library" in out


@pytest.mark.parametrize("sentence", [
    "The vessel has 4 nozzles [S1].",
    "The design pressure is 6,900 kPa [S1].",
    "Clause 6.2.2 applies to 2 pumps [S1].",
    "The retrieved passages list 12 standards [S1].",
])
def test_counts_bounded_by_their_citation_are_left_alone(sentence):
    """"4 nozzles [S1]" counts things IN a cited passage; the citation is its
    boundary. Only a count of DOCUMENTS ranges over the unseen library."""
    assert corpus.bound_counts(sentence, 3) == (sentence, 0)


def test_the_boundary_does_not_argue_with_the_sentence():
    """"The library contains twelve standards (counted in the passages)"
    would contradict itself; the library framing is neutralised, and the
    sentence keeps its capital."""
    out, _ = corpus.bound_counts("The library contains twelve standards [S1].", 3)

    assert out.startswith("The retrieved passages mention twelve standards")
    assert "library contains" not in out


def test_paragraphs_and_bullets_survive_and_each_line_is_checked():
    """A first version re-joined sentences with one space and would have
    flattened the lists the prompt asks the model for."""
    text = "Scope:\n- 12 standards in total [S1]\n- 3 specifications [S2]\n\nSee [S1]."

    out, n = corpus.bound_counts(text, 2)

    assert n == 2
    assert out.count("\n") == text.count("\n")
    assert "in total" not in out
    assert out.endswith("\n\nSee [S1].")


def test_the_real_models_own_words_are_bounded():
    """VERBATIM, FROM THE REAL MODEL, asked "how many standards cover
    hydrostatic testing" against the live corpus. It wrapped the number in
    Markdown bold - "**five** distinct standards" - and the first version of
    the guard, tested only on plain synthetic text, let that sentence through.
    Its "Based on the provided sources" is close, but the rule requires the
    word "retrieved"."""
    real = ("Based on the provided sources, **five** distinct standards are "
            "referenced regarding hydrostatic testing requirements.\n\n"
            "*   **SAES-L-150**: Defines the general requirement [S1], [S3].\n\n"
            "While the sources do not explicitly state a total count, they "
            "collectively reference these five unique documents that govern "
            "hydrostatic testing procedures.")

    out, n = corpus.bound_counts(real, 3)

    assert n == 2, "a count in the real model's answer went unbounded"
    first = out.split("\n")[0]
    assert "**five** distinct standards (counted in the 3 passages retrieved" in first
    assert "*   **SAES-L-150**" in out, "the Markdown list was disturbed"


@pytest.mark.parametrize("sentence", [
    "There are **12** standards [S1].",
    "There are **12 distinct** standards [S1].",
    "There are `12` documents [S1].",
    "There are _twelve_ specifications [S1].",
])
def test_markdown_around_the_count_does_not_hide_it(sentence):
    out, n = corpus.bound_counts(sentence, 3)

    assert n == 1 and "retrieved" in out


def test_one_retrieved_passage_is_singular():
    out, _ = corpus.bound_counts("There are 5 standards [S1].", 1)

    assert "in the 1 passage retrieved" in out


# ======================================== through the route, and on replay


def test_the_route_returns_the_database_answer_and_keeps_it_on_replay():
    """Both allow-lists this crosses - the response model and the payload
    persisted for replay - drop any field they do not name. Asserted on the
    wire and on the reopened conversation, where a missing field would be
    silently absent rather than an error."""
    _doc("std0", "COMPANY_STANDARD")
    _doc("std1", "COMPANY_STANDARD")
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({"std0", "std1"}),
        unrestricted=True)
    client = TestClient(app)
    conversation = client.post("/api/conversations", json={}).json()["id"]

    body = client.post(f"/api/conversations/{conversation}/ask",
                       json={"question": "how many standards are loaded?"}).json()

    assert body["answer_type"] == "metadata"
    assert body["answer"] == "2 company standards are loaded and readable by you."
    assert body["corpus"]["loaded"] == 2

    replay = client.get(f"/api/conversations/{conversation}").json()
    assistant = [m for m in replay["messages"] if m["role"] == "assistant"][-1]
    assert assistant["payload"]["corpus"]["loaded"] == 2, \
        "reopening the conversation lost the database answer"
