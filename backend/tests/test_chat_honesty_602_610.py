"""Chat answer honesty: a missing qualifier word (#602) and front matter (#610).

#602: a question carrying one extra describing word the documents never print
("ASME-certified liquid service relief valves") was REFUSED - "ASME-certified
does not appear in the indexed documents" - while the same question without
the word was answered from the right clause. A capitalised hyphenated word
was read as a named subject. It is now set aside when the word it describes
is in the documents, and the answer says so.

#610: a bolting question quoted a standard's foreword / revision history as
the answer, with a green "1 of 1 point found on the page". Front matter is
now ranked below the clauses, refused when it is all that matched, and never
counted as a point that answers the question - unless the question asks
about it.

Invented documents only. Mutations M3201-M3212.
"""
from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat_presentation, db, front_matter, keyword, lexical
from app import passages as passages_mod
from app import search as search_mod
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

# ----------------------------------------------------------- #602, end to end

RELIEF = [
    "STD-L-011 Pressure Relief Device Sizing, Part 1, Revision 0",
    "1 Scope",
    "1.1 This part covers the sizing of pressure relief devices for vessels.",
    "5 Liquid Service",
    "5.1 Relief valves in liquid service shall reach full rated capacity",
    "at an overpressure of 10 percent of the set pressure.",
    "5.2 The set pressure shall not exceed the design pressure of the vessel.",
]

PLAIN = "At what overpressure must liquid service relief valves reach full rated capacity?"
QUALIFIED = ("At what overpressure must ASME-certified liquid service relief valves "
             "reach full rated capacity?")


@pytest.fixture
def relief(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "relief.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(RELIEF):
        page.insert_text((72, 90 + i * 15), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = TestClient(app).post(
            "/api/documents", files={"file": ("relief.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    yield frozenset({doc_id})
    db.reset_connection()


def test_the_question_without_the_qualifier_is_answered(relief):
    """The control: if this fails, the test below proves nothing."""
    r = answer_mod.answer(PLAIN, allowed_document_ids=relief)
    assert r["answer_type"] == "extract", r.get("reason")
    assert "10 percent" in r["answer"]


def test_a_missing_qualifier_word_does_not_refuse_strong_matches(relief):
    """THE DEFECT (#602): one describing word not in the documents refused a
    question whose every other term matched the answering clause."""
    r = answer_mod.answer(QUALIFIED, allowed_document_ids=relief)
    assert r["answer_type"] == "extract", r.get("reason")
    assert "10 percent" in r["answer"]


def test_the_answer_names_the_word_that_was_not_found(relief):
    r = answer_mod.answer(QUALIFIED, allowed_document_ids=relief)
    assert r["lexical"]["unmatched_qualifiers"] == ["ASME-certified"]
    assert r["notices"] == [
        '"ASME-certified" was not found in the documents searched. '
        "It was set aside, so nothing here confirms it."]


def test_the_model_is_asked_the_question_without_the_missing_word(relief, monkeypatch):
    """Asked WITH the word, the model answers "INSUFFICIENT EVIDENCE" for a
    passage that answers everything else - the model-path half of #602."""
    seen: list[str] = []

    def model(prompt, timeout=180.0):
        seen.append(prompt)
        return {"response": "Full rated capacity at 10 percent overpressure [S1]."}

    monkeypatch.setattr(answer_mod, "claude_lane", lambda: False)
    monkeypatch.setattr(answer_mod, "_call_model", model)
    r = answer_mod.answer(QUALIFIED, tier="generated", allowed_document_ids=relief)
    assert r["answer_type"] == "generated", r.get("reason")
    assert seen and "ASME-certified" not in seen[0]
    assert "liquid service relief valves" in seen[0]
    assert any("ASME-certified" in n for n in r["notices"])


@pytest.mark.parametrize("question", [
    # a named subject that is not a qualifier: still refused
    "At what overpressure must Inconel relief valves reach full rated capacity?",
    # a designation is never a qualifier
    "At what overpressure does STD-Q-999 require relief valves to reach full rated capacity?",
    # a qualifier describing a word the documents do not hold
    "At what overpressure must ASME-certified gearboxes reach full rated capacity?",
])
def test_a_missing_subject_still_refuses(relief, question):
    r = answer_mod.answer(question, allowed_document_ids=relief)
    assert r["answer_type"] == "insufficient_evidence"


@pytest.mark.parametrize(("term", "question", "expected"), [
    ("ASME-certified", "must ASME-certified relief valves open", True),
    ("UL-listed", "are UL-listed relief devices required", True),
    ("ASME-certified", "must ASME-certified gearboxes open", False),   # next word absent
    ("ASME-certified", "are the valves ASME-certified", False),        # describes nothing
    ("STD-Q-999", "does STD-Q-999 relief apply", False),               # a designation
    ("Inconel", "must Inconel relief valves open", False),             # no lowercase tail
])
def test_what_counts_as_a_qualifier(term, question, expected):
    assert lexical.is_absent_qualifier(term, question, ["relief", "valves"]) is expected


# ------------------------------------------------- #610, through answer()

def _hit(cid: str, section: str | None, text: str, score: float, doc: str = "d1") -> dict:
    return {"chunk_id": cid, "document_id": doc, "filename": f"{doc}.pdf", "section": section,
            "page_start": 1, "page_end": 1, "text": text, "rerank_score": score,
            "separation": 0.1, "rrf": 0.03, "context": None, "score": score}


FOREWORD = _hit("c-fw", None, "STD-M-012 Flanged Joints, Revision 3 Foreword "
                "This revision replaces Revision 2.", 4.2)
HISTORY = _hit("c-hist", "Revision history", "Revision history Revision 2 changed the "
               "bolting material requirements for flanged joints.", 9.1)
CLAUSE = _hit("c-41", "4.1", "4 Bolting 4.1 Bolting material shall be alloy steel stud "
              "bolts to grade B7 with grade 2H heavy hex nuts.", -4.2)

BOLTING = "What bolting material is required for flanged joints?"


@pytest.fixture
def fixed_hits(monkeypatch, tmp_path):
    """Retrieval returns what each test says; every passage is lexically
    plausible (the lexical gate is tested above and elsewhere)."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "e.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    monkeypatch.setattr(lexical, "assess", lambda *a, **k: {
        "ok": True, "reason": None, "coverage": 1.0, "terms": [], "covered": [],
        "absent_from_corpus": []})
    monkeypatch.setattr(passages_mod, "expand_passage", lambda *a, **k: {})
    monkeypatch.setattr(answer_mod, "_coverage", lambda *a, **k: None)
    calls: list[int] = []

    def serve(hits):
        def search(question, limit=10, **k):
            calls.append(limit)
            return {"hits": [dict(h) for h in hits], "mode": "hybrid", "reranked": True,
                    "timings": {}, "total": len(hits), "seconds": 0.0}
        monkeypatch.setattr(search_mod, "search", search)
        return calls

    yield serve
    db.reset_connection()


def test_the_clause_is_quoted_not_the_revision_history(fixed_hits):
    """THE DEFECT (#610): the revision history ranked first and was quoted.
    The clause is in the window, so it is found by ranking alone - without
    the second, wider search (which costs a whole retrieval on this laptop)."""
    calls = fixed_hits([HISTORY, FOREWORD, CLAUSE])
    r = answer_mod.answer(BOLTING, allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "extract", r.get("reason")
    assert r["passage"]["chunk_id"] == "c-41"
    assert len(calls) == 1


def test_the_clause_is_not_refused_for_the_score_the_foreword_took(fixed_hits):
    """The cross-encoder scored the foreword above the clause that answers;
    the clause's own low score must not refuse what the foreword alone was
    allowed to answer."""
    fixed_hits([FOREWORD, CLAUSE])
    r = answer_mod.answer(BOLTING, allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "extract", r.get("reason")
    assert r["passage"]["chunk_id"] == "c-41"


def test_a_weak_clause_with_no_front_matter_above_it_still_refuses(fixed_hits):
    """The vouching is for front matter's own document only."""
    other = _hit("c-fw2", None, "STD-X-001 Gaskets Foreword This revision replaces "
                 "Revision 1.", 4.2, doc="d2")
    fixed_hits([other, CLAUSE])
    r = answer_mod.answer(BOLTING, allowed_document_ids=frozenset({"d1", "d2"}))
    assert r["answer_type"] == "insufficient_evidence"


def test_only_front_matter_matched_is_refused_and_looked_past_once(fixed_hits):
    calls = fixed_hits([HISTORY, FOREWORD])
    r = answer_mod.answer(BOLTING, allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "insufficient_evidence"
    assert r["reason"] == answer_mod.FRONT_MATTER_REASON.format(filename="d1.pdf")
    # one wider search, at twice the depth
    assert len(calls) == 2 and calls[1] == 2 * calls[0]
    # the passages are still shown, for the reader to judge
    assert {p["chunk_id"] for p in r["passages"]} == {"c-hist", "c-fw"}


def test_the_wider_look_finds_the_clause_ranked_out_of_the_window(fixed_hits, monkeypatch):
    """Measured in the repro: other documents' title lines pushed the clause
    to rank 10 for a question naming the document."""
    titles = [_hit(f"t{i}", None, f"STD-T-00{i} Title page, Revision 1", 1.0, doc=f"t{i}")
              for i in range(6)]
    first = [FOREWORD, HISTORY, *titles]
    wider = [FOREWORD, HISTORY, *titles, CLAUSE]
    served = iter([first, wider])

    def search(question, limit=10, **k):
        hits = next(served)
        return {"hits": [dict(h) for h in hits], "mode": "hybrid", "reranked": True,
                "timings": {}, "total": len(hits), "seconds": 0.0}

    fixed_hits([])
    monkeypatch.setattr(search_mod, "search", search)
    monkeypatch.setattr(lexical, "assess", lambda q, text, *a, **k: {
        "ok": "bolting" in text.lower(), "reason": None if "bolting" in text.lower() else "no",
        "coverage": 1.0, "terms": [], "covered": [], "absent_from_corpus": []})
    scope = frozenset({"d1", *(f"t{i}" for i in range(6))})
    r = answer_mod.answer(BOLTING, allowed_document_ids=scope)
    assert r["answer_type"] == "extract", r.get("reason")
    assert r["passage"]["chunk_id"] == "c-41"


def test_a_question_about_the_revision_history_is_answered_from_it(fixed_hits):
    fixed_hits([HISTORY, FOREWORD, CLAUSE])
    r = answer_mod.answer("What did Revision 2 change about the bolting material?",
                          allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "extract"
    assert r["passage"]["chunk_id"] == "c-hist"
    assert chat_presentation.verification(r)["verified"] == 1


# ------------------------------------------------- #610, the tick

def _extract(question: str, *passages: dict) -> dict:
    return {"answer_type": "extract", "question": question,
            "answer_passages": [dict(p) for p in passages]}


def test_front_matter_quoted_as_the_answer_is_not_a_point_found(fixed_hits):
    """THE DEFECT (#610): "1 of 1 point found on the page", green, over a
    foreword. The words are on the page; they answer nothing."""
    v = chat_presentation.verification(_extract(BOLTING, HISTORY))
    assert v == {"verified": 0, "total": 1, "method": "verbatim quotation"}


def test_a_clause_quoted_as_the_answer_is_a_point_found():
    v = chat_presentation.verification(_extract(BOLTING, CLAUSE, HISTORY))
    assert v == {"verified": 1, "total": 2, "method": "verbatim quotation"}


def test_a_second_passage_is_never_front_matter(monkeypatch):
    monkeypatch.setattr(lexical, "distinguishing_uncovered_terms", lambda *a, **k: ["joints"])
    monkeypatch.setattr(lexical, "assess", lambda *a, **k: {"ok": True})
    second = answer_mod._second_passage(
        BOLTING, [CLAUSE, HISTORY], CLAUSE, None, frozenset({"d1"}))
    assert second is None


# ------------------------------------------------- front matter, generic

@pytest.mark.parametrize(("section", "context", "text", "expected"), [
    ("Revision history", None, "Revision 2 changed things.", True),
    ("0.1 Foreword", None, "This edition replaces the last.", True),
    ("4.1", "Front > Table of Contents", "1 Scope ... 3", True),
    (None, None, "STD-M-012 Flanged Joints Foreword This revision replaces 2.", True),
    (None, None, "STD-M-012 Flanged Joints, Revision 3", False),          # a title line
    ("7.3", None, "Foreword text quoted inside a clause body.", False),   # a clause
    (None, None, "the history of each tank shall be kept on file", False),  # prose
    ("4.1", "4 Bolting > 4.1", "Bolting material shall be alloy steel.", False),
])
def test_what_is_front_matter(section, context, text, expected):
    assert front_matter.is_front_matter(
        {"section": section, "context": context, "text": text}) is expected


def test_front_matter_comes_from_the_editable_file(tmp_path, monkeypatch):
    """Generic: a heading the file does not list is not front matter, and
    adding it to the file - no code change - makes it so."""
    passage = {"section": "Errata", "context": None, "text": "Table 2 corrected."}
    assert front_matter.is_front_matter(passage) is False
    data = json.loads(front_matter.VOCABULARY_PATH.read_text(encoding="utf-8"))
    data["headings"].append("errata")
    edited = tmp_path / "front_matter.json"
    edited.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(front_matter, "VOCABULARY_PATH", edited)
    front_matter.reload_vocabulary()
    try:
        assert front_matter.is_front_matter(passage) is True
    finally:
        monkeypatch.undo()
        front_matter.reload_vocabulary()


def test_rank_down_keeps_everything_and_moves_front_matter_last():
    ranked = front_matter.rank_down([HISTORY, FOREWORD, CLAUSE], BOLTING)
    assert [h["chunk_id"] for h in ranked] == ["c-41", "c-hist", "c-fw"]
    asked = front_matter.rank_down([HISTORY, CLAUSE], "what did revision 2 change")
    assert [h["chunk_id"] for h in asked] == ["c-hist", "c-41"]
