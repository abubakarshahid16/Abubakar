"""Question filler and plain decimals are not subjects the passage must repeat.

Two ways a good answer was refused as "not in the indexed documents":

1. Question filler ("does", "say", "says", "mention", "according", ...) was
   not in STOPWORDS, so it counted as a distinctive term. It is absent from
   the corpus by nature (a standard does not write "say"), and with it the
   question crossed LONG_QUESTION_TERM_COUNT and needed two shared terms
   instead of one.
2. A plain decimal ("2.5", "0.75") matched `keyword.IDENTIFIER` (its
   clause-number shape) and was held to be a named subject that must appear
   in the corpus. A value the reader typed is not a designation.

A designation (ASTM A106, SAES-W-017, API 5L, STD-A-001) and a three-part
clause number (5.3.2) must still count. All names below are invented.
"""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, keyword, lexical
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

NO_SCOPE = frozenset()


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def upload(client, blocks, name="STD-A-001.pdf") -> str:
    path = settings.data_dir / name
    doc = pymupdf.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


COVER = ["1", "Scope", "This invented specification covers tank linings."]
ANSWER = ["4", "Lining thickness",
          "The lining thickness shall be checked after every cure cycle."]
ELSEWHERE = ["7", "Storage", "Primer storage shall be dry and ventilated."]

FILLER = ["say", "says", "said", "mention", "mentions", "mentioned", "state",
          "states", "stated", "according", "does", "about", "what", "which",
          "shall", "required", "requirement", "requirements", "specified",
          "describe", "described", "define", "defined", "provide", "provides",
          "regarding", "concerning", "tell"]


@pytest.mark.parametrize("word", FILLER)
def test_question_filler_is_not_a_distinctive_term(word):
    """MUTATION TARGET: the word never reaches the term list."""
    terms = lexical.distinctive_terms(
        f"what does the lining {word} about thickness", allowed_document_ids=NO_SCOPE)
    assert word not in [t.lower() for t in terms], terms
    assert [t.lower() for t in terms] == ["lining", "thickness"], terms


@pytest.mark.parametrize("word", [
    "pressure", "test", "design", "material", "thickness", "temperature",
    "inspection", "coating", "welding", "pipe", "valve", "flange", "hardness",
    "surface", "preparation", "cure", "primer", "gasket", "bolt", "voltage"])
def test_real_engineering_words_still_count(word):
    """NOT VACUOUS: the filler list must not swallow engineering vocabulary."""
    terms = lexical.distinctive_terms(
        f"what is the {word}", allowed_document_ids=NO_SCOPE)
    assert word in [t.lower() for t in terms], terms


def test_filler_does_not_turn_a_good_answer_into_a_refusal():
    """MUTATION TARGET: three words of filler plus two topic words. The
    passage carries one topic word; the question needs one shared term, not
    two, once the filler is gone."""
    client = TestClient(app)
    a = upload(client, [COVER, ANSWER, ELSEWHERE])
    verdict = lexical.assess(
        "What does it say about lining thickness?",
        " ".join(ANSWER), allowed_document_ids=frozenset({a}))
    assert verdict["terms"] == ["lining", "thickness"], verdict
    assert verdict["ok"] is True, verdict


def test_a_passage_with_no_topic_term_is_still_refused():
    """NOT VACUOUS: filler gives no credit; an unrelated passage fails."""
    client = TestClient(app)
    a = upload(client, [COVER, ANSWER, ELSEWHERE])
    verdict = lexical.assess(
        "What does it say about lining thickness?",
        " ".join(ELSEWHERE), allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is False, verdict


@pytest.mark.parametrize("number", ["2.5", "0.75", "1.6", "10.9"])
def test_a_plain_decimal_is_not_a_distinctive_term(number):
    """MUTATION TARGET."""
    terms = lexical.distinctive_terms(
        f"what is the lining thickness of {number} mm", allowed_document_ids=NO_SCOPE)
    assert number not in terms, terms
    assert [t.lower() for t in terms] == ["lining", "thickness"], terms


@pytest.mark.parametrize("number", ["2.5", "0.75", "1.6"])
def test_a_plain_decimal_is_not_a_named_subject(number):
    """MUTATION TARGET: a term that reaches the absent list is only fatal if
    it looks like a named subject."""
    assert lexical.looks_like_a_named_subject(number, f"thickness {number} mm") is False


def test_a_decimal_absent_from_the_corpus_does_not_refuse_the_question():
    """MUTATION TARGET: end to end. The corpus never prints 2.5; the question
    is still answered by the lining page."""
    client = TestClient(app)
    a = upload(client, [COVER, ANSWER, ELSEWHERE])
    verdict = lexical.assess(
        "What is the lining thickness of 2.5 mm?",
        " ".join(ANSWER), allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is True, verdict
    assert verdict["absent_from_corpus"] == [], verdict


@pytest.mark.parametrize("designation", [
    "ASTM A106", "SAES-W-017", "API 5L", "STD-A-001", "ISO 13709", "P-101A"])
def test_a_designation_still_counts(designation):
    """NOT VACUOUS: dropping decimals must not drop designations."""
    question = f"what does {designation} require for lining thickness"
    terms = lexical.distinctive_terms(question, allowed_document_ids=NO_SCOPE)
    assert designation in terms, terms
    assert lexical.looks_like_a_named_subject(designation, question) is True


def test_a_three_part_clause_number_still_counts():
    """NOT VACUOUS: 5.3.2 is a clause, not a decimal."""
    terms = lexical.distinctive_terms(
        "what does clause 5.3.2 say about lining", allowed_document_ids=NO_SCOPE)
    assert "5.3.2" in terms, terms


def test_an_absent_designation_still_refuses():
    """NOT VACUOUS: a named standard that is not indexed is still a refusal,
    with a decimal and filler in the same question."""
    client = TestClient(app)
    a = upload(client, [COVER, ANSWER, ELSEWHERE])
    verdict = lexical.assess(
        "What does ASTM A106 say about lining thickness of 2.5 mm?",
        " ".join(ANSWER), allowed_document_ids=frozenset({a}))
    assert verdict["ok"] is False, verdict
    assert "ASTM A106" in verdict["reason"], verdict
