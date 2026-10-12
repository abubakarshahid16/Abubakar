"""Which clause applies, closed limits (docs/limitations.md, plan step 4):

1. ONE passage (a clause or a table) listing several cases: the line whose
   condition holds is highlighted and named; with no condition named, every
   line is listed. The quoted text is never altered.
2. An options answer is not "supported": answerability says
   depends_on_condition.
3. Tier 2 (generated): a named condition sends the clause that holds first
   and never the clause written for another case; with none named, the
   options notice is attached. The model's prose is not touched.
4. Two clauses of ONE document stating different values are a conflict,
   unless the condition reader explains them.

Synthetic text only. Mutations M1580-M1599 (scripts/mutations/condition_choice_2.py).
"""
from __future__ import annotations

import typing

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import answer as answer_mod
from app import answerability, db, keyword, lexical, schemas
from app import condition_choice as cc
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

# ------------------------------------------------------- 1. one passage, several cases

LISTED = ("The minimum wall thickness of carbon steel process pipe shall be as follows: "
          "pipes 2 inch and smaller: 3 mm; pipes larger than 2 inch: 6 mm.")
TABLE = ("| Pipe size | Minimum wall thickness |\n"
         "| 2 inch and smaller | 3 mm |\n"
         "| over 2 inch to 6 inch | 6 mm |\n"
         "| larger than 6 inch | 9 mm |")


def test_a_clause_listing_two_sizes_is_read_as_two_lines():
    got = cc.cases(LISTED)
    assert [c.text for c in got] == ["pipes 2 inch and smaller: 3 mm", "pipes larger than 2 inch: 6 mm"]
    assert [LISTED[c.start:c.end] for c in got] == [c.text for c in got]
    assert [set(c.values) for c in got] == [{"3"}, {"6"}]


def test_a_table_whose_rows_are_size_ranges_is_read_row_by_row():
    """The header's "wall thickness" must not make the row below it read as a
    measured value, and a range row's own numbers are not its value."""
    got = cc.cases(TABLE)
    assert [c.condition.text for c in got] == ["2 inch and smaller", "2 inch to 6 inch", "larger than 6 inch"]
    assert [set(c.values) for c in got] == [{"3"}, {"6"}, {"9"}]


@pytest.mark.parametrize("text", [
    "Pipes 2 inch and smaller: 3 mm; pipes larger than 2 inch: 3 mm.",   # one value for both
    "The minimum wall thickness of process pipe shall be 3 mm.",          # no condition
    "Pipes larger than 2 inch: 6 mm.",                                     # one case
])
def test_a_passage_that_is_not_a_list_of_cases_has_none(text):
    assert cc.cases(text) == []


def _payload(text: str, question: str) -> dict:
    span = answer_mod.find_answer_span(question, text)
    return {"chunk_id": "c1", "document_id": "d1", "filename": "spec.pdf", "section": "4.2 Wall",
            "page_start": 3, "page_end": 3, "text": text, "highlight": list(span) if span else None}


def test_a_size_no_line_meets_changes_nothing():
    """Never a guess: a 1 inch pipe holds for no row of a table that starts
    above 2 inch, so no line is picked and the highlight is left as it was."""
    text = ("| Pipe size | Minimum wall thickness |\n"
            "| over 2 inch to 6 inch | 6 mm |\n| larger than 6 inch | 9 mm |")
    q = "minimum wall thickness for a 1 inch pipe"
    p = _payload(text, q)
    before = p["highlight"]
    assert answer_mod._passage_cases(q, p) is None
    assert p["highlight"] == before


def test_an_unsized_question_does_not_leave_the_highlight_on_one_line():
    """THE DEFECT: vocabulary put the highlight on the larger-pipe line
    (numbers are ignored), and the reader took 6 mm for THE answer."""
    text = "Pipes 2 inch and smaller: 3 mm. Pipes larger than 2 inch: 6 mm."
    p = dict(_payload(text, "q"), highlight=[32, 62])      # where vocabulary put it
    choice = answer_mod._passage_cases("minimum wall thickness for pipes", p)
    assert choice["mode"] == "options"
    assert p["highlight"] == [0, 62] and p["text"] == text


def test_a_list_of_cases_away_from_the_answered_sentence_is_not_the_answer():
    """A passage answering a hydrotest question that also lists wall
    thicknesses is not a question about which size applies."""
    text = ("Pipes 2 inch and smaller: 3 mm; pipes larger than 2 inch: 6 mm. "
            "Every line shall be hydrostatically tested for 30 minutes after erection is complete.")
    q = "how long shall every line be hydrostatically tested after erection"
    assert answer_mod._passage_cases(q, _payload(text, q)) is None


LISTED_PDF = [
    "4 Piping",
    "4.1 General",
    "All process piping shall be designed to the governing piping code and",
    "every line shall be hydrostatically tested before it is put into service.",
    "4.2 Minimum wall thickness",
    "The minimum wall thickness of carbon steel process pipe shall be as follows:",
    "pipes 2 inch and smaller: 3 mm;",
    "pipes larger than 2 inch: 6 mm.",
    "4.3 Testing",
    "Every line shall be hydrostatically tested at 1.5 times design pressure.",
]


def _library(tmp_path, monkeypatch, pages: dict[str, list[list[str]]]) -> dict[str, str]:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    ids = {}
    for name, blocks in pages.items():
        path = tmp_path / name
        doc = pymupdf.open()
        for lines in blocks:
            page = doc.new_page()
            for i, line in enumerate(lines):
                page.insert_text((72, 90 + i * 15), line)
        doc.save(str(path))
        doc.close()
        with open(path, "rb") as fh:
            ids[name] = TestClient(app).post(
                "/api/documents", files={"file": (name, fh, "application/pdf")}
            ).json()["document"]["id"]
        IngestionWorker().process(ids[name])
    return ids


@pytest.fixture
def listed(tmp_path, monkeypatch):
    ids = _library(tmp_path, monkeypatch, {"spec.pdf": [LISTED_PDF]})
    yield frozenset(ids.values())
    db.reset_connection()


def test_an_unsized_question_lists_the_lines_of_the_one_passage(listed):
    r = answer_mod.answer("what is the minimum wall thickness of carbon steel process pipe",
                          allowed_document_ids=listed)
    choice = r["condition_choice"]
    assert choice["mode"] == "options" and choice["within_passage"] is True
    assert [o["conditions"] for o in choice["options"]] == [["2 inch and smaller"], ["larger than 2 inch"]]
    assert [o["line"] for o in choice["options"]] == ["pipes 2 inch and smaller: 3 mm",
                                                      "pipes larger than 2 inch: 6 mm"]
    assert {o["chunk_id"] for o in choice["options"]} == {r["passage"]["chunk_id"]}
    # the highlight covers every line, not one of them
    text, (a, b) = r["passage"]["text"], r["passage"]["highlight"]
    assert "3 mm" in text[a:b] and "6 mm" in text[a:b]
    # the quoted text is the passage as written
    assert r["answer"] == LISTED and text == LISTED


@pytest.mark.parametrize(("size", "line"), [
    ("6 inch", "pipes larger than 2 inch: 6 mm"),
    ("1 inch", "pipes 2 inch and smaller: 3 mm"),
])
def test_a_sized_question_highlights_the_line_for_that_size(listed, size, line):
    r = answer_mod.answer(
        f"what is the minimum wall thickness of carbon steel process pipe for a {size} line",
        allowed_document_ids=listed)
    text, (a, b) = r["passage"]["text"], r["passage"]["highlight"]
    assert text[a:b] == line
    choice = r["condition_choice"]
    assert choice["mode"] == "matched" and choice["within_passage"] is True
    assert choice["options"][0]["line"] == line and choice["question_names"] == [size]
    assert text == LISTED


# --------------------------------------------------------------- 2. the verdict

def test_an_options_answer_is_not_supported(listed):
    r = answer_mod.answer("what is the minimum wall thickness of carbon steel process pipe",
                          allowed_document_ids=listed)
    assert r["answerability"]["verdict"] == answerability.CONDITIONAL


def test_a_sized_answer_is_supported(listed):
    r = answer_mod.answer("what is the minimum wall thickness of carbon steel process pipe for a 6 inch line",
                          allowed_document_ids=listed)
    assert r["answerability"]["verdict"] == answerability.SUPPORTED


def test_the_verdict_is_declared_in_the_response_schema():
    declared = set(typing.get_args(schemas.Answerability.model_fields["verdict"].annotation))
    assert declared == set(answerability.VERDICTS)
    assert schemas.ConditionChoice(mode="options", reason="r", within_passage=True).within_passage


# ------------------------------------------------------------- tier 2 and clauses

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
    monkeypatch.setattr(lexical, "assess", lambda *a, **k: {
        "ok": True, "reason": None, "coverage": 1.0, "terms": [], "covered": [],
        "absent_from_corpus": []})


@pytest.fixture
def empty_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "e.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield
    db.reset_connection()


@pytest.fixture
def searched(monkeypatch, plausible, empty_db):
    """Search returns SMALL then LARGE; the model is faked and records its prompt."""
    from app import passages as passages_mod
    from app import search as search_mod
    monkeypatch.setattr(search_mod, "search", lambda *a, **k: {
        "hits": [dict(SMALL), dict(LARGE)], "mode": "hybrid", "reranked": True,
        "timings": {}, "total": 2, "seconds": 0.0})
    monkeypatch.setattr(passages_mod, "expand_passage", lambda *a, **k: {})
    monkeypatch.setattr(answer_mod, "_coverage", lambda *a, **k: None)
    seen: dict = {}

    def model(prompt, timeout=180.0):
        seen["prompt"] = prompt
        return {"response": seen.get("reply", "The minimum is 3 mm [S1]."), "done_reason": "stop"}
    monkeypatch.setattr(answer_mod, "_call_model", model)
    return seen


def test_a_generated_answer_to_an_unsized_question_carries_the_options_notice(searched):
    searched["reply"] = "Small pipe needs 3 mm [S1]. Larger pipe needs 6 mm [S2]."
    r = answer_mod.answer("what is the minimum wall thickness for process pipe", tier="generated",
                          allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "generated"
    assert r["answer"] == searched["reply"]          # the prose is the model's, untouched
    choice = r["condition_choice"]
    assert choice["mode"] == "options"
    assert {o["chunk_id"] for o in choice["options"]} == {"c-small", "c-large"}
    assert "may mix them" in choice["reason"]
    assert r["answerability"]["verdict"] == answerability.CONDITIONAL


def test_a_generated_answer_to_a_sized_question_is_given_the_clause_that_holds(searched):
    searched["reply"] = "The minimum is 6 mm [S1]."
    r = answer_mod.answer("what is the minimum wall thickness for a 6 inch process pipe",
                          tier="generated", allowed_document_ids=frozenset({"d1"}))
    assert "shall be 6 mm" in searched["prompt"]
    assert "shall be 3 mm" not in searched["prompt"]      # the 2-inch clause is not sent
    assert r["answer_type"] == "generated"
    assert r["condition_choice"]["mode"] == "matched"
    assert r["condition_choice"]["options"][0]["chunk_id"] == "c-large"


def test_the_notice_names_only_passages_the_model_was_given(searched, monkeypatch):
    real = answer_mod.context_budget_for_lane
    monkeypatch.setattr(answer_mod, "context_budget_for_lane", lambda: {**real(), "passages": 1})
    r = answer_mod.answer("what is the minimum wall thickness for process pipe", tier="generated",
                          allowed_document_ids=frozenset({"d1"}))
    assert r["answer_type"] == "generated"
    assert r["condition_choice"] is None


# ------------------------------------------------------ 4. same-document conflicts

PRESSURE_A = {"chunk_id": "a", "document_id": "d1", "page_start": 2, "page_end": 2,
              "section": "4.2 Design pressure",
              "text": "The design pressure of every storage vessel shall be 3.5 bar gauge."}
PRESSURE_B = {"chunk_id": "b", "document_id": "d1", "page_start": 9, "page_end": 9,
              "section": "9.1 Vessel data",
              "text": "The design pressure of every storage vessel shall be 5 bar gauge."}


def _assess(passages: list[dict], question="what is the design pressure of the storage vessels?"):
    result = {"answer_type": "extract", "passage": passages[0], "supporting": passages[1:]}
    return answerability.assess(question, result, allowed_document_ids=frozenset({"d1"}))


def test_two_clauses_of_one_document_stating_different_values_are_a_conflict(plausible, empty_db):
    v = _assess([PRESSURE_A, PRESSURE_B])
    assert v["verdict"] == answerability.CONFLICTING
    assert "same document" in v["reason"]
    assert [e["section"] for e in v["evidence"]] == ["4.2 Design pressure", "9.1 Vessel data"]


def test_two_chunks_of_one_clause_are_not_a_conflict(plausible, empty_db):
    assert _assess([PRESSURE_A, dict(PRESSURE_B, section=PRESSURE_A["section"])])["verdict"] \
        == answerability.SUPPORTED


def test_clauses_for_different_sizes_are_explained_not_a_conflict(plausible, empty_db):
    v = _assess([SMALL, LARGE], "what is the minimum wall thickness for process pipe")
    assert v["verdict"] == answerability.SUPPORTED


def test_a_same_document_conflict_is_flagged_end_to_end(tmp_path, monkeypatch):
    ids = _library(tmp_path, monkeypatch, {"vessels.pdf": [
        ["4.2 Design Pressure",
         "The design pressure of every storage vessel shall be 3.5 bar gauge",
         "measured at the top of the shell for the full operating range."],
        ["9.1 Vessel Data Sheet",
         "The design pressure of every storage vessel shall be 5 bar gauge",
         "as entered on the vendor data sheet for the full operating range."],
    ]})
    try:
        r = answer_mod.answer("what is the design pressure of the storage vessels?",
                              allowed_document_ids=frozenset(ids.values()))
        assert r["answerability"]["verdict"] == answerability.CONFLICTING
        assert "same document" in r["answerability"]["reason"]
    finally:
        db.reset_connection()
