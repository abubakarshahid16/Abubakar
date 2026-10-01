"""Issue #373: a question naming a FAMILY of standards in general words ("the
welding standards") is searched per standard, never in one shared pass.

Evidence recorded 2026-10-01: such a question went through ONE retrieval over
everything the caller may read, so one standard's passages crowded another's
out of the shared top-k and a standard that was never searched on its own could
be reported silent on a topic it does cover.

Invented standards only (STD-A-001 ...). Real ingestion, real hybrid search,
the extract tier: no model, no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import applicability, chat_comparison, db, family_search
from app.main import app
from tests.test_chat_comparison import temp_storage, upload  # noqa: F401  (autouse fixture)


def _std(client, blocks, name, *, scope_activity=None, role="COMPANY_STANDARD") -> str:
    doc_id = upload(client, blocks, name)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by, document_role)"
            " VALUES (?, 'test', ?) ON CONFLICT(document_id) DO UPDATE SET document_role=excluded.document_role",
            (doc_id, role))
    if scope_activity:
        applicability.store_scope_record(doc_id, {"covered_activities": [
            {"activity": scope_activity, "quote": scope_activity, "page": 1}]})
    return doc_id


#: Strong, repeated wording about the topic: fills a shared top-k on its own.
LOUD = [[f"{n}.1 Post Weld Heat Treatment",
         "Post weld heat treatment of welds in this standard shall follow the",
         f"holding schedule {n} stated here for the welding procedure qualified."]
        for n in range(1, 7)]
#: One quiet page that DOES cover the topic, with a number to find.
QUIET = [["7.4 Post Weld Heat Treatment",
          "Post weld heat treatment of welds shall hold at 640 degrees C minimum."]]
NO_TOPIC = [["1 Scope", "This standard covers the welding of structural supports only",
             "and says nothing of any thermal treatment after fabrication work."]]
#: Covers welding by its scope record but has nothing on the topic.
OTHER_TOPIC = [["1 Scope", "This standard prescribes the coating of storage tank floors",
                "with a two coat epoxy system applied to blasted steel surfaces."]]

FAMILY_Q = "what do the welding standards say about post weld heat treatment?"


def _library(client):
    ids = {
        "a": _std(client, LOUD, "STD-A-001.pdf", scope_activity="welding of piping"),
        "b": _std(client, LOUD, "STD-B-002.pdf", scope_activity="welding of vessels"),
        "c": _std(client, QUIET, "STD-C-003.pdf", scope_activity="welding of supports"),
        "d": _std(client, OTHER_TOPIC, "STD-D-004.pdf", scope_activity="welding of tanks"),
        # a standard that is not about welding at all
        "p": _std(client, OTHER_TOPIC, "STD-P-005.pdf", scope_activity="painting of tanks"),
    }
    return ids, {v: f"{k}.pdf" for k, v in ids.items()}


def _run(question, ids, allowed=None):
    docs = {v: n for v, n in _names(ids).items()}
    return family_search.run(
        question, docs, tier="extract",
        allowed_document_ids=frozenset(allowed if allowed is not None else ids.values()),
        progress_id=None, model=None, history="")


def _names(ids):
    with db.connect() as conn:
        return {r[0]: r[1] for r in conn.execute("SELECT id, filename FROM documents")}


# ------------------------------------------------------------- (a) crowding


def test_a_shared_search_hides_a_standard_that_per_standard_search_finds():
    """THE MUTATION TARGET: the quiet standard DOES cover the topic. One shared
    pass over the whole family never shows it (the loud standards fill the
    top-k); each standard on its own budget does."""
    client = TestClient(app)
    ids, _ = _library(client)
    allowed = frozenset(ids.values())

    shared = answer_mod.answer(FAMILY_Q, tier="extract", allowed_document_ids=allowed)
    from app import chat_presentation
    assert ids["c"] not in {p["document_id"] for p in chat_presentation.used_passages(shared)}, (
        "fixture no longer reproduces the crowding this test is about")

    result, notice = _run(FAMILY_Q, ids)
    assert notice is None and result is not None
    by_name = {s["name"]: s for s in result["comparison"]["sides"]}
    quiet = by_name["STD-C-003"]
    assert quiet["answer_type"] == "extract" and quiet["source_count"] == 1
    assert "640" in quiet["text"]
    assert ids["c"] in {p["document_id"] for p in result["passages"]}


def test_each_standard_is_its_own_side_with_its_own_citation_range():
    client = TestClient(app)
    ids, _ = _library(client)
    result, _ = _run(FAMILY_Q, ids)
    sides = result["comparison"]["sides"]
    assert {s["name"] for s in sides} == {"STD-A-001", "STD-B-002", "STD-C-003", "STD-D-004"}
    cursor = 0
    for side in sides:
        assert side["source_start"] == cursor
        cursor += side["source_count"]
    assert cursor == len(result["passages"])


def test_a_standard_whose_own_search_finds_nothing_gets_the_code_written_sentence():
    client = TestClient(app)
    ids, _ = _library(client)
    result, _ = _run(FAMILY_Q, ids)
    by_name = {s["name"]: s for s in result["comparison"]["sides"]}
    assert by_name["STD-D-004"]["answer_type"] == "insufficient_evidence"
    assert by_name["STD-D-004"]["text"] == "STD-D-004: not found in the pages read."
    assert "does not mention" not in result["answer"].lower()


# ------------------------------------------- (b) what was searched, as a guess


def test_the_answer_lists_the_searched_standards_and_calls_membership_a_guess():
    client = TestClient(app)
    _library(client)
    convo = client.post("/api/conversations").json()
    body = client.post(f"/api/conversations/{convo['id']}/ask", json={"question": FAMILY_Q}).json()

    assert body["answer_type"] == "comparison"
    family = body["comparison"]["family"]
    assert family["membership_is_a_guess"] is True
    assert family["searched"] == ["STD-A-001", "STD-B-002", "STD-C-003", "STD-D-004"]
    assert family["label"] == "welding"
    assert body["answer"].startswith(
        "Searched 4 standards judged to be welding standards: STD-A-001, STD-B-002,")
    assert "is a guess" in body["answer"] and "until a person confirms it" in body["answer"]
    # the painting standard was never judged a welding standard, never searched
    assert "STD-P-005" not in body["answer"]
    assert "STD-P-005" not in {s["name"] for s in body["comparison"]["sides"]}
    # and the breakdown survives reopening the conversation
    reopened = client.get(f"/api/conversations/{convo['id']}").json()
    assistant = [m for m in reopened["messages"] if m["role"] == "assistant"][-1]
    assert assistant["payload"]["comparison"]["family"]["searched"]


# ---------------------------------------- (c) named standards: existing path


def test_a_question_naming_specific_standards_takes_the_existing_compare_path():
    client = TestClient(app)
    _library(client)
    convo = client.post("/api/conversations").json()
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "compare STD-A-001 and STD-C-003 on post weld heat treatment"}).json()
    assert body["answer_type"] == "comparison"
    assert body["comparison"].get("family") is None
    assert {s["name"] for s in body["comparison"]["sides"]} == {"STD-A-001", "STD-C-003"}
    assert "Searched" not in body["answer"]


def test_a_family_phrase_that_also_names_a_standard_is_left_to_the_existing_path():
    client = TestClient(app)
    ids, _ = _library(client)
    result, notice = _run(
        "what do the welding standards say about STD-A-001 post weld heat treatment",
        ids)
    assert result is None and notice is None


# --------------------------------------------------- (d) a non-family question


@pytest.mark.parametrize("question", [
    "what does STD-A-001 say about post weld heat treatment",
    "what is post weld heat treatment",
    "which welding standards do we have",
    "welding standards for pumps",
    "what do the applicable standards say about hydrotest",
    "what do the standards say",
    "compare the two documents",
    "tell me about the standard welding procedure",
    "what do the welding standards say about STD-A-001 post weld heat treatment",
])
def test_a_non_family_question_is_not_intercepted(question):
    assert family_search.detect(question) is None


@pytest.mark.parametrize("question, descriptor, topic", [
    ("what do the welding standards say about post weld heat treatment?",
     "welding", "post weld heat treatment"),
    ("What do our piping specifications require for hydrotest pressure", "piping",
     "hydrotest pressure"),
    ("do the pressure vessel standards say anything about nozzle loads",
     "pressure vessel", "nozzle loads"),
])
def test_a_family_question_is_recognised(question, descriptor, topic):
    assert family_search.detect(question) == (descriptor, topic)


def test_a_plain_question_still_reaches_the_ordinary_pipeline():
    client = TestClient(app)
    _library(client)
    convo = client.post("/api/conversations").json()
    body = client.post(
        f"/api/conversations/{convo['id']}/ask",
        json={"question": "what does STD-C-003 say about post weld heat treatment"}).json()
    assert body["answer_type"] != "comparison"
    assert body.get("comparison") is None


def test_fewer_than_two_standards_says_so_and_falls_back():
    client = TestClient(app)
    ids = {"a": _std(client, LOUD, "STD-A-001.pdf", scope_activity="welding of piping"),
           "p": _std(client, OTHER_TOPIC, "STD-P-005.pdf", scope_activity="painting of tanks")}
    result, notice = _run(FAMILY_Q, ids)
    assert result is None
    assert "found only STD-A-001" in notice and "not searched standard by standard" in notice

    convo = client.post("/api/conversations").json()
    body = client.post(f"/api/conversations/{convo['id']}/ask", json={"question": FAMILY_Q}).json()
    assert body["answer_type"] != "comparison"
    assert any("too few to search one by one" in n for n in body.get("notices") or [])


def test_a_family_nobody_matches_says_none_were_found():
    client = TestClient(app)
    ids = {"p": _std(client, OTHER_TOPIC, "STD-P-005.pdf", scope_activity="painting of tanks")}
    result, notice = _run(FAMILY_Q, ids)
    assert result is None and "and found none." in notice


# ------------------------------------------------------------ (e) permissions


def test_a_standard_the_caller_may_not_read_is_never_searched_or_named():
    client = TestClient(app)
    ids, _ = _library(client)
    allowed = [v for k, v in ids.items() if k != "c"]
    result, _ = _run(FAMILY_Q, ids, allowed=allowed)
    assert result is not None
    names = {s["name"] for s in result["comparison"]["sides"]}
    assert "STD-C-003" not in names
    assert "STD-C-003" not in result["answer"]
    assert ids["c"] not in {p["document_id"] for p in result["passages"]}
    assert "640" not in result["answer"]


def test_a_document_that_is_not_a_standard_is_never_a_candidate():
    client = TestClient(app)
    ids = {"a": _std(client, LOUD, "STD-A-001.pdf", scope_activity="welding of piping"),
           "b": _std(client, LOUD, "STD-B-002.pdf", scope_activity="welding of vessels"),
           "s": _std(client, LOUD, "SUB-Z-009.pdf", scope_activity="welding of skids",
                     role="CONTRACTOR_SUBMITTAL")}
    resolved = family_search.resolve("welding", allowed_document_ids=frozenset(ids.values()))
    assert {n for n, _ in resolved["candidates"]} == {"STD-A-001", "STD-B-002"}


# ----------------------------------------------------------------- (f) the cap


def test_no_more_than_eight_standards_are_searched_and_the_rest_are_admitted(monkeypatch):
    client = TestClient(app)
    ids = {f"s{n}": _std(client, QUIET, f"STD-W-{n:03d}.pdf", scope_activity="welding of parts")
           for n in range(1, 11)}
    seen: list[str] = []
    real = chat_comparison._side_answer

    def spy(question, side_ids, **kw):
        seen.append(question)
        return real(question, side_ids, **kw)

    monkeypatch.setattr(chat_comparison, "_side_answer", spy)
    result, _ = _run(FAMILY_Q, ids)
    assert family_search.MAX_STANDARDS == 8
    assert len(result["comparison"]["sides"]) == 8 and len(seen) == 8
    assert result["comparison"]["family"]["judged"] == 10
    assert "Searched 8 standards" in result["answer"]
    assert "10 standards matched; only the 8 best ranked were searched" in result["answer"]


@pytest.mark.parametrize("forms", [
    ("valve", "valves"), ("pipe", "piping", "pipes"), ("weld", "welds", "welding", "welded"),
    ("pressure", "pressures"), ("class", "classes"), ("coat", "coating", "coatings"),
    ("assembly", "assemblies"), ("pump", "pumps", "pumping"),
])
def test_singular_plural_and_ing_forms_of_a_word_meet(forms):
    """"valve standards" must find a scope record that says "valves"."""
    assert len({family_search.stem(w) for w in forms}) == 1


def test_different_words_do_not_meet():
    assert family_search.stem("process") != family_search.stem("pressure")
    assert family_search.stem("weld") != family_search.stem("well")
