"""Plan step 4: which clause applies, when clauses differ by condition.

Refusal calibration (2026-09-29, counts only): 66 of 166 real questions were
answered from a clause stating a different value; a check of 20 found about
two in three were questions that never said which size or condition applied.
Both clauses were right, for different cases, and one was picked silently.

Now: the question names a condition -> the clause that holds under it answers.
It names none -> every competing clause is shown with its condition and the
reader is asked which applies. Values are never merged; none is guessed.

Synthetic text only. Mutations M1407-M1415 (backend), M1416-M1418 (UI).
"""
from __future__ import annotations

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import chat, db, keyword, lexical
from app import condition_choice as cc
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

# ------------------------------------------------------------ reading conditions


def _read(text: str, question: bool = False) -> list[tuple[str, str]]:
    return [(c.kind, c.text) for c in cc.extract(text, question=question)]


def test_a_comparison_in_a_passage_is_a_condition():
    assert ("size", "larger than 2 inch") in _read("4.3 Pipes larger than 2 inch")
    assert ("size", "2 inch and smaller") in _read("4.2 Pipes 2 inch and smaller")


def test_a_bare_value_in_a_passage_is_not_a_condition():
    """"shall be 5 mm" is the value the clause SETS. Read as a condition,
    every two clauses with different values looked like different cases."""
    assert _read("The minimum wall thickness shall be 5 mm.") == []
    assert _read("The gap shall be 1/2 inch.") == []


def test_a_nominal_pipe_size_in_a_passage_is_a_condition():
    assert ("size", "6 inch") in _read("6 inch pipe shall be seamless")


def test_a_bare_point_in_a_question_is_a_condition():
    assert ("size", "6 inch") in _read("thickness for a 6 inch line", question=True)
    kinds = {k for k, _ in _read("coating at 90 °C in sour service", question=True)}
    assert {"temperature", "service"} <= kinds


def test_a_list_of_two_values_is_not_a_range():
    assert _read("coats of 5 mm and 3 mm") == []


def test_a_question_point_falls_inside_or_outside_a_clause_range():
    larger = cc.extract("Pipes larger than 2 inch")[0]
    smaller = cc.extract("Pipes 2 inch and smaller")[0]
    six = cc.extract("a 6 inch line", question=True)[0]
    two = cc.extract("a 2 inch line", question=True)[0]
    assert larger.holds_for(six) and not smaller.holds_for(six)
    assert smaller.holds_for(two) and not larger.holds_for(two)   # "larger than" is strict


def test_fahrenheit_and_millimetres_are_compared_in_one_unit():
    above = cc.extract("above 60 °C")[0]
    assert above.holds_for(cc.extract("at 150 °F", question=True)[0])        # 65.6 °C
    assert not above.holds_for(cc.extract("at 120 °F", question=True)[0])    # 48.9 °C
    upto = cc.extract("2 inch and smaller")[0]
    assert upto.holds_for(cc.extract("a 50 mm line", question=True)[0])      # 1.97 in


# ------------------------------------------------------------ choosing a clause

def _hit(cid: str, section: str, text: str, score: float, sep: float | None = 0.1) -> dict:
    return {"chunk_id": cid, "document_id": "d1", "filename": "spec.pdf", "section": section,
            "page_start": 1, "page_end": 1, "text": text, "rerank_score": score,
            "separation": sep, "rrf": 0.03, "context": None, "score": score}


SMALL = _hit("c-small", "4.2 Pipes 2 inch and smaller",
             "The minimum wall thickness of process pipe shall be 3 mm.", 5.0, 0.0)
LARGE = _hit("c-large", "4.3 Pipes larger than 2 inch",
             "The minimum wall thickness of process pipe shall be 6 mm.", 4.8, 0.05)


@pytest.fixture
def plausible(monkeypatch):
    """Every rival lexically plausible - the lexical gate is tested elsewhere."""
    monkeypatch.setattr(lexical, "assess", lambda *a, **k: {
        "ok": True, "reason": None, "coverage": 1.0, "terms": [], "covered": [],
        "absent_from_corpus": []})


def _choose(question: str, hits: list[dict]):
    return answer_mod._condition_choice(question, hits, hits[0], None, frozenset({"d1"}))


def test_a_question_naming_a_size_gets_the_clause_for_that_size(plausible):
    """THE CASE: the 2-inch-and-smaller clause ranked first; the question is
    about a 6 inch pipe. The larger-pipe clause answers."""
    choice = _choose("minimum wall thickness for a 6 inch process pipe", [SMALL, LARGE])
    assert choice["mode"] == "matched"
    assert choice["winner"]["chunk_id"] == "c-large"
    assert choice["question_names"] == ["6 inch"]


def test_a_question_naming_no_size_is_shown_every_clause_with_its_size(plausible):
    choice = _choose("minimum wall thickness for process pipe", [SMALL, LARGE])
    assert choice["mode"] == "options"
    assert [o["conditions"] for o in choice["options"]] == [
        ["2 inch and smaller"], ["larger than 2 inch"]]
    assert "does not say which applies" in choice["reason"]


def test_when_the_top_clause_already_applies_nothing_is_said(plausible):
    assert _choose("minimum wall thickness for a 1 inch process pipe", [SMALL, LARGE]) is None


def test_a_rival_stating_the_same_values_is_a_duplicate_not_a_rival(plausible):
    same = dict(LARGE, text="The minimum wall thickness of process pipe shall be 3 mm.")
    assert _choose("minimum wall thickness for process pipe", [SMALL, same]) is None


def test_a_rival_far_below_the_top_does_not_compete(plausible):
    far = dict(LARGE, separation=0.9)
    assert _choose("minimum wall thickness for process pipe", [SMALL, far]) is None


def test_a_rival_the_lexical_gate_rejects_does_not_compete(monkeypatch):
    monkeypatch.setattr(lexical, "assess", lambda *a, **k: {"ok": False})
    assert _choose("minimum wall thickness for process pipe", [SMALL, LARGE]) is None


def test_a_question_whose_condition_no_single_clause_meets_keeps_the_top(plausible):
    """Never a guess: a condition that holds for neither (or both) changes
    nothing - the top passage answers, as it did before."""
    sour = dict(SMALL, section="4.2 Pipes in sour service")
    dry = _hit("c-dry", "4.4 Pipes in dry service",
               "The minimum wall thickness of process pipe shall be 4 mm.", 4.9)
    # the two DO compete - asked with no condition, both are shown ...
    assert _choose("minimum wall thickness for process pipe", [sour, dry])["mode"] == "options"
    # ... asked for a service neither is written for, the top one stands
    assert _choose("minimum wall thickness for process pipe in wet service", [sour, dry]) is None


# ------------------------------------------------------------- end to end

PIPING = [
    "4 Piping",
    "4.1 General",
    "All process piping shall be designed to the governing piping code and",
    "every line shall be hydrostatically tested before it is put into service.",
    "4.2 Pipes 2 inch and smaller",
    "The minimum wall thickness of carbon steel process pipe shall be 3 mm",
    "for every line in this size range, including all small bore connections.",
    "4.3 Pipes larger than 2 inch",
    "The minimum wall thickness of carbon steel process pipe shall be 6 mm",
    "for every line in this size range, including all headers and branches.",
]


@pytest.fixture
def piping(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "spec.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(PIPING):
        page.insert_text((72, 90 + i * 15), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = TestClient(app).post(
            "/api/documents", files={"file": ("spec.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    yield frozenset({doc_id})
    db.reset_connection()


def test_an_unsized_question_shows_both_clauses_as_the_answer(piping):
    r = answer_mod.answer("what is the minimum wall thickness of carbon steel process pipe",
                          allowed_document_ids=piping)
    assert r["answer_type"] == "extract"
    assert r["condition_choice"]["mode"] == "options"
    answered = {p["section"] for p in r["answer_passages"]}
    assert answered == {"4.2 Pipes 2 inch and smaller", "4.3 Pipes larger than 2 inch"}
    # neither is demoted to "supporting"
    assert not answered & {p["section"] for p in r["supporting"]}


@pytest.mark.parametrize(("size", "section"), [
    ("6 inch", "4.3 Pipes larger than 2 inch"),
    ("1 inch", "4.2 Pipes 2 inch and smaller"),
])
def test_a_sized_question_is_answered_from_the_clause_for_that_size(piping, size, section):
    r = answer_mod.answer(
        f"what is the minimum wall thickness of carbon steel process pipe for a {size} line",
        allowed_document_ids=piping)
    assert r["passage"]["section"] == section
    assert (r.get("condition_choice") or {}).get("mode") != "options"


def test_the_choice_is_kept_when_a_conversation_is_reopened():
    assert "condition_choice" in chat._PAYLOAD_KEYS


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "e.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def test_the_answer_quotes_the_clause_the_condition_chose(monkeypatch, plausible, empty_db):
    """Through `answer()`: the reranker put the 2-inch-and-smaller clause
    first; the question names 6 inch; the larger-pipe clause is QUOTED, and
    the clause that ranked first stays visible as supporting."""
    from app import passages as passages_mod
    from app import search as search_mod
    monkeypatch.setattr(search_mod, "search", lambda *a, **k: {
        "hits": [dict(SMALL), dict(LARGE)], "mode": "hybrid", "reranked": True,
        "timings": {}, "total": 2, "seconds": 0.0})
    monkeypatch.setattr(passages_mod, "expand_passage", lambda *a, **k: {})
    monkeypatch.setattr(answer_mod, "_coverage", lambda *a, **k: None)
    r = answer_mod.answer("what is the minimum wall thickness for a 6 inch process pipe",
                          allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "extract"
    assert r["passage"]["chunk_id"] == "c-large"
    assert r["answer"] == LARGE["text"]
    assert r["condition_choice"]["mode"] == "matched"
    assert "c-small" in {p["chunk_id"] for p in r["supporting"]}
